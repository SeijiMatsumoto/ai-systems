import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.llm_runs import complete_run, create_run, fail_run, start_run
from backend.db.schemas import LlmRun


class LlmRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        LlmRun.__table__.create(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_shared_run_identity_and_lifecycle(self) -> None:
        incident = create_run(self.session, "incident_investigation")
        existing_research_id = uuid4()
        research = create_run(self.session, "research_workflow", run_id=existing_research_id)
        self.assertNotEqual(incident.id, research.id)
        self.assertEqual(research.id, existing_research_id)
        self.assertEqual(incident.status, "pending")
        self.assertIsNone(incident.started_at)

        started = start_run(self.session, incident.id, logfire_trace_id="a" * 32)
        self.assertEqual(started.status, "running")
        self.assertEqual(started.logfire_trace_id, "a" * 32)
        self.assertIsNotNone(started.started_at)
        self.assertIsNone(started.finished_at)

        completed = complete_run(self.session, incident.id)
        self.assertEqual(completed.status, "completed")
        self.assertIsNotNone(completed.finished_at)
        with self.assertRaisesRegex(ValueError, "invalid run status transition"):
            fail_run(self.session, incident.id)
        self.session.commit()

        with Session(self.engine) as other_session:
            stored = other_session.get(LlmRun, incident.id)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.system_key, "incident_investigation")
            self.assertEqual(stored.status, "completed")
            self.assertEqual(stored.logfire_trace_id, "a" * 32)

    def test_failure_can_end_pending_or_running_run(self) -> None:
        pending = create_run(self.session, "incident_investigation")
        failed_pending = fail_run(self.session, pending.id)
        self.assertEqual(failed_pending.status, "failed")
        self.assertIsNone(failed_pending.started_at)
        self.assertIsNotNone(failed_pending.finished_at)

        running = create_run(self.session, "incident_investigation")
        start_run(self.session, running.id)
        failed_running = fail_run(self.session, running.id)
        self.assertEqual(failed_running.status, "failed")
        self.assertIsNotNone(failed_running.started_at)

    def test_invalid_transitions_and_identifiers_are_rejected(self) -> None:
        run = create_run(self.session, "incident_investigation")
        with self.assertRaisesRegex(ValueError, "invalid run status transition"):
            complete_run(self.session, run.id)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            start_run(self.session, uuid4())
        with self.assertRaisesRegex(ValueError, "system key"):
            create_run(self.session, "Incident Investigation")
        with self.assertRaisesRegex(ValueError, "Logfire trace ID"):
            start_run(self.session, run.id, logfire_trace_id="not-a-trace")
        self.assertEqual(self.session.get(LlmRun, run.id).status, "pending")


if __name__ == "__main__":
    unittest.main()
