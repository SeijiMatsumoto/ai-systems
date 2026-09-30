import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.internal_knowledge_action.contracts import RetrievalPreviewRequest
from backend.internal_knowledge_action.embedding import (
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from backend.internal_knowledge_action.evaluation import (
    evaluate_retrieval,
    load_dataset,
)
from backend.internal_knowledge_action.ingestion import (
    chunk_source,
    index_matches_fixture,
    ingest_fixture,
    load_fixture,
    load_index,
    save_index,
)
from backend.internal_knowledge_action.retrieval import preview_retrieval
from backend.main import app


class CountingEmbedder(MockEmbeddingProvider):
    def __init__(self) -> None:
        self.document_calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[tuple[float, ...]]:
        self.document_calls.append(texts)
        return super().embed_documents(texts)


class RetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = load_fixture()
        cls.embedder = MockEmbeddingProvider()
        cls.index, _ = ingest_fixture(cls.fixture, cls.embedder)

    def test_fixture_has_complete_acl_and_exact_chunk_offsets(self) -> None:
        self.assertEqual(
            {item.persona_id for item in self.fixture.personas}, {"alex", "morgan"}
        )
        self.assertEqual(
            {item.source_id for item in self.fixture.sources},
            {item.source_id for item in self.fixture.acl},
        )
        sources = {source.source_id: source for source in self.fixture.sources}
        for source in self.fixture.sources:
            self.assertGreaterEqual(
                sum(chunk.source_id == source.source_id for chunk in self.index.chunks),
                8,
            )
        for chunk in self.index.chunks:
            self.assertEqual(
                chunk.text, sources[chunk.source_id].body[chunk.start : chunk.end]
            )
            self.assertLessEqual(len(chunk.text), 180)

    def test_long_source_is_split_with_exact_offsets(self) -> None:
        source = self.fixture.sources[0].model_copy(
            update={"body": "A long sentence about leave. " * 20}
        )
        chunks = chunk_source(source)
        self.assertGreater(len(chunks), 1)
        for text, start, end in chunks:
            self.assertEqual(text, source.body[start:end])
            self.assertLessEqual(len(text), 180)

    def test_fixture_rejects_missing_acl(self) -> None:
        payload = self.fixture.model_dump(mode="json")
        payload["acl"].pop()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "exactly one ACL"):
                load_fixture(path)

    def test_ingestion_is_idempotent_and_embeds_changed_content_only(self) -> None:
        embedder = CountingEmbedder()
        first, report = ingest_fixture(self.fixture, embedder)
        self.assertEqual(report.embedded_chunks, len(first.chunks))
        second, report = ingest_fixture(self.fixture, embedder, first)
        self.assertEqual(report.embedded_chunks, 0)
        self.assertEqual(len(embedder.document_calls), 1)
        self.assertEqual(first, second)

        changed = self.fixture.sources[1].model_copy(
            update={
                "revision": "2026-09-13",
                "body": self.fixture.sources[1].body + " The case was updated.",
            }
        )
        sources = tuple(
            changed if source.source_id == changed.source_id else source
            for source in self.fixture.sources
        )
        revised_fixture = self.fixture.model_copy(update={"sources": sources})
        revised, report = ingest_fixture(revised_fixture, embedder, second)
        self.assertEqual(report.updated_sources, [changed.source_id])
        self.assertEqual(
            report.embedded_chunks,
            len(
                [
                    chunk
                    for chunk in revised.chunks
                    if chunk.source_id == changed.source_id
                ]
            ),
        )
        self.assertEqual(len(embedder.document_calls), 2)
        self.assertTrue(index_matches_fixture(revised, revised_fixture))
        self.assertFalse(index_matches_fixture(second, revised_fixture))

    def test_acl_change_updates_index_without_reembedding_and_deletion_removes_chunks(
        self,
    ) -> None:
        embedder = CountingEmbedder()
        prior, _ = ingest_fixture(self.fixture, embedder)
        changed_acl = tuple(
            rule.model_copy(update={"allowed_groups": ("engineering",)})
            if rule.source_id == "ticket-support-214"
            else rule
            for rule in self.fixture.acl
        )
        acl_fixture = self.fixture.model_copy(update={"acl": changed_acl})
        revised, report = ingest_fixture(acl_fixture, embedder, prior)
        self.assertEqual(report.acl_only_sources, ["ticket-support-214"])
        self.assertEqual(report.embedded_chunks, 0)
        self.assertEqual(len(embedder.document_calls), 1)
        self.assertFalse(index_matches_fixture(prior, acl_fixture))

        reduced_fixture = acl_fixture.model_copy(
            update={
                "sources": tuple(
                    item
                    for item in acl_fixture.sources
                    if item.source_id != "ticket-support-214"
                ),
                "acl": tuple(
                    item
                    for item in acl_fixture.acl
                    if item.source_id != "ticket-support-214"
                ),
            }
        )
        reduced, report = ingest_fixture(reduced_fixture, embedder, revised)
        self.assertEqual(report.removed_sources, ["ticket-support-214"])
        self.assertTrue(
            all(chunk.source_id != "ticket-support-214" for chunk in reduced.chunks)
        )

    def test_index_persists_and_reloads_without_provider_call(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "index.local"
            save_index(self.index, path)
            self.assertEqual(load_index(path), self.index)

    def test_embedding_model_change_rebuilds_all_chunks(self) -> None:
        embedder = CountingEmbedder()
        embedder.model_id = "mock-embedding-v2"
        rebuilt, report = ingest_fixture(self.fixture, embedder, self.index)
        self.assertEqual(report.embedded_chunks, len(rebuilt.chunks))
        self.assertEqual(rebuilt.embedding_model, "mock-embedding-v2")

    def test_acl_scopes_both_candidate_paths_and_output(self) -> None:
        request = RetrievalPreviewRequest(
            persona_id="alex",
            question="engineering rotation build pipeline restricted documents",
        )
        result = preview_retrieval(request, self.fixture, self.index, self.embedder)
        self.assertEqual(
            result.authorized_source_ids, ["policy-leave-v1", "ticket-support-214"]
        )
        self.assertTrue(
            all(
                candidate.source_id in result.authorized_source_ids
                for candidate in result.lexical_candidates + result.vector_candidates
            )
        )
        self.assertTrue(
            all(
                item.locator.source_id in result.authorized_source_ids
                for item in result.ranked_excerpts
            )
        )
        self.assertNotIn("IGNORE ALL PREVIOUS", result.model_dump_json())

    def test_vector_path_recovers_paraphrase_missing_from_lexical_path(self) -> None:
        result = preview_retrieval(
            RetrievalPreviewRequest(
                persona_id="alex", question="How much PTO is left?"
            ),
            self.fixture,
            self.index,
            self.embedder,
        )
        self.assertEqual(result.lexical_candidates, [])
        self.assertEqual(result.ranked_excerpts[0].locator.source_id, "policy-leave-v1")
        self.assertEqual(result.ranked_excerpts[0].vector_rank, 1)

    def test_ranked_chunk_includes_exact_procedural_paragraph(self) -> None:
        result = preview_retrieval(
            RetrievalPreviewRequest(
                persona_id="alex", question="How do I request time off?"
            ),
            self.fixture,
            self.index,
            self.embedder,
        )
        body = self.fixture.sources[0].body
        passages = [item.excerpt for item in result.ranked_excerpts]
        self.assertTrue(
            any(
                "Before submitting, open the people portal" in item for item in passages
            )
        )
        self.assertTrue(
            any(
                "Choose the dates, select the appropriate leave type" in item
                for item in passages
            )
        )
        for item in result.ranked_excerpts:
            self.assertEqual(item.excerpt, body[item.locator.start : item.locator.end])

    def test_no_authorized_answer_and_injection_remains_data(self) -> None:
        denied = preview_retrieval(
            RetrievalPreviewRequest(
                persona_id="morgan",
                question="What happens to a customer refund request?",
            ),
            self.fixture,
            self.index,
            self.embedder,
        )
        self.assertEqual(denied.ranked_excerpts, [])
        found = preview_retrieval(
            RetrievalPreviewRequest(
                persona_id="morgan", question="build pipeline deployments"
            ),
            self.fixture,
            self.index,
            self.embedder,
        )
        self.assertIn(
            "doc-engineering-injection",
            [item.locator.source_id for item in found.ranked_excerpts],
        )
        self.assertEqual(found.stop_reason, "retrieval_preview_only")
        self.assertEqual(
            [step.stage for step in found.steps],
            [
                "request_check",
                "access_filter",
                "lexical_search",
                "vector_search",
                "fusion_rerank",
                "stop",
            ],
        )

    def test_small_mock_eval_tracks_recall_no_answer_and_acl(self) -> None:
        outcome = evaluate_retrieval(
            self.fixture, self.index, self.embedder, load_dataset()
        )
        self.assertEqual(outcome.case_count, 12)
        self.assertEqual(outcome.recall_at_3, 1.0)
        self.assertEqual(outcome.precision_among_returned, 0.944)
        self.assertEqual(outcome.top_1_accuracy, 1.0)
        self.assertEqual(outcome.no_answer_accuracy, 1.0)
        self.assertEqual(outcome.unauthorized_source_count, 0)

    def test_live_embedding_adapter_orders_provider_response(self) -> None:
        client = Mock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[0.0, 1.0]),
                SimpleNamespace(index=0, embedding=[1.0, 0.0]),
            ]
        )
        adapter = OpenAIEmbeddingProvider(client=client)
        self.assertEqual(
            adapter.embed_documents(["first", "second"]), [(1.0, 0.0), (0.0, 1.0)]
        )
        client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small", input=["first", "second"]
        )

    def test_api_requires_index_and_rejects_user_supplied_groups(self) -> None:
        client = TestClient(app)
        with patch(
            "backend.internal_knowledge_action.api.load_index", return_value=None
        ):
            missing = client.post(
                "/agent/internal_knowledge_action/retrieval-preview",
                json={"persona_id": "alex", "question": "leave"},
            )
        self.assertEqual(missing.status_code, 409)
        invalid = client.post(
            "/agent/internal_knowledge_action/retrieval-preview",
            json={"persona_id": "alex", "question": "leave", "groups": ["engineering"]},
        )
        self.assertEqual(invalid.status_code, 422)
        oversized = client.post(
            "/agent/internal_knowledge_action/retrieval-preview",
            json={"persona_id": "alex", "question": "x" * 501},
        )
        self.assertEqual(oversized.status_code, 422)
        with patch(
            "backend.internal_knowledge_action.api.load_index", return_value=self.index
        ):
            unknown = client.post(
                "/agent/internal_knowledge_action/retrieval-preview",
                json={"persona_id": "unknown", "question": "leave"},
            )
        self.assertEqual(unknown.status_code, 404)

    def test_api_mock_ingestion_and_preview_without_real_provider(self) -> None:
        client = TestClient(app)
        saved: list = []
        with (
            patch(
                "backend.internal_knowledge_action.api.load_index",
                side_effect=lambda: saved[-1] if saved else None,
            ),
            patch(
                "backend.internal_knowledge_action.api.save_index",
                side_effect=saved.append,
            ),
        ):
            built = client.post("/agent/internal_knowledge_action/index-fixture")
            self.assertEqual(built.status_code, 200)
            self.assertEqual(built.json()["embedded_chunks"], len(self.index.chunks))
            status = client.get("/agent/internal_knowledge_action/index-status")
            self.assertTrue(status.json()["ready"])
            preview = client.post(
                "/agent/internal_knowledge_action/retrieval-preview",
                json={"persona_id": "alex", "question": "How do I request time off?"},
            )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(
            preview.json()["embedding_model"], MockEmbeddingProvider.model_id
        )
        self.assertEqual(
            preview.json()["ranked_excerpts"][0]["locator"]["source_id"],
            "policy-leave-v1",
        )


if __name__ == "__main__":
    unittest.main()
