import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from backend.project_02_research_briefing_system.agent.models import BriefingRequest
from backend.project_02_research_briefing_system.service.research import (
    create_fingerprint,
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
            self.request(datetime(2026, 9, 29, 12, 0))
