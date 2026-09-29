"""Small transaction-scoped lifecycle helpers for the shared run registry."""

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from backend.db.schemas import LlmRun


SYSTEM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TRACE_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _validate_trace_id(trace_id: str | None) -> None:
    if trace_id is not None and not TRACE_ID_RE.fullmatch(trace_id):
        raise ValueError("Logfire trace ID must be 32 lowercase hexadecimal characters")


def create_run(
    session: Session,
    system_key: str,
    *,
    run_id: uuid.UUID | None = None,
    logfire_trace_id: str | None = None,
) -> LlmRun:
    """Create a pending run; the caller owns the database transaction."""
    if not SYSTEM_KEY_RE.fullmatch(system_key):
        raise ValueError("system key must be 1-64 lowercase letters, digits, or underscores")
    _validate_trace_id(logfire_trace_id)
    run = LlmRun(
        id=run_id or uuid.uuid4(),
        system_key=system_key,
        status="pending",
        logfire_trace_id=logfire_trace_id,
    )
    session.add(run)
    session.flush()
    return run


def _transition(
    session: Session,
    run_id: uuid.UUID,
    *,
    from_statuses: tuple[str, ...],
    to_status: str,
    at: datetime | None = None,
    logfire_trace_id: str | None = None,
) -> LlmRun:
    _validate_trace_id(logfire_trace_id)
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("transition timestamp must be timezone-aware")
    values: dict[str, object] = {"status": to_status}
    if to_status == "running":
        values["started_at"] = now
    else:
        values["finished_at"] = now
    if logfire_trace_id is not None:
        values["logfire_trace_id"] = logfire_trace_id

    result = session.execute(
        update(LlmRun)
        .where(LlmRun.id == run_id, LlmRun.status.in_(from_statuses))
        .values(**values)
    )
    if result.rowcount != 1:
        if session.get(LlmRun, run_id) is None:
            raise ValueError("run ID does not exist")
        raise ValueError("invalid run status transition")
    session.flush()
    run = session.get(LlmRun, run_id)
    if run is None:
        raise RuntimeError("run disappeared after transition")
    session.refresh(run)
    return run


def start_run(
    session: Session, run_id: uuid.UUID, *, logfire_trace_id: str | None = None
) -> LlmRun:
    return _transition(
        session, run_id, from_statuses=("pending",), to_status="running",
        logfire_trace_id=logfire_trace_id,
    )


def complete_run(session: Session, run_id: uuid.UUID) -> LlmRun:
    return _transition(
        session, run_id, from_statuses=("running",), to_status="completed"
    )


def fail_run(
    session: Session, run_id: uuid.UUID, *, logfire_trace_id: str | None = None
) -> LlmRun:
    return _transition(
        session, run_id, from_statuses=("pending", "running"), to_status="failed",
        logfire_trace_id=logfire_trace_id,
    )
