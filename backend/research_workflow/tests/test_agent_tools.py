import importlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from backend.db.schemas import DocumentType
from backend.research_workflow.agent.agent import (
    FetchFinancialsInput,
    InspectNewsInput,
    MyDeps,
    SearchDocumentsInput,
    SearchNewsInput,
)
from backend.research_workflow.agent.models import (
    DocumentEvidence,
    FinancialEvidence,
)
from backend.research_workflow.service.research import (
    validate_financial_evidence,
)

agent_module = importlib.import_module(
    "backend.research_workflow.agent.agent"
)


class AgentToolResponseTests(unittest.TestCase):
    def test_search_news_adds_bounded_preview_when_summary_is_missing(self) -> None:
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime.now(timezone.utc) - timedelta(minutes=1),
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        full_content = " ".join(
            [
                "Apple is adjusting its product roadmap after demand and execution challenges."
            ]
            * 20
        )
        article = {
            "reference_id": "article-1",
            "title": "Apple adjusts product roadmap",
            "summary": None,
            "source_url": "https://example.com/apple-roadmap",
            "published_at": "2026-08-21T12:00:00Z",
            "content": full_content,
        }

        with patch.object(agent_module, "fetch_news", return_value=[article]):
            response = agent_module.search_news(
                context,
                SearchNewsInput(query="product roadmap execution risk"),
            )

        result = response["articles"][0]
        self.assertIsNone(result["summary"])
        self.assertLessEqual(len(result["content_preview"]), 401)
        self.assertTrue(result["content_preview"].endswith("…"))
        self.assertNotIn("content", result)
        self.assertEqual(deps.news_articles["article-1"]["content"], full_content)

    def test_search_news_clamps_explicit_old_date_to_provider_window(self) -> None:
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime.now(timezone.utc) - timedelta(minutes=1),
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))

        with patch.object(agent_module, "fetch_news", return_value=[]) as fetch:
            response = agent_module.search_news(
                context,
                SearchNewsInput(
                    query="product launch risks",
                    date_from=datetime.now(timezone.utc) - timedelta(days=90),
                ),
            )

        self.assertTrue(response["date_range_limited_by_provider"])
        self.assertGreater(
            fetch.call_args.kwargs["date_from"],
            datetime.now(timezone.utc) - timedelta(days=30),
        )
        self.assertEqual(fetch.call_args.kwargs["date_to"], deps.as_of)

    def test_inspect_news_registers_one_relevant_passage_per_cached_article(
        self,
    ) -> None:
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime(2026, 8, 22, tzinfo=timezone.utc),
            evidence_catalog={},
            financial_sources={},
            news_articles={
                "article-1": {
                    "reference_id": "article-1",
                    "title": "Apple prepares a foldable iPhone supply chain",
                    "source_url": "https://example.com/apple-foldable",
                    "published_at": "2026-08-20T12:00:00Z",
                    "content": "Full article retained in run-scoped storage.",
                }
            },
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        persisted_rows = [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000002",
                "reference_id": "world_news:article-1",
                "chunk_index": 0,
                "document_id": "00000000-0000-0000-0000-000000000001",
                "document_type": "article",
                "content": (
                    "Apple is preparing foldable iPhone manufacturing capacity, "
                    "which introduces launch execution and supply-chain risks."
                ),
                "content_quality": "full_text",
                "similarity": 0.0,
                "title": "Apple prepares a foldable iPhone supply chain",
                "source_url": "https://example.com/apple-foldable",
                "published_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
            }
        ]

        with patch.object(
            agent_module,
            "persist_inspected_news_article",
            return_value=persisted_rows,
        ) as persist:
            response = agent_module.inspect_news_articles(
                context,
                InspectNewsInput(
                    article_ids=["article-1", "missing", "article-1"],
                    focus="foldable iPhone manufacturing and supply-chain risks",
                ),
            )

        self.assertEqual(len(response["evidence_candidates"]), 1)
        self.assertEqual(response["unknown_article_ids"], ["missing"])
        self.assertEqual(response["articles_after_as_of"], [])
        self.assertEqual(response["articles_without_matching_passages"], [])
        self.assertEqual(persist.call_count, 1)
        self.assertEqual(len(deps.evidence_catalog), 1)
        evidence = next(iter(deps.evidence_catalog.values()))
        self.assertIsInstance(evidence, DocumentEvidence)
        assert isinstance(evidence, DocumentEvidence)
        self.assertEqual(evidence.reference_id, "world_news:article-1")
        self.assertIn("foldable iPhone manufacturing", evidence.quote)

    def test_search_documents_expands_pool_but_returns_requested_count(self) -> None:
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime.now(timezone.utc),
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        rows = [
            {
                "chunk_id": f"chunk-{index}",
                "reference_id": "filing-1",
                "chunk_index": index,
                "document_id": "document-1",
                "document_type": "filing",
                "content": (
                    f"Apple material risk {index} may affect revenue, costs, "
                    "operations, and financial condition."
                ),
                "similarity": 0.9 - index / 100,
                "title": "Apple filing",
                "source_url": "https://example.com/apple",
                "published_at": None,
            }
            for index in range(8)
        ]

        with patch.object(
            agent_module,
            "retrieve_document_by_distance",
            return_value=rows,
        ) as retrieve:
            response = agent_module.search_documents(
                context,
                SearchDocumentsInput(
                    query="Apple material risk revenue",
                    document_type=DocumentType.FILING,
                    top_n=3,
                ),
            )

        self.assertEqual(len(response["evidence_candidates"]), 3)
        self.assertEqual(len(deps.evidence_catalog), 3)
        self.assertEqual(retrieve.call_args.kwargs["top_n"], 8)
        self.assertEqual(retrieve.call_args.kwargs["neighbor_radius"], 1)

    def test_historical_financials_returns_only_compact_curated_metrics(self) -> None:
        raw_data = {
            "symbol": "AAPL",
            "statement_type": "income",
            "frequency": "yearly",
            "periods": [
                {
                    "period_end": "2025-09-30",
                    "metrics": {
                        "TotalRevenue": 400,
                        "NetIncome": 100,
                        "UncuratedMetric": 999,
                    },
                }
            ],
        }
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime.now(timezone.utc),
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))

        with patch.object(
            agent_module,
            "get_historical_financials",
            return_value=raw_data,
        ):
            response = agent_module.historical_financials(
                context,
                FetchFinancialsInput(
                    statement_type="income",
                    frequency="yearly",
                    periods=1,
                ),
            )

        self.assertNotIn("data", response)
        metrics = response["periods"][0]["metrics"]
        self.assertEqual(
            {metric["name"] for metric in metrics},
            {"TotalRevenue", "NetIncome"},
        )
        self.assertLess(len(json.dumps(response)), 2_000)
        self.assertEqual(len(deps.evidence_catalog), 2)
        self.assertEqual(
            deps.financial_sources["historical_financials:AAPL:income:yearly:1"],
            {"data": raw_data},
        )
        for evidence in deps.evidence_catalog.values():
            self.assertIsInstance(evidence, FinancialEvidence)
            assert isinstance(evidence, FinancialEvidence)
            self.assertTrue(
                validate_financial_evidence(evidence, deps.financial_sources)
            )


if __name__ == "__main__":
    unittest.main()
