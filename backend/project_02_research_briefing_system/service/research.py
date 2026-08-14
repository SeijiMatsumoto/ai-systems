import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from pydantic_ai import UsageLimits

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
    ResearchBriefing,
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


async def run_research_workflow(request: BriefingRequest) -> ResearchBriefing:
    # 1. Normalize request and calculate fingerprint
    try:
        fingerprint = create_fingerprint(request)
        with db_utils.get_session() as session:
            cached_run = (
                session.query(ResearchRun)
                .filter(
                    ResearchRun.request_fingerprint == fingerprint,
                    ResearchRun.status == ResearchRunStatus.COMPLETED,
                )
                .order_by(ResearchRun.completed_at.desc())
                .first()
            )

            # 2. Return a valid cached result when available
            if cached_run:
                return cached_run

        # 3. Create ResearchRun and insert initial
        now = datetime.now().astimezone()

        with db_utils.get_session() as session:
            research_run = schemas.ResearchRun(
                request_fingerprint=fingerprint,
                symbol=request.symbol,
                as_of=request.as_of,
                status="pending",
                request_payload=json.dumps(request.model_dump(mode="json")),
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
        # - Make sure symbol is at least 4 chars
        # - Make sure as_of is before today
        # - Make sure request.research_question is at least N characters and is appropriate (check for prompt injection)
        if len(request.symbol) < 4:
            raise ValueError(f"{request.symbol} does not meet length requirements!")

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
            as_of=datetime.now().astimezone(),
            research_question=request.research_question,
            audience=request.audience,
            time_horizon=request.time_horizon,
        )
        request = {
            **briefing_request.model_dump(mode="json"),
            "prefetched_context": {
                "company_snapshot": company_snapshot,
                "recent_close_data": close_data,
            },
        }
        async with asyncio.timeout(120):
            result = await agent.run(
                json.dumps(request, default=str),
                usage_limits=UsageLimits(
                    request_limit=12,
                    tool_calls_limit=10,
                ),
            )

            print(result.output)

        # 7. Validate citations and grounding
        briefing = result.output
        verification = VerificationResult(approval_ready=True)
        with db_utils.get_session() as session:
            for index, finding in enumerate(briefing.key_findings):
                valid_evidence = []

                for evidence in finding.evidence:
                    if validate_document_evidence(session, evidence):
                        valid_evidence.append(evidence)
                    else:
                        verification.invalid_evidence_references.append(
                            evidence.reference_id
                        )

                if not valid_evidence:
                    verification.unsupported_finding_indexes.append(index)
                    continue

                grounding = await verify_finding(finding, valid_evidence)

                if not grounding.is_supported:
                    verification.unsupported_finding_indexes.append(index)

        # 8. Save output, verification, and usage
        # 9. Mark run completed or failed
        # 10. Return briefing

    except Exception as exc:
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

    chunk = session.get(
        schemas.DocumentChunk,
        uuid.UUID(evidence.chunk_id),
    )
    if chunk is None:
        return False

    document = chunk.document

    if document.reference_id != evidence.reference_id:
        return False

    quote = normalize_text(evidence.content)
    source = normalize_text(chunk.content)

    return quote in source
