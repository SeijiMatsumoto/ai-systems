import unittest

from pydantic import ValidationError

from backend.research_workflow.agent.classifiers import (
    FindingRevision,
)


class FindingRevisionTests(unittest.TestCase):
    def test_revision_requires_all_finding_fields(self) -> None:
        with self.assertRaises(ValidationError):
            FindingRevision(action="revise")

    def test_duplicate_drop_omits_revision_fields(self) -> None:
        revision = FindingRevision(action="drop_duplicate")

        self.assertIsNone(revision.statement)
        self.assertIsNone(revision.claim_type)
        self.assertIsNone(revision.confidence)

    def test_duplicate_drop_rejects_revised_statement(self) -> None:
        with self.assertRaises(ValidationError):
            FindingRevision(
                action="drop_duplicate",
                statement="A redundant finding.",
            )


if __name__ == "__main__":
    unittest.main()
