import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone

from pydantic_ai import UsageLimits
from pydantic_ai.messages import ModelMessage, ToolReturnPart

from backend.db import db_utils, schemas
from backend.db.schemas import ResearchRun, ResearchRunStatus
from backend.project_02_research_briefing_system.agent.agent import (
    agent,
    model_name,
    prompt_version,
    schema_version,
    tool_version,
)
from backend.project_02_research_briefing_system.agent.classifiers import (
    run_query_classifier,
    verify_finding,
)
from backend.project_02_research_briefing_system.agent.models import (
    BriefingRequest,
    EvidenceItem,
    GroundingFailure,
    ResearchBriefing,
    ResearchWorkflowResult,
    VerificationResult,
)
from backend.project_02_research_briefing_system.data.market_data import (
    get_close_data,
    get_company_snapshot,
)

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_fingerprint(request: BriefingRequest) -> str:
    fingerprint_input = {
        "request": {
            "symbol": request.symbol.strip().upper(),
            "as_of": (request.as_of.astimezone(timezone.utc).date().isoformat()),
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


def collect_historical_financial_sources(
    messages: Sequence[ModelMessage],
) -> dict[str, object]:
    sources: dict[str, object] = {}

    for message in messages:
        for part in message.parts:
            if not isinstance(part, ToolReturnPart):
                continue
            if part.tool_name != "historical_financials":
                continue

            payload = part.structured_content()
            if not isinstance(payload, dict):
                continue

            reference_id = payload.get("reference_id")
            if isinstance(reference_id, str):
                sources[reference_id] = payload

    return sources


async def run_research_workflow(request: BriefingRequest) -> ResearchWorkflowResult:
    # 1. Normalize request and calculate fingerprint
    run_id = None
    try:
        fingerprint = create_fingerprint(request)
        with db_utils.get_session() as session:
            existing_run = (
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

            # 2. Return a valid cached result when available
            if existing_run:
                return ResearchWorkflowResult(
                    run_id=existing_run.id,
                    status=existing_run.status,
                    briefing=(
                        ResearchBriefing.model_validate(existing_run.briefing_payload)
                        if existing_run.briefing_payload
                        else None
                    ),
                )

        # 3. Create ResearchRun and insert initial
        now = datetime.now().astimezone()

        with db_utils.get_session() as session:
            research_run = schemas.ResearchRun(
                request_fingerprint=fingerprint,
                symbol=request.symbol,
                as_of=request.as_of,
                status="pending",
                request_payload=request.model_dump(mode="json"),
                model_name=model_name,
                prompt_version=prompt_version,
                tool_version=tool_version,
                schema_version=schema_version,
                started_at=now,
            )
            session.add(research_run)
            session.flush()
            run_id = research_run.id

        # 4. Run pre-agent request guardrails
        if request.as_of > now:
            raise ValueError(f"{request.as_of} cannot be after today")

        if len(request.research_question) < 30:
            raise ValueError(
                f"{request.research_question} does not meet length requirements!"
            )

        # LLM guardrail classification here
        query_classification_result = await run_query_classifier(
            request.symbol, request.research_question
        )
        logger.info(
            "[Query Classification] %s - %s: is_relevant=%s, reason=%s",
            request.symbol,
            request.research_question,
            query_classification_result.is_relevant,
            query_classification_result.reasoning,
        )
        if not query_classification_result.is_relevant:
            raise ValueError(
                f"Query classification not relevant reasoning: {query_classification_result.reasoning}"
            )

        # 5. Prefetch company snapshot and prices
        company_snapshot, close_data = await asyncio.gather(
            asyncio.to_thread(get_company_snapshot, request.symbol),
            asyncio.to_thread(get_close_data, request.symbol),
        )

        # 5.5 Update ResearchRun to running
        with db_utils.get_session() as session:
            research_run = session.get(ResearchRun, run_id)

            if research_run is None:
                raise ValueError(f"Research run {run_id} not found")

            research_run.status = ResearchRunStatus.RUNNING
            research_run.started_at = datetime.now(timezone.utc)

        # 6. Invoke the autonomous agent
        briefing_request = BriefingRequest(
            symbol=request.symbol,
            as_of=request.as_of,
            research_question=request.research_question,
            audience=request.audience,
            time_horizon=request.time_horizon,
        )
        agent_input = {
            **briefing_request.model_dump(mode="json"),
            "prefetched_context": {
                "company_snapshot": company_snapshot,
                "recent_close_data": close_data,
            },
        }
        async with asyncio.timeout(120):
            result = await agent.run(
                json.dumps(agent_input, default=str),
                usage_limits=UsageLimits(
                    request_limit=12,
                    tool_calls_limit=10,
                ),
            )

            print(result.output)

        # 7. Validate citations and grounding
        briefing = result.output
        symbol = request.symbol.strip().upper()
        financial_sources: dict[str, object] = {
            f"company_snapshot:{symbol}": company_snapshot,
            f"close_data:{symbol}": close_data,
        }
        financial_sources.update(
            collect_historical_financial_sources(result.all_messages())
        )

        verification = VerificationResult(approval_ready=True)
        grounding_inputs = []
        with db_utils.get_session() as session:
            for index, finding in enumerate(briefing.key_findings):
                valid_evidence = []
                for evidence in finding.evidence:
                    if evidence.evidence_type == "document":
                        is_valid = validate_document_evidence(session, evidence)
                    else:
                        is_valid = validate_financial_evidence(
                            evidence, financial_sources
                        )
                    if is_valid:
                        valid_evidence.append(evidence)
                    else:
                        verification.invalid_evidence_references.append(
                            evidence.reference_id
                        )

                if not valid_evidence:
                    verification.unsupported_finding_indexes.append(index)
                    continue

                grounding_inputs.append((index, finding, valid_evidence))

        for index, finding, valid_evidence in grounding_inputs:
            grounding = await verify_finding(finding, valid_evidence)

            if not grounding.is_supported:
                verification.unsupported_finding_indexes.append(index)
                verification.grounding_failures.append(
                    GroundingFailure(finding_index=index, reason=grounding.reasoning)
                )

        verification.approval_ready = not any(
            [
                verification.unsupported_finding_indexes,
                verification.invalid_evidence_references,
            ]
        )
        # 8. Save output, verification, and usage
        with db_utils.get_session() as session:
            research_run = session.get(ResearchRun, run_id)

            if research_run is None:
                raise RuntimeError(f"Research run {run_id} not found")

            research_run.briefing_payload = briefing.model_dump(mode="json")
            research_run.verification_payload = verification.model_dump(mode="json")
            research_run.usage_payload = asdict(result.usage)
            research_run.status = ResearchRunStatus.COMPLETED
            research_run.completed_at = datetime.now(timezone.utc)

        # 9. Return briefing
        return ResearchWorkflowResult(
            run_id=research_run.id,
            status=research_run.status,
            briefing=(ResearchBriefing.model_validate(briefing) if briefing else None),
        )

    except Exception as exc:
        if run_id is not None:
            with db_utils.get_session() as session:
                research_run = session.get(ResearchRun, run_id)
                if research_run:
                    research_run.status = ResearchRunStatus.FAILED
                    research_run.error_payload = {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                    research_run.completed_at = datetime.now(timezone.utc)
        raise


def normalize_text(value: str) -> str:
    return " ".join(value.split())


def validate_document_evidence(
    session,
    evidence: EvidenceItem,
) -> bool:
    if evidence.chunk_id is None:
        return False

    try:
        chunk_id = uuid.UUID(evidence.chunk_id)
    except ValueError:
        return False

    chunk = session.get(
        schemas.DocumentChunk,
        chunk_id,
    )
    if chunk is None:
        return False

    document = chunk.document

    if document.reference_id != evidence.reference_id:
        return False

    if not isinstance(evidence.content, str):
        return False

    quote = normalize_text(evidence.content)
    source = normalize_text(chunk.content)

    return quote in source


def validate_financial_evidence(
    evidence: EvidenceItem, financial_sources: dict[str, object]
):
    source_data = financial_sources.get(evidence.reference_id)

    if source_data is None or evidence.field_path is None:
        return False

    try:
        actual_value = resolve_field_path(
            source_data,
            evidence.field_path,
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False

    return actual_value == evidence.content


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
