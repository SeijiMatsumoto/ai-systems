"""Persist ordered public research workflow steps before streaming them."""

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID

from pydantic_core import to_jsonable_python

from backend.db import db_utils, schemas
from backend.research_workflow.contracts import (
    ResearchStepStage,
    ResearchStepStatus,
    ResearchWorkflowStep,
)

StepCallback = Callable[[ResearchWorkflowStep], None]


class ResearchRunRecorder:
    def __init__(
        self,
        run_id: UUID,
        *,
        on_step: StepCallback | None = None,
    ) -> None:
        self.run_id = run_id
        self.on_step = on_step
        self._sequence = 0
        self._lock = threading.Lock()

    def emit(
        self,
        stage: ResearchStepStage,
        status: ResearchStepStatus,
        summary: str,
        details: dict[str, object] | None = None,
    ) -> ResearchWorkflowStep:
        with self._lock:
            self._sequence += 1
            step = ResearchWorkflowStep(
                run_id=self.run_id,
                sequence=self._sequence,
                stage=stage,
                status=status,
                summary=summary,
                details=to_jsonable_python(details or {}),
                recorded_at=datetime.now(timezone.utc),
            )
            with db_utils.get_session() as session:
                session.add(
                    schemas.ResearchRunStep(
                        run_id=self.run_id,
                        sequence=step.sequence,
                        payload=step.model_dump(mode="json"),
                    )
                )
        if self.on_step is not None:
            self.on_step(step)
        return step


def saved_steps(run_id: UUID) -> list[ResearchWorkflowStep]:
    with db_utils.get_session() as session:
        rows = (
            session.query(schemas.ResearchRunStep)
            .filter(schemas.ResearchRunStep.run_id == run_id)
            .order_by(schemas.ResearchRunStep.sequence)
            .all()
        )
        return [ResearchWorkflowStep.model_validate(row.payload) for row in rows]
