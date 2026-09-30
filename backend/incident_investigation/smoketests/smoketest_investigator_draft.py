"""One real investigator model call: draft from pinned prior tool results."""

import asyncio

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import Model

from backend.incident_investigation.agent import InvestigationDraft
from backend.incident_investigation.smoketests._common import (
    checkout_context,
    emit,
    one_investigator_response,
    require_key,
)
from backend.incident_investigation.verification import verify_report

EVIDENCE = {
    "search_logs": ["logs-0115", "logs-0133"],
    "get_metric_series": ["metrics-0407"],
    "list_changes": ["changes-0002"],
}
TOOL_INPUTS = {
    "search_logs": {
        "service": "checkout",
        "start": "2026-04-14T14:00:00Z",
        "end": "2026-04-14T14:19:18Z",
        "level": "ERROR",
        "limit": 10,
    },
    "get_metric_series": {
        "service": "checkout",
        "metric": "error_rate",
        "start": "2026-04-14T14:00:00Z",
        "end": "2026-04-14T14:19:18Z",
    },
    "list_changes": {
        "service": "payments",
        "start": "2026-04-14T14:00:00Z",
        "end": "2026-04-14T14:19:18Z",
    },
}


async def check(model: Model | str | None = None) -> None:
    prompt, deps, store = checkout_context()
    records = {
        item.evidence_id: item for item in [*store.logs, *store.metrics, *store.changes]
    }
    history = [ModelRequest(parts=[UserPromptPart(content=prompt)])]
    for index, (tool_name, evidence_ids) in enumerate(EVIDENCE.items(), 1):
        expected_service = TOOL_INPUTS[tool_name]["service"]
        for evidence_id in evidence_ids:
            record = records[evidence_id]
            if record.service != expected_service:
                raise AssertionError(
                    f"{evidence_id} is {record.service}, expected {expected_service}"
                )
            if (
                tool_name == "get_metric_series"
                and record.metric != TOOL_INPUTS[tool_name]["metric"]
            ):
                raise AssertionError(f"{evidence_id} has the wrong metric")
        call_id = f"smoke-tool-{index}"
        history.extend(
            [
                ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name=tool_name,
                            args=TOOL_INPUTS[tool_name],
                            tool_call_id=call_id,
                        )
                    ]
                ),
                ModelRequest(
                    parts=[
                        ToolReturnPart(
                            tool_name=tool_name,
                            content={
                                "records": [
                                    records[evidence_id].model_dump(mode="json")
                                    for evidence_id in evidence_ids
                                ],
                                "truncated": False,
                                "coverage_gaps": [],
                            },
                            tool_call_id=call_id,
                        )
                    ]
                ),
            ]
        )
    response, usage, trace_id = await one_investigator_response(
        "The fixture tool results above are sufficient for this smoke check. "
        "Draft a cautious report now with citations from those results.",
        deps,
        message_history=history,
        model=model,
    )
    drafts = [
        part
        for part in response.parts
        if isinstance(part, ToolCallPart) and part.tool_name == "final_result"
    ]
    if len(drafts) != 1:
        raise AssertionError("expected one final_result draft, not another tool query")
    draft = InvestigationDraft.model_validate(drafts[0].args_as_dict())
    cited = {
        evidence_id
        for claim in [*draft.observations, *draft.candidate_causes]
        for evidence_id in claim.evidence_ids
    }
    allowed = {evidence_id for ids in EVIDENCE.values() for evidence_id in ids}
    if not draft.observations or not cited or not cited <= allowed:
        raise AssertionError(
            "draft lacks observations or cites evidence outside prior results"
        )
    _, verification = verify_report(
        draft, store=store, scope=deps.scope, surfaced_evidence_ids=allowed
    )
    if not verification.passed:
        raise AssertionError(f"draft failed citation checks: {verification.issues}")
    emit(
        {
            "input": "checkout_trigger.json and pinned search_logs, metric, change results",
            "expected": "one cited InvestigationDraft",
            "draft": draft.model_dump(mode="json"),
            "verification_passed": verification.passed,
            "usage": usage,
            "trace_id": trace_id,
        }
    )


if __name__ == "__main__":
    require_key("OPENAI_API_KEY")
    asyncio.run(check())
