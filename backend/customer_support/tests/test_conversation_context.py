"""Persistent focus is independently checked and never substitutes for current evidence."""

import unittest

from backend.customer_support.contracts import (
    ContextChange,
    ConversationContext,
    Evidence,
    PendingResolution,
    SubjectReference,
    SupportResponse,
)
from backend.customer_support.conversation_context import (
    commit_context,
    conservative_context,
    final_change,
    validate_change,
)


def ref(number):
    return SubjectReference(kind="order", record_id=f"order-{number}")


def evidence(number):
    return Evidence(
        evidence_id=f"S{number}",
        kind="order",
        source_id=f"order-{number}",
        locator="fixture",
        text="Scoped observation",
    )


def response(**values):
    return SupportResponse(
        run_id="run-new",
        conversation_id="chat",
        disposition="answered",
        answer="Answer",
        stop_reason="verified",
        fixture_version="fixture",
        **values,
    )


class ContextTests(unittest.TestCase):
    def test_unobserved_subject_and_final_uncited_subject_are_rejected(self):
        change = ContextChange(mode="select", subjects=(ref(2),))
        with self.assertRaises(ValueError):
            validate_change(change, {"S1": evidence(1)}, ConversationContext())
        with self.assertRaises(ValueError):
            final_change(change, (evidence(1),), "verified")

    def test_ordered_choices_survive_general_policy_answer_then_selection_clears(self):
        previous = ConversationContext(subjects=(ref(1), ref(2)))
        clarification = response(
            context_update=ContextChange(choices=(ref(2), ref(1)))
        ).model_copy(
            update={
                "disposition": "clarification",
                "stop_reason": "missing_reference",
                "answer": "Which order?",
            }
        )
        pending = commit_context(previous, clarification)
        assert pending.pending is not None
        self.assertEqual(pending.pending.choices, (ref(2), ref(1)))
        unchanged = commit_context(pending, response(context_update=ContextChange()))
        self.assertEqual(unchanged.pending, pending.pending)
        selected = commit_context(
            unchanged,
            response(context_update=ContextChange(mode="select", subjects=(ref(1),))),
        )
        self.assertIsNone(selected.pending)
        self.assertEqual(selected.subjects, (ref(1),))

    def test_failure_preserves_context_and_version(self):
        previous = ConversationContext(
            subjects=(ref(1),),
            pending=PendingResolution(question="Which?", choices=(ref(1), ref(2))),
        )
        self.assertEqual(commit_context(previous, response()), previous)
        self.assertIsNone(
            final_change(ContextChange(mode="clear"), (), "model_unavailable")
        )

    def test_legacy_recovery_does_not_choose_last_order_in_list(self):
        self.assertEqual(
            conservative_context(
                [response(evidence=(evidence(1), evidence(2)))]
            ).subjects,
            (),
        )
        self.assertEqual(
            conservative_context([response(evidence=(evidence(1),))]).subjects,
            (ref(1),),
        )

    def test_policy_only_output_preserves_subject(self):
        previous = ConversationContext(subjects=(ref(1),))
        changed = commit_context(
            previous, response(context_update=final_change(None, (), "verified"))
        )
        self.assertEqual(changed.subjects, previous.subjects)
        self.assertEqual(changed.version, previous.version + 1)

    def test_clear_discards_pending_choices(self):
        previous = ConversationContext(
            subjects=(ref(1),),
            pending=PendingResolution(question="Which?", choices=(ref(1),)),
        )
        cleared = commit_context(
            previous, response(context_update=ContextChange(mode="clear"))
        )
        self.assertEqual(cleared.subjects, ())
        self.assertIsNone(cleared.pending)
