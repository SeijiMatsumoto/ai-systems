"""Subject memory is context, not evidence or authority to perform an action."""

from .contracts import (
    ContextChange,
    ConversationContext,
    PendingResolution,
    SubjectReference,
)
from .task_resources import saved_policies


def evidence_references(evidence):
    kinds = {"order": "order", "catalog": "product", "case": "case"}
    refs = []
    for item in evidence:
        if item.kind in kinds:
            ref = SubjectReference.model_validate(
                {"kind": kinds[item.kind], "record_id": item.source_id}
            )
            if ref not in refs:
                refs.append(ref)
    return tuple(refs[:10])


def scope_context(context, customer, store, case_lookup):
    def allowed(ref):
        if ref.kind == "order":
            return customer.order(ref.record_id).order is not None
        if ref.kind == "product":
            return store.product(ref.record_id) is not None
        return case_lookup is not None and case_lookup(ref.record_id) is not None

    subjects = tuple(ref for ref in context.subjects if allowed(ref))
    pending = context.pending
    if pending:
        pending = pending.model_copy(
            update={"choices": tuple(ref for ref in pending.choices if allowed(ref))}
        )
    return context.model_copy(update={"subjects": subjects, "pending": pending})


def validate_change(change, catalog, current):
    available = {
        (ref.kind, ref.record_id) for ref in evidence_references(catalog.values())
    }
    references = (*change.subjects, *change.choices)
    if any((ref.kind, ref.record_id) not in available for ref in references):
        raise ValueError("Context selection requires scoped current observations")
    return change


def final_change(change, evidence, reason):
    if reason not in {
        "verified",
        "owned_order_list",
        "proposal_validated",
        "missing_reference",
        "task_abandoned",
        "explicit_confirmation_required",
        "explicit_rejection_required",
    }:
        return None
    if change is not None:
        if reason == "verified" and change.mode == "select":
            available = {
                (ref.kind, ref.record_id) for ref in evidence_references(evidence)
            }
            if any(
                (ref.kind, ref.record_id) not in available for ref in change.subjects
            ):
                raise ValueError(
                    "Answered subjects must be supported by final cited evidence"
                )
        if reason != "missing_reference" and change.choices:
            raise ValueError("Only clarification may record unresolved choices")
        return change
    refs = evidence_references(evidence)
    return ContextChange(mode="select", subjects=refs) if refs else ContextChange()


def commit_context(previous, response):
    if response.context_update is None:
        return previous
    change = response.context_update
    subjects = previous.subjects
    if change.mode == "select":
        subjects = change.subjects
    elif change.mode == "clear":
        subjects = ()
    pending = previous.pending
    if response.stop_reason == "missing_reference":
        pending = PendingResolution(
            question=response.answer[:500],
            choices=change.choices,
            source_run_id=response.run_id,
        )
    elif change.mode in {"select", "clear"}:
        pending = None
    return ConversationContext(
        version=previous.version + 1,
        subjects=subjects,
        pending=pending,
        source_run_id=response.run_id,
        saved_policy=()
        if change.mode == "clear"
        else saved_policies(previous.saved_policy, response),
    )


def compact_context(context):
    return context.model_dump(mode="json", exclude={"saved_policy"})


def conservative_context(rows):
    # Recover only a saved explicit selection; do not infer focus from all fetched records.
    for response in rows:
        if response.context is not None:
            return response.context
        refs = evidence_references(response.evidence)
        if response.disposition == "answered" and len(refs) == 1:
            return ConversationContext(
                subjects=refs,
                source_run_id=response.run_id,
                saved_policy=saved_policies((), response),
            )
        if len(refs) > 1:
            break
    return ConversationContext()
