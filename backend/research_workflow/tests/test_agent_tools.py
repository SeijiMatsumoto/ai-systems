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
    InspectWebInput,
    MyDeps,
    SearchDocumentsInput,
    SearchWebInput,
)
from backend.research_workflow.contracts import (
    ExtractedWebPage,
    FinancialEvidence,
    WebSearchResult,
)
from backend.research_workflow.service.research import (
    validate_financial_evidence,
)

agent_module = importlib.import_module("backend.research_workflow.agent.agent")


class AgentToolResponseTests(unittest.TestCase):
    def test_search_web_scopes_company_and_rejects_wrong_company(self) -> None:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        deps = MyDeps(
            symbol="AAPL",
            company_name="Apple Inc.",
            as_of=as_of,
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        results = [
            WebSearchResult(
                result_id="tavily:one",
                title="Apple product roadmap",
                source_url="https://example.com/apple",
                summary="Apple discusses launches",
                published_at=as_of - timedelta(days=1),
                date_precision="instant",
            ),
            WebSearchResult(
                result_id="tavily:two",
                title="Microsoft product roadmap",
                source_url="https://example.com/msft",
                summary="Microsoft discusses launches",
                published_at=as_of - timedelta(days=1),
                date_precision="instant",
            ),
        ]
        with patch.object(
            agent_module.tavily, "search", return_value=(results, 1)
        ) as search:
            response = agent_module.search_web(
                context, SearchWebInput(query="product roadmap execution risk")
            )
        self.assertEqual(
            [item["result_id"] for item in response["results"]], ["tavily:one"]
        )
        self.assertEqual(response["rejected_company_scope"], 1)
        self.assertEqual(response["rejected_dates_or_metadata"], 1)
        self.assertIn("Apple Inc.", search.call_args.kwargs["query"])
        self.assertEqual(set(deps.web_results), {"tavily:one"})

    def test_inspect_web_registers_only_selected_extracted_passages(self) -> None:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        result = WebSearchResult(
            result_id="tavily:one",
            title="Apple prepares foldable iPhone",
            source_url="https://example.com/apple",
            summary="Apple supply chain",
            published_at=as_of - timedelta(days=1),
            date_precision="instant",
        )
        deps = MyDeps(
            symbol="AAPL",
            company_name="Apple Inc.",
            as_of=as_of,
            evidence_catalog={},
            financial_sources={},
            web_results={result.result_id: result},
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        rows = [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000002",
                "reference_id": "tavily:one",
                "chunk_index": 0,
                "document_id": "00000000-0000-0000-0000-000000000001",
                "document_type": "article",
                "content": "Apple is preparing foldable iPhone manufacturing capacity, which introduces launch execution and supply-chain risks.",
                "content_quality": "full_text",
                "similarity": 0.0,
                "title": result.title,
                "source_url": result.source_url,
                "published_at": result.published_at,
            }
        ]
        with (
            patch.object(
                agent_module.tavily,
                "extract",
                return_value=(
                    [
                        ExtractedWebPage(
                            source_url=result.source_url, content="source text"
                        )
                    ],
                    [],
                ),
            ) as extract,
            patch.object(
                agent_module, "persist_inspected_web_page", return_value=rows
            ) as persist,
        ):
            response = agent_module.inspect_web_results(
                context,
                InspectWebInput(
                    result_ids=["tavily:one", "missing", "tavily:one"],
                    focus="foldable iPhone manufacturing risks",
                ),
            )
        self.assertEqual(extract.call_args.args[0], [result.source_url])
        self.assertEqual(persist.call_count, 1)
        self.assertEqual(response["unknown_result_ids"], ["missing"])
        self.assertEqual(len(response["evidence_candidates"]), 1)
        self.assertEqual(
            next(iter(deps.evidence_catalog.values())).reference_id, "tavily:one"
        )

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
                    "period_end": "2099-09-30",
                    "metrics": {"TotalRevenue": 9999},
                },
                {
                    "period_end": "2025-09-30",
                    "metrics": {
                        "TotalRevenue": 400,
                        "NetIncome": 100,
                        "UncuratedMetric": 999,
                    },
                },
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
            {
                "data": {
                    "periods": [
                        {
                            "period_end": "2025-09-30",
                            "metrics": {"TotalRevenue": 400, "NetIncome": 100},
                        }
                    ]
                }
            },
        )
        for evidence in deps.evidence_catalog.values():
            self.assertIsInstance(evidence, FinancialEvidence)
            assert isinstance(evidence, FinancialEvidence)
            self.assertTrue(
                validate_financial_evidence(evidence, deps.financial_sources)
            )

    def test_historical_financials_declines_mutable_provider_view(self) -> None:
        deps = MyDeps(
            symbol="AAPL",
            as_of=datetime.now(timezone.utc) - timedelta(days=2),
            evidence_catalog={},
            financial_sources={},
        )
        context = cast(Any, SimpleNamespace(deps=deps))
        with patch.object(agent_module, "get_historical_financials") as provider:
            result = agent_module.historical_financials(context, FetchFinancialsInput())
        self.assertIn("cannot establish availability", result["error"])
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
