"""Saved knowledge answer and proposal flow with ACL and verification boundaries."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.db import db_utils
from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.db.schemas import KnowledgeAnswerOutput
from backend.internal_knowledge_action.action_intent import (
    ACTION_THRESHOLD,
    ActionIntentProvider,
    LiveJevActionIntentProvider,
    detect_action_signals,
)
from backend.internal_knowledge_action.action_model import (
    ActionProposalProvider,
    LiveActionProposalProvider,
)
from backend.internal_knowledge_action.answer_model import (
    ANSWER_INSTRUCTIONS,
    AnswerProvider,
    LiveAnswerProvider,
)
from backend.internal_knowledge_action.contracts import (
    AnswerClaimDraft,
    ClaimVerification,
    GroundingJudgment,
    IndexSnapshot,
    KnowledgeAnswerRequest,
    KnowledgeAnswerResult,
    KnowledgeStep,
    KnowledgeTaskProposal,
    RetrievalFixture,
    RetrievalPreviewRequest,
    SelectedEvidence,
)
from backend.internal_knowledge_action.embedding import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from backend.internal_knowledge_action.grounding import (
    ACCEPT_PROBABILITY,
    GroundingProvider,
    LiveJevGroundingProvider,
)
from backend.internal_knowledge_action.ingestion import (
    index_matches_fixture,
    load_fixture,
    load_index,
)
from backend.internal_knowledge_action.retrieval import (
    normalize_question,
    preview_retrieval,
)

SessionScope = Callable[[], AbstractContextManager[Session]]
StepCallback = Callable[[KnowledgeStep], None]


def _embedder_for(index: IndexSnapshot) -> EmbeddingProvider:
    if index.embedding_model == MockEmbeddingProvider.model_id:
        return MockEmbeddingProvider()
    if index.embedding_model == OpenAIEmbeddingProvider.model_id:
        return OpenAIEmbeddingProvider()
    raise ValueError("Unsupported indexed embedding model")


def _verify_claim(
    claim: AnswerClaimDraft,
    catalog: dict[str, SelectedEvidence],
    fixture: RetrievalFixture,
    index: IndexSnapshot,
    authorized_ids: set[str],
) -> str | None:
    sources = {source.source_id: source for source in fixture.sources}
    indexed = {chunk.chunk_id: chunk for chunk in index.chunks}
    if len(claim.evidence_ids) != len(set(claim.evidence_ids)):
        return "duplicate_evidence_id"
    for evidence_id in claim.evidence_ids:
        item = catalog.get(evidence_id)
        if item is None:
            return "unknown_or_unsurfaced_evidence_id"
        locator = item.locator
        if locator.source_id not in authorized_ids:
            return "unauthorized_evidence"
        source = sources.get(locator.source_id)
        chunk = indexed.get(item.chunk_id)
        if (
            source is None
            or chunk is None
            or source.revision != locator.revision
            or chunk.source_id != locator.source_id
            or not (locator.start <= chunk.start < chunk.end <= locator.end)
            or source.body[chunk.start : chunk.end] != chunk.text
            or source.body[locator.start : locator.end] != item.excerpt
        ):
            return "stale_or_invalid_locator"
    return None


def populate_available_actions(
    result: KnowledgeAnswerResult, fixture: RetrievalFixture
) -> None:
    """Expose a follow-up only when the verified answer cites an in-scope ticket."""
    result.available_actions = []
    result.action_evidence_ids = []
    if result.stop_reason != "answered":
        return
    persona = next(
        (
            item
            for item in fixture.personas
            if item.persona_id == result.request.persona_id
        ),
        None,
    )
    if persona is None or "support" not in persona.groups:
        return
    sources = {item.source_id: item for item in fixture.sources}
    cited_ids = {
        evidence_id for claim in result.claims for evidence_id in claim.evidence_ids
    }
    ticket_evidence_ids = [
        item.evidence_id
        for item in result.evidence
        if item.evidence_id in cited_ids
        and item.locator.source_id in result.authorized_source_ids
        and sources.get(item.locator.source_id)
        and sources[item.locator.source_id].kind == "ticket"
    ]
    if ticket_evidence_ids:
        result.available_actions = ["support_follow_up"]
        result.action_evidence_ids = ticket_evidence_ids


async def run_answer(
    request: KnowledgeAnswerRequest,
    *,
    fixture: RetrievalFixture | None = None,
    index: IndexSnapshot | None = None,
    embedder: EmbeddingProvider | None = None,
    answerer: AnswerProvider | None = None,
    grounder: GroundingProvider | None = None,
    session_scope: SessionScope = db_utils.get_session,
    on_step: StepCallback | None = None,
    action_classifier: ActionIntentProvider | None = None,
    action_proposer: ActionProposalProvider | None = None,
) -> KnowledgeAnswerResult:
    steps: list[KnowledgeStep] = []
    run_id: UUID
    with session_scope() as session:
        run_id = create_run(
            session, "internal_knowledge_action", run_id=request.run_id
        ).id
    with session_scope() as session:
        start_run(session, run_id)

    def emit(stage: str, status: str, summary: str, details: dict[str, Any]) -> None:
        step = KnowledgeStep.model_validate(
            {
                "sequence": len(steps) + 1,
                "stage": stage,
                "status": status,
                "summary": summary,
                "details": details,
            }
        )
        steps.append(step)
        if on_step:
            on_step(step)

    result = KnowledgeAnswerResult(
        run_id=run_id,
        status="failed",
        stop_reason="retrieval_error",
        request=request,
        steps=steps,
    )
    stage = "retrieval"
    try:
        question = normalize_question(request.question)
        signals = detect_action_signals(question)
        emit(
            "request_check",
            "completed",
            "Validated request before any model call",
            {"question": question, "length": len(question), "max_length": 500},
        )
        action_request = False
        if signals:
            emit(
                "action_intent_signals",
                "completed",
                "Deterministic action keywords found",
                {"signals": signals},
            )
            stage = "action_intent"
            action_classifier = action_classifier or LiveJevActionIntentProvider()
            emit(
                "action_intent_classification",
                "running",
                "Jev classifies whether this is an explicit action request",
                {
                    "model": action_classifier.model_id,
                    "request": question,
                    "request_limit": 1,
                },
            )
            judgment = await action_classifier.classify(question, signals)
            result.usage["jev_action_intent"] = judgment.usage
            action_request = judgment.probability >= ACTION_THRESHOLD
            emit(
                "action_intent_classification",
                "completed",
                "Applied application threshold to Jev decision",
                {
                    "judgment": judgment.model_dump(mode="json"),
                    "threshold": ACTION_THRESHOLD,
                    "explicit_action": action_request,
                },
            )
        else:
            emit(
                "action_intent_signals",
                "completed",
                "No action keywords found; skipped Jev classifier",
                {"signals": []},
            )
        if action_request:
            stage = "retrieval"
            fixture = fixture or load_fixture()
            index = index or load_index()
            if index is None or not index_matches_fixture(index, fixture):
                raise ValueError("Build or refresh the fixture index first")
            embedder = embedder or _embedder_for(index)
            preview = preview_retrieval(
                RetrievalPreviewRequest(
                    persona_id=request.persona_id, question=question
                ),
                fixture,
                index,
                embedder,
            )
            persona = next(
                (
                    item
                    for item in fixture.personas
                    if item.persona_id == request.persona_id
                ),
                None,
            )
            sources = {item.source_id: item for item in fixture.sources}
            ticket_evidence = [
                SelectedEvidence(
                    evidence_id=f"K{i}",
                    chunk_id=item.chunk_id,
                    title=item.title,
                    excerpt=item.excerpt,
                    locator=item.locator,
                )
                for i, item in enumerate(preview.ranked_excerpts, 1)
                if sources.get(item.locator.source_id)
                and sources[item.locator.source_id].kind == "ticket"
            ]
            result.fixture_version = fixture.version
            result.embedding_model = index.embedding_model
            result.authorized_source_ids = preview.authorized_source_ids
            result.evidence = ticket_evidence
            emit(
                "access_filter",
                "completed",
                "Resolved requester identity and ACL scope before proposal model",
                {
                    "persona_id": request.persona_id,
                    "source_ids": preview.authorized_source_ids,
                },
            )
            emit(
                "lexical_search",
                "completed",
                "Scored only ACL-authorized keyword candidates",
                {
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in preview.lexical_candidates
                    ]
                },
            )
            emit(
                "vector_search",
                "completed",
                "Scored only ACL-authorized vector candidates",
                {
                    "embedding_model": index.embedding_model,
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in preview.vector_candidates
                    ],
                },
            )
            emit(
                "fusion_rerank",
                "completed",
                "Selected citable support-ticket excerpts for the proposal",
                {
                    "ranked_excerpts": [
                        item.model_dump(mode="json") for item in preview.ranked_excerpts
                    ],
                    "ticket_evidence_ids": [
                        item.evidence_id for item in ticket_evidence
                    ],
                },
            )
            allowed = (
                persona is not None
                and "support" in persona.groups
                and bool(ticket_evidence)
            )
            emit(
                "action_policy",
                "completed" if allowed else "failed",
                "Checked supported action, requester scope, and ticket evidence",
                {
                    "action_type": "support_follow_up",
                    "requester_allowed": bool(persona and "support" in persona.groups),
                    "ticket_evidence_ids": [
                        item.evidence_id for item in ticket_evidence
                    ],
                    "allowed": allowed,
                },
            )
            if allowed:
                stage = "action_proposal"
                action_proposer = action_proposer or LiveActionProposalProvider()
                emit(
                    "action_proposal_input",
                    "completed",
                    "Sent only ACL-authorized ticket evidence to typed proposal model",
                    {
                        "request": question,
                        "evidence": [
                            item.model_dump(mode="json") for item in ticket_evidence
                        ],
                        "model": action_proposer.model_id,
                        "request_limit": 1,
                    },
                )
                draft, usage = await action_proposer.propose(
                    question, ticket_evidence, run_id
                )
                result.usage["action_proposal"] = usage
                valid_ids = {item.evidence_id for item in ticket_evidence}
                if (
                    draft.task_type != "support_follow_up"
                    or len(draft.evidence_ids) != len(set(draft.evidence_ids))
                    or not set(draft.evidence_ids) <= valid_ids
                    or not draft.title.strip()
                    or not draft.description.strip()
                ):
                    result.stop_reason = "action_policy_blocked"
                    result.action_status = "blocked"
                    emit(
                        "action_proposal_output",
                        "failed",
                        "Proposal failed deterministic type, field, or provenance checks",
                        {"draft": draft.model_dump(mode="json")},
                    )
                else:
                    source_id = ticket_evidence[0].locator.source_id
                    result.action_proposal = KnowledgeTaskProposal(
                        **draft.model_dump(),
                        requester_persona_id=request.persona_id,
                        idempotency_key=f"knowledge-action:{run_id}",
                    )
                    result.action_status = "pending_approval"
                    result.stop_reason = "action_proposal_pending"
                    result.status = "completed"
                    emit(
                        "action_proposal_output",
                        "completed",
                        "Validated task proposal; no task has been created",
                        {
                            "proposal": result.action_proposal.model_dump(mode="json"),
                            "source_id": source_id,
                        },
                    )
            else:
                result.status = "completed"
                result.action_status = "blocked"
                result.stop_reason = "action_policy_blocked"
        else:
            stage = "retrieval"
            fixture = fixture or load_fixture()
            sources = {item.source_id: item for item in fixture.sources}
            index = index or load_index()
            if index is None or not index_matches_fixture(index, fixture):
                raise ValueError("Build or refresh the fixture index first")
            embedder = embedder or _embedder_for(index)
            preview = preview_retrieval(
                RetrievalPreviewRequest(
                    persona_id=request.persona_id, question=question
                ),
                fixture,
                index,
                embedder,
            )
            result.fixture_version = fixture.version
            result.embedding_model = index.embedding_model
            result.authorized_source_ids = preview.authorized_source_ids
            emit(
                "access_filter",
                "completed",
                "Resolved demo persona and ACL scope",
                {
                    "persona_id": request.persona_id,
                    "source_ids": preview.authorized_source_ids,
                },
            )
            emit(
                "lexical_search",
                "completed",
                "Scored authorized keyword candidates",
                {
                    "question": question,
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in preview.lexical_candidates
                    ],
                },
            )
            emit(
                "vector_search",
                "completed",
                "Scored authorized vector candidates",
                {
                    "question": question,
                    "embedding_model": index.embedding_model,
                    "candidates": [
                        item.model_dump(mode="json")
                        for item in preview.vector_candidates
                    ],
                },
            )
            evidence = [
                SelectedEvidence(
                    evidence_id=f"K{rank}",
                    chunk_id=item.chunk_id,
                    title=item.title,
                    excerpt=item.excerpt,
                    locator=item.locator,
                )
                for rank, item in enumerate(preview.ranked_excerpts, 1)
            ]
            result.evidence = evidence
            emit(
                "fusion_rerank",
                "completed",
                "Selected bounded citable context",
                {
                    "ranked_excerpts": [
                        item.model_dump(mode="json") for item in preview.ranked_excerpts
                    ],
                    "evidence_ids": [item.evidence_id for item in evidence],
                },
            )
            if not evidence:
                result.status = "completed"
                result.stop_reason = "no_relevant_passage"
            else:
                stage = "answer_model"
                answerer = answerer or LiveAnswerProvider()
                emit(
                    "model_input",
                    "completed",
                    "Sent selected passages to the answer model",
                    {
                        "question": question,
                        "evidence": [item.model_dump(mode="json") for item in evidence],
                        "model": answerer.model_id,
                        "instructions": ANSWER_INSTRUCTIONS,
                        "request_limit": 1,
                        "private_reasoning": "unavailable",
                    },
                )
                draft, usage = await answerer.answer(question, evidence, run_id)
                result.usage["answer_model"] = usage
                emit(
                    "model_output",
                    "completed",
                    "Received typed answer draft",
                    {"draft": draft.model_dump(mode="json"), "usage": usage},
                )
                if draft.abstain or not draft.claims:
                    result.status = "completed"
                    result.stop_reason = "model_abstained"
                else:
                    result.answer_format = draft.format
                    catalog = {item.evidence_id: item for item in evidence}
                    checks = []
                    for rank, claim in enumerate(draft.claims):
                        reason = _verify_claim(
                            claim,
                            catalog,
                            fixture,
                            index,
                            set(preview.authorized_source_ids),
                        )
                        checks.append(
                            ClaimVerification(
                                claim_index=rank,
                                passed=reason is None,
                                reason=reason or "exact_authorized_passage",
                            )
                        )
                    result.verification = checks
                    emit(
                        "citation_check",
                        "completed" if all(c.passed for c in checks) else "failed",
                        "Checked citation IDs, scope, revision, and exact offsets",
                        {"checks": [check.model_dump(mode="json") for check in checks]},
                    )
                    if not all(check.passed for check in checks):
                        result.status = "completed"
                        result.stop_reason = "citation_rejected"
                    else:
                        stage = "grounding"
                        grounder = grounder or LiveJevGroundingProvider()
                        for rank, claim in enumerate(draft.claims):
                            cited = [catalog[item] for item in claim.evidence_ids]
                            emit(
                                "grounding",
                                "running",
                                f"{grounder.model_id} checking claim {rank + 1}",
                                {
                                    "model": grounder.model_id,
                                    "claim": claim.model_dump(mode="json"),
                                    "evidence": [
                                        item.model_dump(mode="json") for item in cited
                                    ],
                                },
                            )
                            try:
                                judgment: GroundingJudgment = await grounder.judge(
                                    claim, cited
                                )
                            except Exception as exc:  # noqa: BLE001 - abstain on classifier failure
                                result.verification[rank] = ClaimVerification(
                                    claim_index=rank,
                                    passed=False,
                                    reason="grounding_unavailable",
                                )
                                result.error_type = type(exc).__name__
                                result.status = "completed"
                                result.stop_reason = "grounding_unavailable"
                                emit(
                                    "grounding",
                                    "failed",
                                    "Grounding provider unavailable; abstained",
                                    {"error_type": type(exc).__name__},
                                )
                                break
                            accepted = judgment.probability >= ACCEPT_PROBABILITY
                            result.verification[rank] = ClaimVerification(
                                claim_index=rank,
                                passed=accepted,
                                reason="supported"
                                if accepted
                                else "insufficient_support",
                                judgment=judgment,
                            )
                            result.usage[f"jev_claim_{rank + 1}"] = judgment.usage
                            emit(
                                "grounding",
                                "completed",
                                "Grounding support judgment recorded",
                                {
                                    "claim_index": rank,
                                    "threshold": ACCEPT_PROBABILITY,
                                    "judgment": judgment.model_dump(mode="json"),
                                    "accepted": accepted,
                                },
                            )
                            if not accepted:
                                result.status = "completed"
                                result.stop_reason = "grounding_rejected"
                                break
                        else:
                            result.claims = draft.claims
                            result.status = "completed"
                            result.stop_reason = "answered"
                            populate_available_actions(result, fixture)
                            emit(
                                "action_availability",
                                "completed",
                                "Checked for follow-up actions supported by cited, authorized ticket evidence",
                                {
                                    "available_actions": result.available_actions,
                                    "action_evidence_ids": result.action_evidence_ids,
                                    "cited_ticket_source_ids": sorted(
                                        {
                                            item.locator.source_id
                                            for item in evidence
                                            if item.evidence_id
                                            in result.action_evidence_ids
                                        }
                                    ),
                                },
                            )
    except Exception as exc:  # noqa: BLE001 - persist an inspectable failed run
        result.status = "completed" if stage == "action_intent" else "failed"
        result.stop_reason = {
            "answer_model": "answer_model_error",
            "action_intent": "action_intent_unavailable",
            "action_proposal": "action_proposal_error",
        }.get(stage, "retrieval_error")
        result.error_type = type(exc).__name__
        emit(
            "action_intent_classification"
            if stage == "action_intent"
            else "action_proposal_output"
            if stage == "action_proposal"
            else "model_output"
            if stage == "answer_model"
            else "request_check",
            "failed",
            "Run failed before a verified result could be saved",
            {"error_type": type(exc).__name__},
        )

    emit(
        "persistence",
        "completed",
        "Saved outcome and ordered walkthrough",
        {"run_id": str(run_id), "status": result.status},
    )
    emit(
        "stop",
        "completed",
        f"Stopped: {result.stop_reason}",
        {"stop_reason": result.stop_reason},
    )
    result.steps = steps
    with session_scope() as session:
        session.add(
            KnowledgeAnswerOutput(
                run_id=run_id, response_payload=result.model_dump(mode="json")
            )
        )
        if result.status == "completed":
            complete_run(session, run_id)
        else:
            fail_run(session, run_id)
    return result
