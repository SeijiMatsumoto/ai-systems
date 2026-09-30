import asyncio
import json
from datetime import date
from typing import Literal
from uuid import UUID

import logfire
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.db import db_utils
from backend.db.schemas import ResearchRun, ResearchRunStep
from backend.research_workflow.contracts import BriefingRequest, ResearchWorkflowStep
from backend.research_workflow.data.filings import ingest_filings
from backend.research_workflow.service.ingestion import (
    backfill_company_data,
)
from backend.research_workflow.service.research import (
    run_research_workflow,
)

app = FastAPI()
BACKGROUND_RESEARCH_TASKS: set[asyncio.Task[None]] = set()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logfire.instrument_fastapi(app)


@app.post("/agent/research_brief")
async def run_agent(request: BriefingRequest):
    try:
        return await run_research_workflow(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504, detail="Research workflow timed out"
        ) from exc


@app.post("/agent/research_brief/stream")
async def stream_agent(request: BriefingRequest):
    """Stream steps after each is saved; execution continues if the client leaves."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def on_step(step: ResearchWorkflowStep) -> None:
        item = ("step", step.model_dump(mode="json"))
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is loop:
            queue.put_nowait(item)
        else:
            asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()

    async def execute() -> None:
        try:
            result = await run_research_workflow(request, on_step=on_step)
            await queue.put(("result", result.model_dump(mode="json")))
        except Exception as exc:  # noqa: BLE001 - return workflow failures as SSE
            await queue.put(
                ("error", {"type": type(exc).__name__, "message": str(exc)})
            )

    task = asyncio.create_task(execute())
    BACKGROUND_RESEARCH_TASKS.add(task)
    task.add_done_callback(BACKGROUND_RESEARCH_TASKS.discard)

    async def events():
        while True:
            event, payload = await queue.get()
            yield f"event: {event}\ndata: {json.dumps(payload)}\n\n"
            if event in {"result", "error"}:
                break

    return StreamingResponse(events(), media_type="text/event-stream")


def get_research_run_detail(run_id: UUID) -> dict[str, object]:
    with db_utils.get_session() as session:
        research_run = session.get(ResearchRun, run_id)
        if research_run is None:
            raise HTTPException(status_code=404, detail="Research run not found")

        return {
            "run_id": research_run.id,
            "resumed_from_run_id": research_run.resumed_from_run_id,
            "symbol": research_run.symbol,
            "as_of": research_run.as_of,
            "status": research_run.status,
            "request_payload": research_run.request_payload,
            "briefing_payload": research_run.briefing_payload,
            "verification_payload": research_run.verification_payload,
            "usage_payload": research_run.usage_payload,
            "error_payload": research_run.error_payload,
            "checkpoint_stage": research_run.checkpoint_stage,
            "checkpoint_payload": research_run.checkpoint_payload,
            "trace_id": research_run.trace_id,
            "model_name": research_run.model_name,
            "prompt_version": research_run.prompt_version,
            "tool_version": research_run.tool_version,
            "schema_version": research_run.schema_version,
            "created_at": research_run.created_at,
            "started_at": research_run.started_at,
            "completed_at": research_run.completed_at,
            "workflow_steps": [
                row.payload
                for row in session.query(ResearchRunStep)
                .filter(ResearchRunStep.run_id == run_id)
                .order_by(ResearchRunStep.sequence)
                .all()
            ],
        }


@app.get("/research-runs/{run_id}")
async def get_research_run(run_id: UUID):
    return await asyncio.to_thread(get_research_run_detail, run_id)


def list_research_run_summaries(
    symbol: str | None,
    limit: int,
) -> list[dict[str, object]]:
    with db_utils.get_session() as session:
        query = session.query(ResearchRun)
        if symbol:
            query = query.filter(ResearchRun.symbol == symbol.strip().upper())

        research_runs = query.order_by(ResearchRun.created_at.desc()).limit(limit).all()
        return [
            {
                "run_id": research_run.id,
                "symbol": research_run.symbol,
                "status": research_run.status,
                "research_question": research_run.request_payload.get(
                    "research_question", ""
                ),
                "approval_ready": (
                    research_run.verification_payload.get("approval_ready")
                    if research_run.verification_payload
                    else None
                ),
                "created_at": research_run.created_at,
                "completed_at": research_run.completed_at,
            }
            for research_run in research_runs
        ]


@app.get("/research-runs")
async def list_research_runs(
    symbol: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
):
    return await asyncio.to_thread(list_research_run_summaries, symbol, limit)


class FilingIngestionRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    form_type: Literal["10-K", "10-Q", "8-K"] = "10-K"
    start_date: date | None = None
    end_date: date | None = None
    limit: int = Field(default=1, ge=1, le=10)


@app.post("/ingestion/filings", status_code=201)
async def ingest_company_filings(request: FilingIngestionRequest):
    documents = await asyncio.to_thread(
        ingest_filings,
        symbol=request.symbol.strip().upper(),
        form_type=request.form_type,
        start_date=request.start_date,
        end_date=request.end_date,
        limit=request.limit,
    )

    return {
        "symbol": request.symbol.strip().upper(),
        "form_type": request.form_type,
        "documents_ingested": len(documents),
    }


class CompanyBackfillRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=10)
    as_of: date
    include_8k: bool = True


@app.post("/ingestion/company-backfill")
async def backfill_company(request: CompanyBackfillRequest):
    return await backfill_company_data(
        symbol=request.symbol,
        as_of=request.as_of,
        include_8k=request.include_8k,
    )
