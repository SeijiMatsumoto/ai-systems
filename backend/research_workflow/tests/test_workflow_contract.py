import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from backend.db.schemas import DocumentType
from backend.research_workflow.contracts import (
    BriefingRequest,
    DocumentEvidence,
    SearchWebInput,
)
from backend.research_workflow.service.research import (
    _prefetched_financial_context,
    create_fingerprint,
    validate_document_evidence,
)


class WorkflowContractTests(unittest.TestCase):
    def request(self, as_of: datetime) -> BriefingRequest:
        return BriefingRequest(
            symbol="AAPL",
            as_of=as_of,
            research_question="What changed in Apple's business risk this month?",
            audience="investors",
            time_horizon="12m",
        )

    def test_cache_key_uses_full_as_of_instant(self) -> None:
        first = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        later = first + timedelta(hours=1)
        self.assertNotEqual(
            create_fingerprint(self.request(first)),
            create_fingerprint(self.request(later)),
        )
        same_instant = first.astimezone(timezone(timedelta(hours=-5)))
        self.assertEqual(
            create_fingerprint(self.request(first)),
            create_fingerprint(self.request(same_instant)),
        )

    def test_as_of_requires_timezone(self) -> None:
        with self.assertRaises(ValidationError):
            self.request(datetime(2026, 9, 29, 12, 0))  # noqa: DTZ001 - tests rejection

    def test_web_start_date_requires_timezone(self) -> None:
        with self.assertRaises(ValidationError):
            SearchWebInput(query="Apple product", date_from=datetime(2026, 9, 29))  # noqa: DTZ001 - tests rejection

    def test_prefetch_excludes_cutoff_day_and_mutable_snapshot_metrics(self) -> None:
        as_of = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
        context, catalog, sources = _prefetched_financial_context(
            "AAPL",
            as_of,
            {"company_name": "Apple Inc.", "market_cap": 1000000},
            [
                {"Date": "2026-09-28", "Close": 100.0},
                {"Date": "2026-09-29", "Close": 110.0},
            ],
        )
        self.assertNotIn("market_cap", context["company_snapshot"])
        self.assertEqual(len(sources["close_data:AAPL"]), 1)
        self.assertTrue(all(".1." not in item.field_path for item in catalog.values()))

    def test_document_verification_checks_company_and_publication_scope(self) -> None:
        import hashlib

        published = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
        content = "Apple describes a material product execution risk."
        document_id = "00000000-0000-0000-0000-000000000001"
        chunk_id = "00000000-0000-0000-0000-000000000002"
        document = SimpleNamespace(
            reference_id="filing-1",
            document_type=DocumentType.FILING,
            title="Apple filing",
            source_url="https://example.com/filing",
            filter_metadata={"symbol": "AAPL"},
            published_at=published,
        )
        chunk = SimpleNamespace(
            document_id=UUID(document_id),
            document=document,
            chunk_index=0,
            content=content,
        )
        session = cast(Any, SimpleNamespace(get=lambda model, key: chunk))
        evidence = DocumentEvidence(
            evidence_id="doc:one",
            reference_id="filing-1",
            title="Apple filing",
            url="https://example.com/filing",
            retrieved_at=datetime.now(timezone.utc),
            published_at=published,
            document_type=DocumentType.FILING,
            content_quality="full_text",
            document_id=document_id,
            chunk_id=chunk_id,
            chunk_index=0,
            start_char=0,
            end_char=len(content),
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            quote=content,
        )
        self.assertTrue(
            validate_document_evidence(
                session, evidence, symbol="AAPL", as_of=published + timedelta(hours=1)
            )
        )
        self.assertFalse(
            validate_document_evidence(
                session, evidence, symbol="MSFT", as_of=published + timedelta(hours=1)
            )
        )
        self.assertFalse(
            validate_document_evidence(
                session, evidence, symbol="AAPL", as_of=published - timedelta(hours=1)
            )
        )
