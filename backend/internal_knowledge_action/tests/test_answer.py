"""Offline answer-path checks; no live embedding, answer, or Jev request."""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic_ai.usage import RunUsage
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.db.schemas import KnowledgeAnswerOutput, KnowledgeMockTask, LlmRun
from backend.internal_knowledge_action.action_approval import decide_action
from backend.internal_knowledge_action.action_intent import LiveJevActionIntentProvider
from backend.internal_knowledge_action.action_model import LiveActionProposalProvider
from backend.internal_knowledge_action.answer_model import LiveAnswerProvider
from backend.internal_knowledge_action.answer_service import _verify_claim, run_answer
from backend.internal_knowledge_action.contracts import (
    ActionDecisionRequest,
    AnswerClaimDraft,
    AnswerDraft,
    GroundingJudgment,
    KnowledgeAnswerRequest,
    TaskProposalDraft,
)
from backend.internal_knowledge_action.embedding import MockEmbeddingProvider
from backend.internal_knowledge_action.grounding import LiveJevGroundingProvider
from backend.internal_knowledge_action.ingestion import ingest_fixture, load_fixture
from backend.main import app


class FakeAnswerer:
    model_id = "fake-answer"

    def __init__(self, draft: AnswerDraft | None = None, *, error: bool = False):
        self.draft = draft or AnswerDraft(
            abstain=False,
            format="numbered_list",
            claims=[
                AnswerClaimDraft(
                    statement="The manager approves time off.", evidence_ids=["K3"]
                )
            ],
        )
        self.error = error
        self.calls = []

    async def answer(self, question, evidence, run_id):
        self.calls.append((question, evidence, run_id))
        if self.error:
            raise RuntimeError("fake provider failed")
        return self.draft, {"requests": 1, "input_tokens": 42, "output_tokens": 11}


class FakeGrounder:
    model_id = "fake-jev"

    def __init__(self, probability: float = 0.95, *, error: bool = False):
        self.probability = probability
        self.error = error
        self.calls = []

    async def judge(self, claim, evidence):
        self.calls.append((claim, evidence))
        if self.error:
            raise RuntimeError("fake Jev failed")
        return GroundingJudgment(
            model="fake-jev",
            question_version=1,
            probability=self.probability,
            usage={"input_tokens": 20},
        )


class FakeActionClassifier:
    model_id = "fake-jev-intent"

    def __init__(self, probability=0.95, error=False):
        self.probability = probability
        self.error = error
        self.calls = []

    async def classify(self, question, signals):
        self.calls.append((question, signals))
        if self.error:
            raise RuntimeError("fake intent provider failed")
        from backend.internal_knowledge_action.contracts import ActionIntentJudgment

        return ActionIntentJudgment(
            model=self.model_id, probability=self.probability, usage={"requests": 1}
        )


class FakeActionProposer:
    model_id = "fake-proposal"

    def __init__(self, error=False):
        self.error = error
        self.calls = []

    async def propose(self, question, evidence, run_id):
        self.calls.append((question, evidence, run_id))
        if self.error:
            raise RuntimeError("fake proposal failed")
        return TaskProposalDraft(
            task_type="support_follow_up",
            title="Follow up on ticket 214",
            description="Check the refund review and update the requester.",
            evidence_ids=[evidence[0].evidence_id],
        ), {"requests": 1, "input_tokens": 18}


class FakeJevClient:
    def __init__(self):
        self.call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def system_one(self, **kwargs):
        self.call = kwargs
        return SimpleNamespace(
            model="fake-jev",
            nouls={"supported": SimpleNamespace(noul=0.91)},
            usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 12}),
        )


class FakeActionJevClient:
    def __init__(self):
        self.call = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def system_one(self, **kwargs):
        self.call = kwargs
        return SimpleNamespace(
            model="fake-jev",
            nouls={"explicit_action": SimpleNamespace(noul=0.87)},
            usage=SimpleNamespace(model_dump=lambda: {"requests": 1}),
        )


class AnswerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = load_fixture()
        self.embedder = MockEmbeddingProvider()
        self.index, _ = ingest_fixture(self.fixture, self.embedder)
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        LlmRun.__table__.create(self.engine)
        KnowledgeAnswerOutput.__table__.create(self.engine)
        KnowledgeMockTask.__table__.create(self.engine)

        @contextmanager
        def sessions():
            with Session(self.engine, expire_on_commit=False) as session:
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise

        self.sessions = sessions

    def tearDown(self):
        self.engine.dispose()

    async def run_case(
        self,
        persona_id,
        question,
        answerer=None,
        grounder=None,
        on_step=None,
        action_classifier=None,
        action_proposer=None,
    ):
        classifier = action_classifier or FakeActionClassifier()
        return await run_answer(
            KnowledgeAnswerRequest(persona_id=persona_id, question=question),
            fixture=self.fixture,
            index=self.index,
            embedder=self.embedder,
            answerer=answerer or FakeAnswerer(),
            grounder=grounder or FakeGrounder(),
            session_scope=self.sessions,
            on_step=on_step,
            action_classifier=classifier,
            action_proposer=action_proposer or FakeActionProposer(),
        )

    async def test_answer_is_cited_and_saved_with_ordered_steps(self):
        answerer = FakeAnswerer()
        grounder = FakeGrounder()
        emitted = []
        result = await self.run_case(
            "alex", "How do I request time off?", answerer, grounder, emitted.append
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.stop_reason, "answered")
        self.assertEqual(result.answer_format, "numbered_list")
        self.assertEqual(result.claims[0].evidence_ids, ["K3"])
        self.assertEqual(
            [step.sequence for step in result.steps],
            list(range(1, len(result.steps) + 1)),
        )
        self.assertEqual(result.steps, emitted)
        self.assertEqual(result.steps[-1].stage, "stop")
        self.assertEqual(len(answerer.calls), 1)
        self.assertTrue(
            any(
                "Before submitting, open the people portal" in item.excerpt
                for item in answerer.calls[0][1]
            )
        )
        self.assertEqual(len(grounder.calls), 1)
        self.assertEqual(result.usage["answer_model"]["input_tokens"], 42)
        self.assertEqual(result.usage["jev_claim_1"]["input_tokens"], 20)
        with self.sessions() as session:
            stored = session.get(KnowledgeAnswerOutput, result.run_id)
            self.assertEqual(stored.response_payload["steps"][-1]["stage"], "stop")
            self.assertEqual(stored.response_payload["answer_format"], "numbered_list")
            self.assertEqual(session.get(LlmRun, result.run_id).status, "completed")

    async def test_ticket_answer_is_access_scoped_and_denied_to_engineering(self):
        answerer = FakeAnswerer(
            AnswerDraft(
                abstain=False,
                claims=[
                    AnswerClaimDraft(
                        statement="A support lead reviews refunds.", evidence_ids=["K1"]
                    )
                ],
            )
        )
        allowed = await self.run_case(
            "alex", "What happens to a customer refund request?", answerer
        )
        denied = await self.run_case(
            "morgan", "What happens to a customer refund request?", answerer
        )
        self.assertEqual(allowed.stop_reason, "answered")
        self.assertEqual(allowed.evidence[0].locator.source_id, "ticket-support-214")
        self.assertEqual(allowed.available_actions, ["support_follow_up"])
        self.assertEqual(allowed.action_evidence_ids, ["K1"])
        self.assertEqual(denied.stop_reason, "no_relevant_passage")
        self.assertEqual(denied.available_actions, [])
        self.assertEqual(len(answerer.calls), 1)
        self.assertNotIn("ticket-support-214", denied.model_dump_json())

    async def test_no_answer_and_action_keyword_before_jev_decision(self):
        answerer = FakeAnswerer()
        grounder = FakeGrounder()
        empty = await self.run_case(
            "alex", "Who manages payroll taxes?", answerer, grounder
        )
        action = await self.run_case(
            "alex", "Please send a refund now", answerer, grounder
        )
        self.assertEqual(empty.stop_reason, "no_relevant_passage")
        self.assertEqual(action.stop_reason, "action_proposal_pending")
        self.assertEqual(answerer.calls, [])
        self.assertEqual(grounder.calls, [])
        self.assertEqual(action.action_status, "pending_approval")
        stages = [item.stage for item in action.steps]
        self.assertLess(
            stages.index("action_intent_signals"),
            stages.index("action_intent_classification"),
        )
        self.assertLess(
            stages.index("action_intent_classification"), stages.index("access_filter")
        )

    async def test_action_policy_approval_rejection_and_idempotent_execution(self):
        action = await self.run_case(
            "alex", "Create a support follow-up for ticket 214"
        )
        self.assertEqual(action.stop_reason, "action_proposal_pending")
        self.assertIsNone(action.mock_task)
        self.assertNotIn(
            "ticket-support-214",
            " ".join(item.locator.source_id for item in action.evidence)
            if action.request.persona_id == "morgan"
            else "",
        )
        with self.sessions() as session:
            denied = decide_action(
                session,
                action.run_id,
                ActionDecisionRequest(
                    approver_id="morgan-engineer", decision="approve"
                ),
                self.fixture,
            )
        self.assertEqual(denied.stop_reason, "action_approval_denied")
        self.assertEqual(denied.action_status, "pending_approval")
        with self.sessions() as session:
            executed = decide_action(
                session,
                action.run_id,
                ActionDecisionRequest(
                    approver_id="jordan-support-lead", decision="approve"
                ),
                self.fixture,
            )
        self.assertEqual(executed.action_status, "executed")
        self.assertIsNotNone(executed.mock_task)
        with self.sessions() as session:
            repeated = decide_action(
                session,
                action.run_id,
                ActionDecisionRequest(
                    approver_id="jordan-support-lead", decision="approve"
                ),
                self.fixture,
            )
            self.assertEqual(session.query(KnowledgeMockTask).count(), 1)
        self.assertEqual(repeated.mock_task.task_id, executed.mock_task.task_id)

        rejected_proposal = await self.run_case(
            "alex", "Create a support follow-up for ticket 214"
        )
        with self.sessions() as session:
            rejected = decide_action(
                session,
                rejected_proposal.run_id,
                ActionDecisionRequest(
                    approver_id="jordan-support-lead", decision="reject"
                ),
                self.fixture,
            )
        self.assertEqual(rejected.action_status, "rejected")
        self.assertIsNone(rejected.mock_task)

    async def test_action_request_acl_denial_proposal_failure_and_stale_source(self):
        denied = await self.run_case(
            "morgan", "Create a support follow-up for ticket 214"
        )
        self.assertEqual(denied.stop_reason, "action_policy_blocked")
        self.assertEqual(denied.evidence, [])
        pending = await self.run_case(
            "alex", "Create a support follow-up for ticket 214"
        )
        changed = self.fixture.model_copy(deep=True)
        changed.sources = tuple(
            item.model_copy(update={"revision": "changed"})
            if item.source_id == "ticket-support-214"
            else item
            for item in changed.sources
        )
        with self.sessions() as session:
            blocked = decide_action(
                session,
                pending.run_id,
                ActionDecisionRequest(
                    approver_id="jordan-support-lead", decision="approve"
                ),
                changed,
            )
        self.assertEqual(blocked.stop_reason, "action_policy_blocked")
        failed = await self.run_case(
            "alex",
            "Create a support follow-up for ticket 214",
            action_proposer=FakeActionProposer(error=True),
        )
        self.assertEqual(failed.stop_reason, "action_proposal_error")

    async def test_action_intent_provider_failure_safely_stops(self):
        answerer = FakeAnswerer()
        result = await self.run_case(
            "alex",
            "Create a support follow-up for ticket 214",
            answerer,
            action_classifier=FakeActionClassifier(error=True),
        )
        self.assertEqual(result.stop_reason, "action_intent_unavailable")
        self.assertEqual(answerer.calls, [])

    async def test_action_approval_api_exposes_demo_roles_and_records_decision(self):
        pending = await self.run_case(
            "alex", "Create a support follow-up for ticket 214"
        )
        client = TestClient(app)
        with patch(
            "backend.internal_knowledge_action.api.db_utils.get_session", self.sessions
        ):
            approvers = client.get("/agent/internal_knowledge_action/approvers")
            response = client.post(
                f"/agent/internal_knowledge_action/actions/{pending.run_id}/decision",
                json={"approver_id": "jordan-support-lead", "decision": "approve"},
            )
        self.assertEqual(approvers.status_code, 200)
        self.assertEqual(len(approvers.json()), 2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action_status"], "executed")
        self.assertEqual(
            response.json()["mock_task"]["source_id"], "ticket-support-214"
        )

    async def test_informational_action_keyword_uses_jev_then_read_only_path(self):
        classifier = FakeActionClassifier(probability=0.1)
        answerer = FakeAnswerer()
        result = await self.run_case(
            "alex",
            "How do I open the people portal?",
            answerer,
            action_classifier=classifier,
        )
        self.assertEqual(len(classifier.calls), 1)
        self.assertEqual(result.stop_reason, "answered")
        self.assertEqual(len(answerer.calls), 1)

    async def test_unknown_citation_is_rejected_before_jev(self):
        answerer = FakeAnswerer(
            AnswerDraft(
                abstain=False,
                claims=[
                    AnswerClaimDraft(
                        statement="A secret fact.", evidence_ids=["restricted-K9"]
                    )
                ],
            )
        )
        grounder = FakeGrounder()
        result = await self.run_case(
            "alex", "How do I request time off?", answerer, grounder
        )
        self.assertEqual(result.stop_reason, "citation_rejected")
        self.assertEqual(result.claims, [])
        self.assertEqual(grounder.calls, [])

    async def test_stale_exact_locator_is_rejected(self):
        result = await self.run_case("alex", "How do I request time off?")
        evidence = result.evidence[0].model_copy(deep=True)
        evidence.locator.start += 1
        reason = _verify_claim(
            AnswerClaimDraft(statement="A claim", evidence_ids=["K1"]),
            {"K1": evidence},
            self.fixture,
            self.index,
            set(result.authorized_source_ids),
        )
        self.assertEqual(reason, "stale_or_invalid_locator")

    async def test_jev_rejection_or_failure_abstains_and_distractor_is_visible(self):
        rejected = await self.run_case(
            "alex",
            "What charge details does the specialist collect for a refund?",
            FakeAnswerer(),
            FakeGrounder(probability=0.2),
        )
        self.assertEqual(rejected.stop_reason, "grounding_rejected")
        self.assertEqual(rejected.claims, [])
        self.assertTrue(
            any(
                item.locator.source_id == "policy-leave-v1"
                for item in rejected.evidence
            )
        )
        unavailable = await self.run_case(
            "alex",
            "How do I request time off?",
            FakeAnswerer(),
            FakeGrounder(error=True),
        )
        self.assertEqual(unavailable.stop_reason, "grounding_unavailable")
        self.assertEqual(unavailable.claims, [])

    async def test_injection_is_data_and_answer_provider_failure_is_saved(self):
        answerer = FakeAnswerer(AnswerDraft(abstain=True, claims=[]))
        injection = await self.run_case(
            "morgan",
            "What old issue comment was copied into the build pipeline note?",
            answerer,
        )
        self.assertEqual(injection.stop_reason, "model_abstained")
        self.assertTrue(
            any("IGNORE ALL PREVIOUS" in item.excerpt for item in injection.evidence)
        )
        failed = await self.run_case(
            "alex", "How do I request time off?", FakeAnswerer(error=True)
        )
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.stop_reason, "answer_model_error")
        with self.sessions() as session:
            self.assertEqual(session.get(LlmRun, failed.run_id).status, "failed")
            self.assertEqual(
                session.get(KnowledgeAnswerOutput, failed.run_id).response_payload[
                    "error_type"
                ],
                "RuntimeError",
            )

    async def test_saved_answer_api_replays_frozen_result(self):
        result = await self.run_case("alex", "How do I request time off?")
        client = TestClient(app)
        with patch(
            "backend.internal_knowledge_action.api.db_utils.get_session", self.sessions
        ):
            listed = client.get("/agent/internal_knowledge_action/answers")
            detail = client.get(
                f"/agent/internal_knowledge_action/answers/{result.run_id}"
            )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["run_id"], str(result.run_id))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(
            detail.json()["evidence"],
            [item.model_dump(mode="json") for item in result.evidence],
        )

    async def test_saved_ticket_answer_derives_follow_up_for_legacy_payload(self):
        answerer = FakeAnswerer(
            AnswerDraft(
                abstain=False,
                claims=[
                    AnswerClaimDraft(
                        statement="A support lead reviews the refund request.",
                        evidence_ids=["K1"],
                    )
                ],
            )
        )
        result = await self.run_case(
            "alex", "What happens to a customer refund request?", answerer
        )
        with self.sessions() as session:
            saved = session.get(KnowledgeAnswerOutput, result.run_id)
            saved.response_payload.pop("available_actions", None)
            saved.response_payload.pop("action_evidence_ids", None)
            session.commit()

        with patch(
            "backend.internal_knowledge_action.api.db_utils.get_session", self.sessions
        ):
            detail = TestClient(app).get(
                f"/agent/internal_knowledge_action/answers/{result.run_id}"
            )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["available_actions"], ["support_follow_up"])
        self.assertEqual(detail.json()["action_evidence_ids"], ["K1"])

    async def test_stream_endpoint_emits_steps_and_terminal_saved_result(self):
        async def fake_run(request, *, on_step):
            return await run_answer(
                request,
                fixture=self.fixture,
                index=self.index,
                embedder=self.embedder,
                answerer=FakeAnswerer(),
                grounder=FakeGrounder(),
                session_scope=self.sessions,
                on_step=on_step,
            )

        with patch("backend.internal_knowledge_action.api.run_answer", fake_run):
            response = TestClient(app).post(
                "/agent/internal_knowledge_action/answer-stream",
                json={"persona_id": "alex", "question": "How do I request time off?"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: step", response.text)
        self.assertIn("event: result", response.text)
        self.assertLess(
            response.text.index("event: step"), response.text.index("event: result")
        )

    async def test_live_adapter_shapes_use_only_selected_passages(self):
        result = await self.run_case("alex", "How do I request time off?")
        selected = result.evidence[:1]

        class FakeAgent:
            async def run(self, prompt, **kwargs):
                self.prompt = prompt
                self.kwargs = kwargs
                return SimpleNamespace(
                    output=AnswerDraft(abstain=True, claims=[]), usage=RunUsage()
                )

        answerer = LiveAnswerProvider.__new__(LiveAnswerProvider)
        answerer.agent = FakeAgent()
        draft, usage = await answerer.answer(
            "How do I request time off?", selected, result.run_id
        )
        self.assertTrue(draft.abstain)
        self.assertIn(selected[0].excerpt, answerer.agent.prompt)
        self.assertNotIn("ticket-support-214", answerer.agent.prompt)
        self.assertEqual(answerer.agent.kwargs["usage_limits"].request_limit, 1)
        self.assertIsInstance(usage, dict)

        client = FakeJevClient()
        with patch(
            "backend.internal_knowledge_action.grounding.AsyncTypeSafeClient",
            return_value=client,
        ):
            judgment = await LiveJevGroundingProvider().judge(
                AnswerClaimDraft(
                    statement="A manager approves time off.", evidence_ids=["K1"]
                ),
                selected,
            )
        self.assertEqual(judgment.probability, 0.91)
        self.assertEqual(client.call["model"], "jev-latest")
        self.assertEqual(
            client.call["state"]["cited_passages"][0]["text"], selected[0].excerpt
        )

    async def test_action_jev_and_proposal_adapters_are_bounded_and_typed(self):
        client = FakeActionJevClient()
        with patch(
            "backend.internal_knowledge_action.action_intent.AsyncTypeSafeClient",
            return_value=client,
        ):
            judgment = await LiveJevActionIntentProvider().classify(
                "Please create a follow-up", ["create"]
            )
        self.assertEqual(judgment.probability, 0.87)
        self.assertEqual(
            client.call["state"]["deterministic_action_signals"], ["create"]
        )
        self.assertIn("explicit_action", client.call["questions"])

        result = await self.run_case("alex", "What happens to ticket 214?")

        class FakeAgent:
            async def run(self, prompt, **kwargs):
                self.prompt = prompt
                self.kwargs = kwargs
                return SimpleNamespace(
                    output=TaskProposalDraft(
                        task_type="support_follow_up",
                        title="Follow up ticket 214",
                        description="Check the queue.",
                        evidence_ids=["K1"],
                    ),
                    usage=RunUsage(),
                )

        proposer = LiveActionProposalProvider.__new__(LiveActionProposalProvider)
        proposer.agent = FakeAgent()
        selected = result.evidence[:1]
        draft, usage = await proposer.propose(
            "Create a follow-up", selected, result.run_id
        )
        self.assertEqual(draft.task_type, "support_follow_up")
        self.assertIn(selected[0].excerpt, proposer.agent.prompt)
        self.assertEqual(proposer.agent.kwargs["usage_limits"].request_limit, 1)
        self.assertIsInstance(usage, dict)


if __name__ == "__main__":
    unittest.main()
