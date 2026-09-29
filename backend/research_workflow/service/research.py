import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from opentelemetry.trace import get_current_span
from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from backend.db import db_utils, schemas
from backend.db.schemas import ResearchRun, ResearchRunStatus
from backend.research_workflow.agent.agent import (
    model_name,
    prompt_version,
    run_research_briefing_agent,
    schema_version,
    tool_version,
)
from backend.research_workflow.agent.classifiers import (
    revise_finding,
    run_query_classifier,
    synthesize_narrative,
    verify_finding,
)
from backend.research_workflow.agent.evidence import (
    build_financial_evidence_candidates,
    catalog_from_candidates,
    compact_financial_evidence,
    hydrate_briefing,
    load_evidence_catalog,
)
from backend.research_workflow.agent.models import (
    BriefingRequest,
    DocumentEvidence,
    DraftResearchBriefing,
    EvidenceRecord,
    FinancialEvidence,
    Finding,
    GroundingFailure,
    ResearchBriefing,
    ResearchWorkflowResult,
    VerificationResult,
)
from backend.research_workflow.data.market_data import (
    get_close_data,
    get_company_snapshot,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

RESEARCH_SEMAPHORE = asyncio.Semaphore(2)
AGENT_COMPLETED_CHECKPOINT = "agent_completed"
VERIFICATION_COMPLETED_CHECKPOINT = "verification_completed"


def current_trace_id() -> str | None:
    span_context = get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"


def create_fingerprint(request: BriefingRequest) -> str:
    fingerprint_input = {
        "request": {
            "symbol": request.symbol.strip().upper(),
            "as_of": request.as_of.astimezone(timezone.utc).isoformat(),
            "research_question": " ".join(request.research_question.split()),
            "audience": request.audience.strip().lower(),
            "time_horizon": request.time_horizon.strip().lower(),
        },
        "model_name": model_name,
        "prompt_version": prompt_version,
        "tool_version": tool_version,
        "schema_version": schema_version,
    }
    canonical_json = json.dumps(
        fingerprint_input,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical_json.encode()).hexdigest()


def _checkpoint_state(
    payload: dict[str, object] | None,
) -> tuple[DraftResearchBriefing, dict[str, EvidenceRecord], dict[str, object]]:
    if payload is None:
        raise ValueError("Checkpoint payload is missing")
    draft = DraftResearchBriefing.model_validate(payload.get("draft_briefing"))
    catalog = load_evidence_catalog(payload.get("evidence_catalog"))
    financial_sources = payload.get("financial_sources")
    if not isinstance(financial_sources, dict):
        raise TypeError("Checkpoint financial sources are missing or invalid")
    return draft, catalog, {str(key): value for key, value in financial_sources.items()}


def _prefetched_financial_context(
    symbol: str,
    company_snapshot: dict[str, object],
    close_data: list[dict[str, str | float]],
) -> tuple[
    dict[str, object],
    dict[str, EvidenceRecord],
    dict[str, object],
]:
    snapshot_reference = f"company_snapshot:{symbol}"
    close_reference = f"close_data:{symbol}"
    snapshot_candidates = [
        candidate
        for candidate in build_financial_evidence_candidates(
            reference_id=snapshot_reference,
            title=f"{symbol} company snapshot",
            source="Yahoo Finance",
            url=f"https://finance.yahoo.com/quote/{symbol}/",
            data=company_snapshot,
        )
        if candidate.value is not None
        and not candidate.field_path.startswith("latest_news_headlines")
    ]
    close_candidates = build_financial_evidence_candidates(
        reference_id=close_reference,
        title=f"{symbol} recent close prices",
        source="Yahoo Finance",
        url=f"https://finance.yahoo.com/quote/{symbol}/history/",
        data=close_data,
    )
    price_summary, selected_close_candidates = _compact_price_summary(
        close_data,
        close_candidates,
    )
    candidates: list[FinancialEvidence] = [
        *snapshot_candidates,
        *selected_close_candidates,
    ]
    snapshot_for_agent = {
        key: value
        for key, value in company_snapshot.items()
        if key != "latest_news_headlines"
    }
    prefetched_context: dict[str, object] = {
        "company_snapshot": snapshot_for_agent,
        "recent_price_summary": price_summary,
        "evidence_candidates": [
            compact_financial_evidence(candidate) for candidate in candidates
        ],
    }
    return (
        prefetched_context,
        catalog_from_candidates(candidates),
        {
            snapshot_reference: company_snapshot,
            close_reference: close_data,
        },
    )


def _compact_price_summary(
    close_data: list[dict[str, str | float]],
    candidates: list[FinancialEvidence],
) -> tuple[dict[str, object] | None, list[FinancialEvidence]]:
    priced_rows = [
        (index, row)
        for index, row in enumerate(close_data)
        if isinstance(row.get("Close"), (int, float))
    ]
    if not priced_rows:
        return None, []

    first = priced_rows[0]
    latest = priced_rows[-1]
    low = min(priced_rows, key=lambda item: float(item[1]["Close"]))
    high = max(priced_rows, key=lambda item: float(item[1]["Close"]))
    selected_points = {
        "period_start": first,
        "period_end": latest,
        "period_low": low,
        "period_high": high,
    }
    selected_paths = {
        f"{index}.{field_name}"
        for index, _ in selected_points.values()
        for field_name in ("Date", "Close")
    }
    selected_candidates = [
        candidate for candidate in candidates if candidate.field_path in selected_paths
    ]
    candidate_by_path = {
        candidate.field_path: candidate for candidate in selected_candidates
    }

    summary: dict[str, object] = {}
    for label, (index, row) in selected_points.items():
        evidence_ids = [
            candidate_by_path[path].evidence_id
            for path in (f"{index}.Date", f"{index}.Close")
            if path in candidate_by_path
        ]
        summary[label] = {
            "date": row.get("Date"),
            "close": row["Close"],
            "evidence_ids": evidence_ids,
        }

    start_close = float(first[1]["Close"])
    end_close = float(latest[1]["Close"])
    summary["period_change_pct"] = (
        round(((end_close / start_close) - 1) * 100, 2) if start_close != 0 else None
    )
    return summary, selected_candidates


async def run_research_workflow(request: BriefingRequest) -> ResearchWorkflowResult:
    run_id: uuid.UUID | None = None
    draft: DraftResearchBriefing | None = None
    catalog: dict[str, EvidenceRecord] | None = None
    financial_sources: dict[str, object] | None = None
    resuming_from_checkpoint = False
    try:
        fingerprint = create_fingerprint(request)
        async with RESEARCH_SEMAPHORE, asyncio.timeout(180):
            with db_utils.get_session() as session:
                cached_run = (
                    session.query(ResearchRun)
                    .filter(
                        ResearchRun.request_fingerprint == fingerprint,
                        ResearchRun.status.in_(
                            [
                                ResearchRunStatus.PENDING,
                                ResearchRunStatus.RUNNING,
                                ResearchRunStatus.COMPLETED,
                            ]
                        ),
                    )
                    .order_by(ResearchRun.completed_at.desc())
                    .first()
                )
                if cached_run:
                    logger.info(
                        "research_run_cache_hit run_id=%s symbol=%s status=%s",
                        cached_run.id,
                        request.symbol.strip().upper(),
                        cached_run.status.value,
                    )
                    return ResearchWorkflowResult(
                        run_id=cached_run.id,
                        status=cached_run.status,
                        briefing=(
                            ResearchBriefing.model_validate(cached_run.briefing_payload)
                            if cached_run.briefing_payload
                            else None
                        ),
                        verification=(
                            VerificationResult.model_validate(
                                cached_run.verification_payload
                            )
                            if cached_run.verification_payload
                            else None
                        ),
                    )

                checkpointed_run = (
                    session.query(ResearchRun)
                    .filter(
                        ResearchRun.request_fingerprint == fingerprint,
                        ResearchRun.status == ResearchRunStatus.FAILED,
                        ResearchRun.checkpoint_stage == AGENT_COMPLETED_CHECKPOINT,
                        ResearchRun.checkpoint_payload.is_not(None),
                    )
                    .order_by(ResearchRun.completed_at.desc())
                    .first()
                )
                if checkpointed_run:
                    run_id = checkpointed_run.id
                    draft, catalog, financial_sources = _checkpoint_state(
                        checkpointed_run.checkpoint_payload
                    )
                    checkpointed_run.status = ResearchRunStatus.RUNNING
                    checkpointed_run.error_payload = None
                    checkpointed_run.completed_at = None
                    checkpointed_run.started_at = datetime.now(timezone.utc)
                    checkpointed_run.trace_id = current_trace_id()
                    resuming_from_checkpoint = True

            if resuming_from_checkpoint:
                logger.info(
                    "research_run_checkpoint_resumed run_id=%s symbol=%s stage=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    AGENT_COMPLETED_CHECKPOINT,
                )

            if not resuming_from_checkpoint:
                now = datetime.now(timezone.utc)
                with db_utils.get_session() as session:
                    research_run = schemas.ResearchRun(
                        request_fingerprint=fingerprint,
                        symbol=request.symbol.strip().upper(),
                        as_of=request.as_of,
                        status=ResearchRunStatus.PENDING,
                        request_payload=request.model_dump(mode="json"),
                        model_name=model_name,
                        prompt_version=prompt_version,
                        tool_version=tool_version,
                        schema_version=schema_version,
                        started_at=now,
                        trace_id=current_trace_id(),
                    )
                    session.add(research_run)
                    session.flush()
                    run_id = research_run.id

                logger.info(
                    "research_run_created run_id=%s symbol=%s status=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    ResearchRunStatus.PENDING.value,
                )
                if run_id is None:
                    raise RuntimeError("Research run ID was not generated")
                if request.as_of > now:
                    raise ValueError(f"{request.as_of} cannot be after today")
                if len(request.research_question) < 30:
                    raise ValueError(
                        f"{request.research_question} does not meet length requirements!"
                    )

                query_classification = await run_query_classifier(
                    request.symbol, request.research_question, run_id
                )
                logger.info(
                    "query_classification_completed run_id=%s symbol=%s "
                    "is_relevant=%s reason=%s",
                    run_id,
                    request.symbol,
                    query_classification.is_relevant,
                    query_classification.reasoning,
                )
                if not query_classification.is_relevant:
                    raise ValueError(
                        "Query classification not relevant reasoning: "
                        f"{query_classification.reasoning}"
                    )

                company_snapshot, close_data = await asyncio.gather(
                    asyncio.to_thread(get_company_snapshot, request.symbol),
                    asyncio.to_thread(get_close_data, request.symbol),
                )
                prefetched_context, catalog, financial_sources = (
                    _prefetched_financial_context(
                        request.symbol.strip().upper(), company_snapshot, close_data
                    )
                )

                with db_utils.get_session() as session:
                    research_run = session.get(ResearchRun, run_id)
                    if research_run is None:
                        raise ValueError(f"Research run {run_id} not found")
                    research_run.status = ResearchRunStatus.RUNNING
                    research_run.started_at = datetime.now(timezone.utc)

                logger.info(
                    "research_run_started run_id=%s symbol=%s status=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    ResearchRunStatus.RUNNING.value,
                )
                execution = await run_research_briefing_agent(
                    run_id=run_id,
                    request=request,
                    prefetched_context=prefetched_context,
                    evidence_catalog=catalog,
                    financial_sources=financial_sources,
                )
                result = execution.result
                draft = result.output
                if not draft.key_findings:
                    raise RuntimeError("Research agent returned no key findings")

                catalog = execution.evidence_catalog
                financial_sources = execution.financial_sources

                with db_utils.get_session() as session:
                    research_run = session.get(ResearchRun, run_id)
                    if research_run is None:
                        raise RuntimeError(f"Research run {run_id} not found")
                    research_run.usage_payload = to_jsonable_python(
                        asdict(result.usage)
                    )
                    research_run.checkpoint_stage = AGENT_COMPLETED_CHECKPOINT
                    research_run.checkpoint_payload = to_jsonable_python(
                        {
                            "draft_briefing": draft.model_dump(mode="json"),
                            "evidence_catalog": [
                                item.model_dump(mode="json")
                                for item in catalog.values()
                            ],
                            "financial_sources": financial_sources,
                        }
                    )

                logger.info(
                    "research_run_checkpoint_saved run_id=%s symbol=%s stage=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    AGENT_COMPLETED_CHECKPOINT,
                )

            if (
                run_id is None
                or draft is None
                or catalog is None
                or financial_sources is None
            ):
                raise RuntimeError("Research workflow state is incomplete")

            briefing, unresolved_ids = hydrate_briefing(draft, catalog)
            verification = VerificationResult(
                invalid_evidence_references=unresolved_ids,
                approval_ready=True,
            )
            grounding_inputs: list[
                tuple[int, Finding, list[EvidenceRecord], str | None]
            ] = []
            with db_utils.get_session() as session:
                for index, finding in enumerate(briefing.key_findings):
                    valid_evidence: list[EvidenceRecord] = []
                    for evidence in finding.evidence:
                        if isinstance(evidence, DocumentEvidence):
                            is_valid = validate_document_evidence(session, evidence)
                        else:
                            is_valid = validate_financial_evidence(
                                evidence, financial_sources
                            )
                        if is_valid:
                            valid_evidence.append(evidence)
                        else:
                            verification.invalid_evidence_references.append(
                                evidence.evidence_id
                            )

                    if not valid_evidence:
                        verification.grounding_failures.append(
                            GroundingFailure(
                                finding_index=index,
                                reason="No valid evidence remained after deterministic validation.",
                            )
                        )
                        continue
                    precheck_failure: str | None = None
                    if finding.confidence == 3 and all(
                        isinstance(item, DocumentEvidence)
                        and item.document_type == schemas.DocumentType.ARTICLE
                        and item.content_quality == "snippet"
                        for item in valid_evidence
                    ):
                        precheck_failure = (
                            "High-confidence claim relies only on article snippets."
                        )
                    grounding_inputs.append(
                        (index, finding, valid_evidence, precheck_failure)
                    )

            verified_findings: list[Finding] = []
            for index, finding, valid_evidence, precheck_failure in grounding_inputs:
                failure_reason = precheck_failure
                if failure_reason is None:
                    try:
                        grounding = await verify_finding(
                            finding, valid_evidence, run_id, index
                        )
                        if grounding.is_supported:
                            verified_findings.append(
                                finding.model_copy(update={"evidence": valid_evidence})
                            )
                            continue
                        failure_reason = grounding.reasoning
                    except Exception:
                        logger.exception(
                            "grounding_classifier_failed run_id=%s finding_index=%s",
                            run_id,
                            index,
                        )
                        failure_reason = "Grounding classifier failed."

                try:
                    revision = await revise_finding(
                        finding,
                        valid_evidence,
                        verified_findings,
                        failure_reason,
                        run_id,
                        index,
                    )
                    if revision.action == "drop_duplicate":
                        logger.info(
                            "research_finding_dropped_as_duplicate "
                            "run_id=%s finding_index=%s",
                            run_id,
                            index,
                        )
                        continue

                    if (
                        revision.statement is None
                        or revision.claim_type is None
                        or revision.confidence is None
                    ):
                        raise ValueError("Finding revision is missing required fields")

                    revised_confidence = min(
                        revision.confidence,
                        finding.confidence,
                    )
                    if revised_confidence < revision.confidence:
                        logger.info(
                            "research_finding_revision_confidence_capped "
                            "run_id=%s finding_index=%s original=%s proposed=%s",
                            run_id,
                            index,
                            finding.confidence,
                            revision.confidence,
                        )

                    revised_finding = Finding(
                        statement=revision.statement,
                        claim_type=revision.claim_type,
                        confidence=revised_confidence,
                        evidence=valid_evidence,
                    )
                    revised_grounding = await verify_finding(
                        revised_finding,
                        valid_evidence,
                        run_id,
                        index,
                    )
                    snippet_only = all(
                        isinstance(item, DocumentEvidence)
                        and item.document_type == schemas.DocumentType.ARTICLE
                        and item.content_quality == "snippet"
                        for item in valid_evidence
                    )
                    if not revised_grounding.is_supported:
                        failure_reason = revised_grounding.reasoning
                    elif revised_finding.confidence == 3 and snippet_only:
                        failure_reason = (
                            "High-confidence claim relies only on article snippets."
                        )
                    else:
                        verified_findings.append(revised_finding)
                        logger.info(
                            "research_finding_revised run_id=%s finding_index=%s",
                            run_id,
                            index,
                        )
                        continue
                except Exception:
                    logger.exception(
                        "research_finding_revision_failed run_id=%s finding_index=%s",
                        run_id,
                        index,
                    )
                    failure_reason = "Finding revision or re-verification failed."

                verification.grounding_failures.append(
                    GroundingFailure(
                        finding_index=index,
                        reason=failure_reason,
                    )
                )

            if not verified_findings:
                raise RuntimeError("No grounded findings remained after verification")

            briefing.key_findings = verified_findings
            all_evidence = list(
                {
                    evidence.evidence_id: evidence
                    for finding in verified_findings
                    for evidence in finding.evidence
                }.values()
            )
            try:
                narrative = await synthesize_narrative(
                    verified_findings,
                    run_id,
                )
                summary_check = await verify_finding(
                    Finding(
                        statement=narrative.executive_summary,
                        claim_type="inference",
                        confidence=2,
                        evidence=all_evidence,
                    ),
                    all_evidence,
                    run_id,
                    -1,
                )
                outlook_check = await verify_finding(
                    Finding(
                        statement=narrative.outlook,
                        claim_type="scenario",
                        confidence=2,
                        evidence=all_evidence,
                    ),
                    all_evidence,
                    run_id,
                    -2,
                )
                briefing.executive_summary = (
                    narrative.executive_summary
                    if summary_check.is_supported
                    else " ".join(
                        finding.statement for finding in verified_findings[:3]
                    )
                )
                briefing.outlook = (
                    narrative.outlook
                    if outlook_check.is_supported
                    else "Monitor the verified findings and cited evidence for changes."
                )
            except Exception:
                logger.exception(
                    "research_narrative_synthesis_failed run_id=%s", run_id
                )
                briefing.executive_summary = " ".join(
                    finding.statement for finding in verified_findings[:3]
                )
                briefing.outlook = (
                    "Monitor the verified findings and cited evidence for changes."
                )

            briefing.limitations = list(
                dict.fromkeys(
                    [
                        *briefing.limitations,
                        "Document searches expose at most three ranked passages per tool call.",
                    ]
                )
            )
            if verification.grounding_failures:
                briefing.limitations.append(
                    "Some candidate findings were excluded after grounding and repair."
                )
            if any(
                isinstance(evidence, DocumentEvidence)
                and evidence.content_quality == "snippet"
                for finding in verified_findings
                for evidence in finding.evidence
            ):
                briefing.limitations.append(
                    "Some article evidence is snippet-quality and should be checked "
                    "against the original source."
                )

            verification.unsupported_finding_indexes = []
            verification.invalid_evidence_references = list(
                dict.fromkeys(verification.invalid_evidence_references)
            )
            verification.approval_ready = not verification.invalid_evidence_references
            workflow_result = ResearchWorkflowResult(
                run_id=run_id,
                status=ResearchRunStatus.COMPLETED,
                briefing=briefing,
                verification=verification,
            )

            with db_utils.get_session() as session:
                research_run = session.get(ResearchRun, run_id)
                if research_run is None:
                    raise RuntimeError(f"Research run {run_id} not found")
                research_run.briefing_payload = briefing.model_dump(mode="json")
                research_run.verification_payload = verification.model_dump(mode="json")
                research_run.checkpoint_stage = VERIFICATION_COMPLETED_CHECKPOINT
                research_run.status = ResearchRunStatus.COMPLETED
                research_run.completed_at = datetime.now(timezone.utc)

            logger.info(
                "research_run_completed run_id=%s symbol=%s status=%s "
                "approval_ready=%s",
                run_id,
                request.symbol.strip().upper(),
                ResearchRunStatus.COMPLETED.value,
                verification.approval_ready,
            )
            return workflow_result

    except Exception as exc:
        if run_id is not None:
            with db_utils.get_session() as session:
                research_run = session.get(ResearchRun, run_id)
                if research_run and research_run.status != ResearchRunStatus.COMPLETED:
                    research_run.status = ResearchRunStatus.FAILED
                    research_run.error_payload = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    research_run.completed_at = datetime.now(timezone.utc)
            logger.error(
                "research_run_failed run_id=%s symbol=%s error_type=%s",
                run_id,
                request.symbol.strip().upper(),
                type(exc).__name__,
            )
        raise


def validate_document_evidence(session: Session, evidence: DocumentEvidence) -> bool:
    try:
        chunk_id = uuid.UUID(evidence.chunk_id)
        document_id = uuid.UUID(evidence.document_id)
    except (TypeError, ValueError):
        return False
    chunk = session.get(schemas.DocumentChunk, chunk_id)
    if chunk is None or chunk.document_id != document_id:
        return False
    document = chunk.document
    if (
        document.reference_id != evidence.reference_id
        or document.document_type != evidence.document_type
        or chunk.chunk_index != evidence.chunk_index
    ):
        return False
    if hashlib.sha256(chunk.content.encode()).hexdigest() != evidence.content_hash:
        return False
    if not 0 <= evidence.start_char < evidence.end_char <= len(chunk.content):
        return False
    return chunk.content[evidence.start_char : evidence.end_char] == evidence.quote


def validate_financial_evidence(
    evidence: FinancialEvidence,
    financial_sources: dict[str, object],
) -> bool:
    source_data = financial_sources.get(evidence.reference_id)
    if source_data is None:
        return False
    try:
        actual_value = resolve_field_path(source_data, evidence.field_path)
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return actual_value == evidence.value


def resolve_field_path(data: object, field_path: str) -> object:
    current = data
    for part in field_path.split("."):
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise TypeError(f"Cannot resolve {part!r} in field path {field_path!r}")
    return current
