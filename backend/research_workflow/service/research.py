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

from backend.db import db_utils, llm_runs, schemas
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
    suggest_web_finding,
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
from backend.research_workflow.agent.jev_classifier import (
    ACCEPT_PROBABILITY,
    JEV_MODEL,
    QUERY_GATE_VERSION,
    REJECT_PROBABILITY,
    classify_research_query,
    decide_query_gate,
    judge_web_passage,
)
from backend.research_workflow.agent.query_precheck import precheck_research_query
from backend.research_workflow.contracts import (
    BriefingRequest,
    DocumentEvidence,
    DraftResearchBriefing,
    EvidenceRecord,
    FinancialEvidence,
    Finding,
    GroundingFailure,
    QueryClassification,
    ResearchBriefing,
    ResearchWorkflowResult,
    VerificationResult,
    WebSourceDisposition,
)
from backend.research_workflow.data.market_data import (
    get_close_data,
    get_company_snapshot,
)
from backend.research_workflow.service.run_record import (
    ResearchRunRecorder,
    StepCallback,
    saved_steps,
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
        "query_gate_version": QUERY_GATE_VERSION,
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
    as_of: datetime,
    company_snapshot: dict[str, object],
    close_data: list[dict[str, str | float]],
) -> tuple[
    dict[str, object],
    dict[str, EvidenceRecord],
    dict[str, object],
]:
    close_reference = f"close_data:{symbol}"
    # Daily close prices have no intraday timestamp. Exclude the cutoff day.
    close_data = [
        row for row in close_data if str(row.get("Date", "")) < as_of.date().isoformat()
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
    candidates: list[FinancialEvidence] = selected_close_candidates
    snapshot_for_agent = {
        key: value
        for key, value in company_snapshot.items()
        if key in {"symbol", "company_name", "sector", "industry"}
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


def _create_research_attempt(
    session: Session,
    request: BriefingRequest,
    fingerprint: str,
    *,
    resumed_from: ResearchRun | None = None,
) -> ResearchRun:
    shared = llm_runs.create_run(
        session,
        "research_workflow",
        logfire_trace_id=current_trace_id(),
    )
    research_run = ResearchRun(
        id=shared.id,
        resumed_from_run_id=resumed_from.id if resumed_from else None,
        request_fingerprint=fingerprint,
        symbol=request.symbol.strip().upper(),
        as_of=request.as_of,
        status=ResearchRunStatus.PENDING,
        request_payload=request.model_dump(mode="json"),
        model_name=model_name,
        prompt_version=prompt_version,
        tool_version=tool_version,
        schema_version=schema_version,
        trace_id=current_trace_id(),
        checkpoint_stage=(resumed_from.checkpoint_stage if resumed_from else None),
        checkpoint_payload=(resumed_from.checkpoint_payload if resumed_from else None),
        usage_payload=(resumed_from.usage_payload if resumed_from else {}),
    )
    session.add(research_run)
    session.flush()
    return research_run


def _stale(run: ResearchRun, now: datetime) -> bool:
    from datetime import timedelta

    reference = run.started_at or run.created_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return now - reference > timedelta(minutes=5)


async def run_research_workflow(
    request: BriefingRequest,
    *,
    on_step: StepCallback | None = None,
) -> ResearchWorkflowResult:
    run_id: uuid.UUID | None = None
    recorder: ResearchRunRecorder | None = None
    usage_events: list[dict[str, object]] = []

    def record_usage(component: str, usage: dict[str, object]) -> None:
        entry = {"component": component, "usage": to_jsonable_python(usage)}
        usage_events.append(entry)
        if recorder is not None:
            stage = (
                "classifier"
                if component in {"query_jev", "query_classifier"}
                else "agent"
            )
            recorder.emit(stage, "completed", f"{component} usage recorded", entry)
        if run_id is not None:
            with db_utils.get_session() as usage_session:
                usage_run = usage_session.get(ResearchRun, run_id)
                if usage_run is not None:
                    usage_run.usage_payload = {"calls": list(usage_events)}

    draft: DraftResearchBriefing | None = None
    catalog: dict[str, EvidenceRecord] | None = None
    financial_sources: dict[str, object] | None = None
    resuming_from_checkpoint = False
    review_results: list[dict[str, object]] = []
    try:
        fingerprint = create_fingerprint(request)
        async with RESEARCH_SEMAPHORE, asyncio.timeout(180):
            with db_utils.get_session() as session:
                now = datetime.now(timezone.utc)
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
                    .order_by(ResearchRun.created_at.desc())
                    .first()
                )
                if (
                    cached_run
                    and cached_run.status
                    in (
                        ResearchRunStatus.PENDING,
                        ResearchRunStatus.RUNNING,
                    )
                    and _stale(cached_run, now)
                ):
                    cached_run.status = ResearchRunStatus.FAILED
                    cached_run.completed_at = now
                    cached_run.error_payload = {
                        "type": "StaleRun",
                        "message": "Run stopped updating before reaching a terminal state.",
                    }
                    llm_runs.fail_run(session, cached_run.id)
                    session.flush()
                    cached_run = None
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
                    draft, catalog, financial_sources = _checkpoint_state(
                        checkpointed_run.checkpoint_payload
                    )
                    prior_calls = (checkpointed_run.usage_payload or {}).get("calls")
                    if isinstance(prior_calls, list):
                        usage_events.extend(prior_calls)
                    elif checkpointed_run.usage_payload:
                        usage_events.append(
                            {
                                "component": "research_agent",
                                "usage": checkpointed_run.usage_payload,
                            }
                        )
                    new_run = _create_research_attempt(
                        session, request, fingerprint, resumed_from=checkpointed_run
                    )
                    run_id = new_run.id
                    resuming_from_checkpoint = True

            if resuming_from_checkpoint and run_id is not None:
                recorder = ResearchRunRecorder(run_id, on_step=on_step)
                recorder.emit(
                    "run",
                    "completed",
                    "Resumed from a saved agent checkpoint",
                    {
                        "resumed_from_run_id": str(checkpointed_run.id),
                        "checkpoint_stage": AGENT_COMPLETED_CHECKPOINT,
                    },
                )
                recorder.emit(
                    "scope",
                    "completed",
                    "Reusing frozen checkpoint evidence",
                    {
                        "symbol": request.symbol.strip().upper(),
                        "as_of": request.as_of.isoformat(),
                        "evidence_count": len(catalog or {}),
                        "new_source_calls": False,
                    },
                )
                with db_utils.get_session() as session:
                    resumed = session.get(ResearchRun, run_id)
                    if resumed is None:
                        raise RuntimeError("Resumed research run disappeared")
                    llm_runs.start_run(
                        session, run_id, logfire_trace_id=current_trace_id()
                    )
                    resumed.status = ResearchRunStatus.RUNNING
                    resumed.started_at = datetime.now(timezone.utc)

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
                    research_run = _create_research_attempt(
                        session, request, fingerprint
                    )
                    run_id = research_run.id

                logger.info(
                    "research_run_created run_id=%s symbol=%s status=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    ResearchRunStatus.PENDING.value,
                )
                if run_id is None:
                    raise RuntimeError("Research run ID was not generated")
                recorder = ResearchRunRecorder(run_id, on_step=on_step)
                recorder.emit(
                    "run",
                    "completed",
                    "Research run created",
                    {
                        "request": request.model_dump(mode="json"),
                        "fingerprint": fingerprint,
                    },
                )
                recorder.emit(
                    "scope",
                    "completed",
                    "Research evidence scope set",
                    {
                        "symbol": request.symbol.strip().upper(),
                        "as_of": request.as_of.isoformat(),
                        "available_tools": [
                            "search_documents",
                            "historical_financials",
                            "search_web",
                            "inspect_web_results",
                        ],
                    },
                )
                try:
                    precheck = precheck_research_query(request, now=now)
                except ValueError as exc:
                    recorder.emit(
                        "classifier",
                        "failed",
                        "Deterministic query precheck rejected request",
                        {"reason": str(exc)},
                    )
                    raise
                recorder.emit(
                    "classifier",
                    "completed",
                    "Deterministic query precheck passed",
                    precheck.model_dump(mode="json"),
                )

                recorder.emit(
                    "classifier",
                    "running",
                    "Classifying research request",
                    {"symbol": request.symbol, "question": request.research_question},
                )
                recorder.emit(
                    "classifier",
                    "running",
                    "Jev relevance and instruction judgments requested",
                    {
                        "model": JEV_MODEL,
                        "query_gate_version": QUERY_GATE_VERSION,
                        "accept_probability": ACCEPT_PROBABILITY,
                        "reject_probability": REJECT_PROBABILITY,
                        "state": {
                            "symbol": request.symbol.strip().upper(),
                            "research_question": request.research_question,
                        },
                    },
                )
                fallback_reason: str | None = None
                query_classification: QueryClassification | None = None
                try:
                    judgment = await classify_research_query(
                        precheck.symbol,
                        precheck.normalized_question,
                        precheck=precheck,
                    )
                    decision = decide_query_gate(judgment)
                    record_usage("query_jev", judgment.usage)
                    recorder.emit(
                        "classifier",
                        "completed",
                        "Jev query judgment and application gate recorded",
                        decision.model_dump(mode="json"),
                    )
                    if decision.outcome == "fallback":
                        fallback_reason = "uncertain_jev_judgment"
                    else:
                        query_classification = QueryClassification(
                            is_relevant=decision.outcome == "accept",
                            reasoning=decision.reason,
                        )
                except Exception as exc:  # noqa: BLE001 - route Jev failures to the bounded fallback
                    fallback_reason = "jev_unavailable"
                    recorder.emit(
                        "classifier",
                        "failed",
                        "Jev query judgment unavailable",
                        {"error_type": type(exc).__name__},
                    )

                if fallback_reason is not None:
                    recorder.emit(
                        "classifier",
                        "running",
                        "Existing query classifier handling fallback",
                        {"fallback_reason": fallback_reason},
                    )
                    query_classification = await run_query_classifier(
                        request.symbol,
                        precheck.normalized_question,
                        run_id,
                        on_usage=record_usage,
                    )
                if query_classification is None:
                    raise RuntimeError("Research query gate returned no decision")
                recorder.emit(
                    "classifier",
                    "completed",
                    "Research request classified",
                    {
                        **query_classification.model_dump(mode="json"),
                        "decided_by": "fallback_classifier"
                        if fallback_reason
                        else "jev_gate",
                        "fallback_reason": fallback_reason,
                    },
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

                recorder.emit(
                    "prefetch",
                    "running",
                    "Fetching company identity and close prices",
                    {"symbol": request.symbol, "as_of": request.as_of.isoformat()},
                )
                company_snapshot, close_data = await asyncio.gather(
                    asyncio.to_thread(get_company_snapshot, request.symbol),
                    asyncio.to_thread(get_close_data, request.symbol),
                )
                prefetched_context, catalog, financial_sources = (
                    _prefetched_financial_context(
                        request.symbol.strip().upper(),
                        request.as_of,
                        company_snapshot,
                        close_data,
                    )
                )
                recorder.emit(
                    "prefetch",
                    "completed",
                    "Prefetched model context",
                    {"model_visible_context": prefetched_context},
                )

                with db_utils.get_session() as session:
                    research_run = session.get(ResearchRun, run_id)
                    if research_run is None:
                        raise ValueError(f"Research run {run_id} not found")
                    research_run.status = ResearchRunStatus.RUNNING
                    research_run.started_at = datetime.now(timezone.utc)
                    llm_runs.start_run(
                        session, run_id, logfire_trace_id=current_trace_id()
                    )

                logger.info(
                    "research_run_started run_id=%s symbol=%s status=%s",
                    run_id,
                    request.symbol.strip().upper(),
                    ResearchRunStatus.RUNNING.value,
                )
                recorder.emit(
                    "agent",
                    "running",
                    "Research agent started",
                    {
                        "model": model_name,
                        "prompt_version": prompt_version,
                        "tool_version": tool_version,
                    },
                )
                execution = await run_research_briefing_agent(
                    run_id=run_id,
                    request=request,
                    prefetched_context=prefetched_context,
                    evidence_catalog=catalog,
                    financial_sources=financial_sources,
                    on_event=recorder.emit,
                )
                result = execution.result
                draft = result.output
                record_usage("research_agent", asdict(result.usage))
                recorder.emit(
                    "agent",
                    "completed",
                    "Research agent returned draft",
                    {
                        "draft": draft.model_dump(mode="json"),
                        "usage": to_jsonable_python(asdict(result.usage)),
                    },
                )
                if not draft.key_findings:
                    raise RuntimeError("Research agent returned no key findings")

                catalog = execution.evidence_catalog
                financial_sources = execution.financial_sources

                cited_draft_ids = {
                    evidence_id
                    for finding in draft.key_findings
                    for evidence_id in finding.evidence_ids
                }
                web_candidates = [
                    item
                    for item in catalog.values()
                    if isinstance(item, DocumentEvidence)
                    and item.reference_id.startswith("tavily:")
                    and item.evidence_id not in cited_draft_ids
                ]
                suggestion_attempted = False
                for passage in web_candidates[:3]:
                    try:
                        judgment = await judge_web_passage(
                            request.research_question,
                            [item.statement for item in draft.key_findings],
                            passage,
                        )
                        record_usage("web_jev", judgment.usage)
                        review = judgment.model_dump(mode="json")
                        review["reason"] = "No distinct relevant fact found."
                        if (
                            judgment.relevance_probability >= 0.8
                            and judgment.novelty_probability >= 0.8
                            and not suggestion_attempted
                        ):
                            suggestion_attempted = True
                            suggestion = await suggest_web_finding(
                                request.research_question,
                                draft.key_findings,
                                passage,
                                run_id,
                                on_usage=record_usage,
                            )
                            proposed = suggestion.finding
                            if proposed and proposed.evidence_ids == [
                                passage.evidence_id
                            ]:
                                draft.key_findings.append(proposed)
                                review["reason"] = (
                                    "Distinct finding proposed; pending evidence checks."
                                )
                            else:
                                review["reason"] = suggestion.reason
                        review_results.append(review)
                    except Exception as exc:  # noqa: BLE001 - web review is noncritical
                        review_results.append(
                            {
                                "evidence_id": passage.evidence_id,
                                "reason": f"Web review unavailable: {type(exc).__name__}",
                            }
                        )
                recorder.emit(
                    "verification",
                    "completed",
                    "Inspected web passages reviewed for coverage",
                    {
                        "decisions": review_results,
                        "reviewed_count": len(review_results),
                        "unreviewed_count": max(0, len(web_candidates) - 3),
                        "repair_attempted": suggestion_attempted,
                    },
                )

                with db_utils.get_session() as session:
                    research_run = session.get(ResearchRun, run_id)
                    if research_run is None:
                        raise RuntimeError(f"Research run {run_id} not found")
                    research_run.usage_payload = {"calls": list(usage_events)}
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
                recorder.emit(
                    "checkpoint",
                    "completed",
                    "Agent checkpoint saved",
                    {
                        "stage": AGENT_COMPLETED_CHECKPOINT,
                        "evidence_count": len(catalog),
                    },
                )

            if (
                run_id is None
                or draft is None
                or catalog is None
                or financial_sources is None
                or recorder is None
            ):
                raise RuntimeError("Research workflow state is incomplete")

            if resuming_from_checkpoint:
                review_results = [
                    item
                    for step in saved_steps(checkpointed_run.id)
                    if step.summary == "Inspected web passages reviewed for coverage"
                    for item in step.details.get("decisions", [])
                    if isinstance(item, dict)
                ]

            recorder.emit(
                "verification",
                "running",
                "Resolving cited evidence",
                {
                    "draft_findings": len(draft.key_findings),
                    "catalog_size": len(catalog),
                },
            )
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
                            is_valid = validate_document_evidence(
                                session,
                                evidence,
                                symbol=request.symbol,
                                as_of=request.as_of,
                            )
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

            recorder.emit(
                "verification",
                "completed",
                "Deterministic evidence provenance checked",
                {
                    "invalid_evidence_references": verification.invalid_evidence_references,
                    "grounding_failures": [
                        failure.model_dump(mode="json")
                        for failure in verification.grounding_failures
                    ],
                    "eligible_finding_indexes": [item[0] for item in grounding_inputs],
                },
            )
            verified_findings: list[Finding] = []
            for index, finding, valid_evidence, precheck_failure in grounding_inputs:
                failure_reason = precheck_failure
                if failure_reason is None:
                    try:
                        recorder.emit(
                            "verification",
                            "running",
                            "Checking finding grounding",
                            {
                                "finding_index": index,
                                "statement": finding.statement,
                                "evidence_ids": [
                                    item.evidence_id for item in valid_evidence
                                ],
                                "model_visible_evidence": [
                                    item.model_dump(mode="json")
                                    for item in valid_evidence
                                ],
                            },
                        )
                        grounding = await verify_finding(
                            finding,
                            valid_evidence,
                            run_id,
                            index,
                            on_usage=record_usage,
                        )
                        recorder.emit(
                            "verification",
                            "completed",
                            "Grounding judgment recorded",
                            {
                                "finding_index": index,
                                "is_supported": grounding.is_supported,
                                "reason": grounding.reasoning,
                            },
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
                    recorder.emit(
                        "verification",
                        "running",
                        "Repairing rejected finding",
                        {
                            "finding_index": index,
                            "failure_reason": failure_reason,
                            "finding": finding.model_dump(mode="json"),
                            "model_visible_evidence": [
                                item.model_dump(mode="json") for item in valid_evidence
                            ],
                            "accepted_findings": [
                                item.model_dump(mode="json")
                                for item in verified_findings
                            ],
                        },
                    )
                    revision = await revise_finding(
                        finding,
                        valid_evidence,
                        verified_findings,
                        failure_reason,
                        run_id,
                        index,
                        on_usage=record_usage,
                    )
                    recorder.emit(
                        "verification",
                        "completed",
                        "Finding repair decision recorded",
                        {
                            "finding_index": index,
                            "revision": revision.model_dump(mode="json"),
                        },
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
                        on_usage=record_usage,
                    )
                    recorder.emit(
                        "verification",
                        "completed",
                        "Revised finding checked",
                        {
                            "finding_index": index,
                            "is_supported": revised_grounding.is_supported,
                            "reason": revised_grounding.reasoning,
                        },
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
            cited_final_ids = {
                evidence.evidence_id
                for finding in verified_findings
                for evidence in finding.evidence
            }
            review_by_id = {
                str(item.get("evidence_id")): item for item in review_results
            }
            web_dispositions = []
            for item in catalog.values():
                if not isinstance(
                    item, DocumentEvidence
                ) or not item.reference_id.startswith("tavily:"):
                    continue
                review = review_by_id.get(item.evidence_id, {})
                cited = item.evidence_id in cited_final_ids
                web_dispositions.append(
                    WebSourceDisposition(
                        evidence_id=item.evidence_id,
                        title=item.title,
                        url=item.url,
                        outcome=(
                            "cited"
                            if cited
                            else "review_failed"
                            if str(review.get("reason", "")).startswith(
                                "Web review unavailable:"
                            )
                            else "excluded"
                        ),
                        reason=(
                            "Cited by a verified final finding."
                            if cited
                            else (
                                "Proposed web finding did not pass final evidence checks."
                                if review.get("reason")
                                == "Distinct finding proposed; pending evidence checks."
                                else str(
                                    review.get("reason")
                                    or "Not selected within bounded web review."
                                )
                            )
                        ),
                        relevance_probability=review.get("relevance_probability"),
                        novelty_probability=review.get("novelty_probability"),
                    ).model_dump(mode="json")
                )
            recorder.emit(
                "verification",
                "completed",
                "Final web source dispositions recorded",
                {"decisions": web_dispositions},
            )
            all_evidence = list(
                {
                    evidence.evidence_id: evidence
                    for finding in verified_findings
                    for evidence in finding.evidence
                }.values()
            )
            try:
                recorder.emit(
                    "verification",
                    "running",
                    "Synthesizing checked findings",
                    {
                        "accepted_findings": [
                            finding.model_dump(mode="json")
                            for finding in verified_findings
                        ]
                    },
                )
                narrative = await synthesize_narrative(
                    verified_findings,
                    run_id,
                    on_usage=record_usage,
                )
                recorder.emit(
                    "verification",
                    "completed",
                    "Narrative draft recorded",
                    narrative.model_dump(mode="json"),
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
                    on_usage=record_usage,
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
                    on_usage=record_usage,
                )
                recorder.emit(
                    "verification",
                    "completed",
                    "Narrative grounding checked",
                    {
                        "summary_supported": summary_check.is_supported,
                        "summary_reason": summary_check.reasoning,
                        "outlook_supported": outlook_check.is_supported,
                        "outlook_reason": outlook_check.reasoning,
                    },
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
                        *[
                            note
                            for note in briefing.limitations
                            if not (
                                any(
                                    term in note.lower()
                                    for term in (
                                        "reporting",
                                        "web",
                                        "news",
                                        "article",
                                        "tavily",
                                    )
                                )
                                and any(
                                    term in note.lower()
                                    for term in (
                                        "relies",
                                        "based on",
                                        "supported by",
                                        "draws on",
                                    )
                                )
                            )
                        ],
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
                llm_runs.complete_run(session, run_id)

            recorder.emit(
                "persistence",
                "completed",
                "Verified briefing saved",
                {
                    "status": "completed",
                    "stop_reason": "verified_briefing",
                    "approval_ready": verification.approval_ready,
                    "accepted_findings": len(verified_findings),
                },
            )

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
            marked_failed = False
            with db_utils.get_session() as session:
                research_run = session.get(ResearchRun, run_id)
                if research_run and research_run.status != ResearchRunStatus.COMPLETED:
                    research_run.status = ResearchRunStatus.FAILED
                    research_run.error_payload = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    research_run.completed_at = datetime.now(timezone.utc)
                    llm_runs.fail_run(
                        session, run_id, logfire_trace_id=current_trace_id()
                    )
                    marked_failed = True
            logger.error(
                "research_run_failed run_id=%s symbol=%s error_type=%s",
                run_id,
                request.symbol.strip().upper(),
                type(exc).__name__,
            )
            if recorder is not None and marked_failed:
                recorder.emit(
                    "persistence",
                    "failed",
                    "Research run failed",
                    {"stop_reason": type(exc).__name__, "error": str(exc)},
                )
        raise


def validate_document_evidence(
    session: Session,
    evidence: DocumentEvidence,
    *,
    symbol: str,
    as_of: datetime,
) -> bool:
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
        or document.title != evidence.title
        or document.source_url != evidence.url
        or chunk.chunk_index != evidence.chunk_index
        or (document.filter_metadata or {}).get("symbol") != symbol.strip().upper()
        or document.published_at is None
        or document.published_at > as_of
        or document.published_at != evidence.published_at
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
