import unittest

from backend.research_workflow.agent.evidence import (
    build_document_evidence_candidates,
    build_financial_evidence_candidates,
    catalog_from_candidates,
    compact_document_evidence,
    compact_financial_evidence,
    hydrate_briefing,
    split_passages,
)
from backend.research_workflow.contracts import (
    DraftFinding,
    DraftResearchBriefing,
)
from backend.research_workflow.service.research import (
    _compact_price_summary,
)


class EvidenceCatalogTests(unittest.TestCase):
    def test_article_is_document_evidence_with_snippet_quality(self) -> None:
        article_content = " ".join(
            ["Apple announced a product launch with material strategic details."] * 12
        )
        candidates = build_document_evidence_candidates(
            "Apple product launch",
            [
                {
                    "chunk_id": "chunk-1",
                    "reference_id": "article-1",
                    "chunk_index": 0,
                    "document_id": "document-1",
                    "document_type": "article",
                    "content": article_content,
                    "title": "Apple announcement",
                    "source_url": "https://example.com/apple",
                    "published_at": None,
                }
            ],
        )

        self.assertEqual(candidates[0].evidence_type, "document")
        self.assertEqual(candidates[0].document_type.value, "article")
        self.assertEqual(candidates[0].content_quality, "snippet")

        compact = compact_document_evidence(candidates[0])
        self.assertEqual(compact["quote"], article_content)
        self.assertNotIn("chunk_id", compact)
        self.assertNotIn("content_hash", compact)

    def test_passages_are_exact_slices_of_source(self) -> None:
        source = "First material statement.\n\nSecond material statement."

        passages = split_passages(source)

        self.assertEqual(len(passages), 2)
        for start, end, passage in passages:
            self.assertEqual(source[start:end], passage)

    def test_document_candidates_filter_boilerplate_and_rank_globally(self) -> None:
        shared = {
            "reference_id": "filing-1",
            "document_id": "document-1",
            "document_type": "filing",
            "title": "Example filing",
            "source_url": "https://example.com/filing",
            "published_at": None,
            "content_quality": "full_text",
        }
        candidates = build_document_evidence_candidates(
            "tariffs material impact gross margin",
            [
                {
                    **shared,
                    "chunk_id": "chunk-1",
                    "chunk_index": 1,
                    "similarity": 0.9,
                    "content": (
                        "Example Inc. | 2026 Form 10-Q | 13\n\n[Scrubbed due to 'auth']"
                    ),
                },
                {
                    **shared,
                    "chunk_id": "chunk-2",
                    "chunk_index": 2,
                    "similarity": 0.85,
                    "content": (
                        "Tariffs applied to components may materially affect gross "
                        "margin, product pricing, and the company's financial results."
                    ),
                },
            ],
            max_candidates=3,
        )

        self.assertEqual(len(candidates), 1)
        self.assertIn("materially affect gross margin", candidates[0].quote)

    def test_document_candidates_respect_final_payload_limit(self) -> None:
        rows = [
            {
                "chunk_id": f"chunk-{index}",
                "reference_id": "filing-1",
                "chunk_index": index,
                "document_id": "document-1",
                "document_type": "filing",
                "content": (
                    f"Material risk number {index} may affect revenue, costs, "
                    "operations, and financial condition over time."
                ),
                "similarity": 0.9 - index / 100,
                "title": "Example filing",
                "source_url": "https://example.com/filing",
                "published_at": None,
            }
            for index in range(8)
        ]

        candidates = build_document_evidence_candidates(
            "material risk revenue",
            rows,
            max_candidates=3,
        )

        self.assertEqual(len(candidates), 3)

    def test_article_candidates_reject_boilerplate_and_deduplicate_stories(
        self,
    ) -> None:
        body = " ".join(
            [
                "Apple product delays and demand uncertainty may affect execution and investment returns."
            ]
            * 10
        )
        rows = [
            {
                "chunk_id": "chunk-nav",
                "reference_id": "article-nav",
                "chunk_index": 0,
                "document_id": "document-nav",
                "document_type": "article",
                "content": "\n".join(
                    [
                        "Latest Headlines",
                        "Top Stories",
                        "Breaking News",
                        "Stock Alerts",
                        "Industry News",
                        "Earnings Calendar",
                    ]
                    * 8
                ),
                "similarity": 0.99,
                "title": "Navigation page",
                "source_url": "https://example.com/navigation",
                "published_at": None,
                "content_quality": "full_text",
            },
            {
                "chunk_id": "chunk-1",
                "reference_id": "article-1",
                "chunk_index": 0,
                "document_id": "document-1",
                "document_type": "article",
                "content": body,
                "similarity": 0.9,
                "title": "Apple Product Delays Raise Execution Questions",
                "source_url": "https://example.com/story-one",
                "published_at": None,
                "content_quality": "full_text",
            },
            {
                "chunk_id": "chunk-2",
                "reference_id": "article-2",
                "chunk_index": 0,
                "document_id": "document-2",
                "document_type": "article",
                "content": body,
                "similarity": 0.85,
                "title": "Apple product delays raise execution questions!",
                "source_url": "https://example.com/story-two",
                "published_at": None,
                "content_quality": "full_text",
            },
        ]

        candidates = build_document_evidence_candidates(
            "Apple product execution risk",
            rows,
            max_candidates=3,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].reference_id, "article-1")

    def test_financial_candidates_keep_resolvable_field_paths(self) -> None:
        data = {"valuation": {"forward_pe": 21.5}, "prices": [{"close": 200.0}]}

        candidates = build_financial_evidence_candidates(
            reference_id="company_snapshot:AAPL",
            title="AAPL snapshot",
            source="Yahoo Finance",
            data=data,
        )

        values_by_path = {item.field_path: item.value for item in candidates}
        self.assertEqual(values_by_path["valuation.forward_pe"], 21.5)
        self.assertEqual(values_by_path["prices.0.close"], 200.0)
        self.assertEqual(
            compact_financial_evidence(candidates[0]).keys(),
            {"evidence_id", "field_path", "value"},
        )

    def test_price_summary_keeps_only_start_end_low_high_evidence(self) -> None:
        close_data: list[dict[str, str | float]] = [
            {"Date": "2026-01-01", "Close": 100.0},
            {"Date": "2026-01-02", "Close": 80.0},
            {"Date": "2026-01-03", "Close": 120.0},
            {"Date": "2026-01-04", "Close": 110.0},
        ]
        candidates = build_financial_evidence_candidates(
            reference_id="close_data:AAPL",
            title="AAPL prices",
            source="Yahoo Finance",
            data=close_data,
        )

        summary, selected = _compact_price_summary(close_data, candidates)

        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["period_change_pct"], 10.0)
        self.assertEqual(len(selected), 8)
        self.assertEqual(
            {candidate.field_path for candidate in selected},
            {
                "0.Date",
                "0.Close",
                "1.Date",
                "1.Close",
                "2.Date",
                "2.Close",
                "3.Date",
                "3.Close",
            },
        )

    def test_hydration_resolves_known_ids_and_reports_unknown_ids(self) -> None:
        candidate = build_financial_evidence_candidates(
            reference_id="company_snapshot:AAPL",
            title="AAPL snapshot",
            source="Yahoo Finance",
            data={"market_cap": 1_000},
        )[0]
        draft = DraftResearchBriefing(
            executive_summary="Summary",
            key_findings=[
                DraftFinding(
                    statement="Apple has the recorded market capitalization.",
                    claim_type="fact",
                    confidence=2,
                    evidence_ids=[candidate.evidence_id, "fin:invented"],
                )
            ],
            outlook="Conditional outlook.",
        )

        briefing, invalid_ids = hydrate_briefing(
            draft, catalog_from_candidates([candidate])
        )

        self.assertEqual(briefing.key_findings[0].evidence, [candidate])
        self.assertEqual(invalid_ids, ["fin:invented"])


if __name__ == "__main__":
    unittest.main()
