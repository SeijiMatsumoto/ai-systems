import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx

from backend.db.schemas import ResearchRunStatus
from backend.research_workflow.api import app
from backend.research_workflow.contracts import (
    ResearchWorkflowResult,
    ResearchWorkflowStep,
)


class ResearchStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_orders_saved_steps_before_result(self) -> None:
        run_id = uuid4()

        async def fake_workflow(request, *, on_step):
            for sequence in (1, 2):
                on_step(
                    ResearchWorkflowStep(
                        run_id=run_id,
                        sequence=sequence,
                        stage="tool",
                        status="completed",
                        summary=f"Tool step {sequence}",
                        details={"arguments": {"query": f"search {sequence}"}},
                        recorded_at=datetime.now(timezone.utc),
                    )
                )
            return ResearchWorkflowResult(
                run_id=run_id, status=ResearchRunStatus.COMPLETED
            )

        payload = {
            "symbol": "AAPL",
            "as_of": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "research_question": "What recent changes could affect this company?",
            "audience": "investors",
            "time_horizon": "12m",
        }
        transport = httpx.ASGITransport(app=app)
        with patch(
            "backend.research_workflow.api.run_research_workflow", fake_workflow
        ):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/agent/research_brief/stream", json=payload
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [line for line in response.text.splitlines() if line.startswith("event:")],
            ["event: step", "event: step", "event: result"],
        )
        self.assertIn(str(run_id), response.text)
        self.assertIn('"query": "search 2"', response.text)

    async def test_stream_reports_failure_after_prior_steps(self) -> None:
        async def fake_workflow(request, *, on_step):
            on_step(
                ResearchWorkflowStep(
                    run_id=uuid4(),
                    sequence=1,
                    stage="classifier",
                    status="running",
                    summary="Classifying request",
                    recorded_at=datetime.now(timezone.utc),
                )
            )
            raise RuntimeError("classifier unavailable")

        payload = {
            "symbol": "AAPL",
            "as_of": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "research_question": "What recent changes could affect this company?",
            "audience": "investors",
            "time_horizon": "12m",
        }
        transport = httpx.ASGITransport(app=app)
        with patch(
            "backend.research_workflow.api.run_research_workflow", fake_workflow
        ):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.post(
                    "/agent/research_brief/stream", json=payload
                )
        self.assertEqual(
            [line for line in response.text.splitlines() if line.startswith("event:")],
            ["event: step", "event: error"],
        )
        self.assertIn("classifier unavailable", response.text)


if __name__ == "__main__":
    unittest.main()
