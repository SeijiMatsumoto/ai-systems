import importlib
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

from backend.db.schemas import DocumentType
from backend.project_02_research_briefing_system.agent.agent import (
    FetchFinancialsInput,
    MyDeps,
    SearchDocumentsInput,
)
from backend.project_02_research_briefing_system.agent.models import FinancialEvidence
from backend.project_02_research_briefing_system.service.research import (
    validate_financial_evidence,
)

agent_module = importlib.import_module(
    "backend.project_02_research_briefing_system.agent.agent"
)


class AgentToolResponseTests(unittest.TestCase):
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
