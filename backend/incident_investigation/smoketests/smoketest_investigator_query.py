"""One real investigator model call: choose a scoped telemetry query."""

import asyncio

from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model

from backend.incident_investigation.agent import (
    InspectTraceInput,
    ListChangesInput,
    MetricSeriesInput,
    SearchLogsInput,
)
from backend.incident_investigation.smoketests._common import (
    checkout_context,
    emit,
    one_investigator_response,
    require_key,
)

INPUT_TYPES = {
    "search_logs": SearchLogsInput,
    "get_metric_series": MetricSeriesInput,
    "inspect_trace": InspectTraceInput,
    "list_changes": ListChangesInput,
}


async def check(model: Model | str | None = None) -> None:
    prompt, deps, _ = checkout_context()
    response, usage, trace_id = await one_investigator_response(
        prompt, deps, model=model
    )
    calls = [part for part in response.parts if isinstance(part, ToolCallPart)]
    if len(calls) != 1 or calls[0].tool_name not in INPUT_TYPES:
        raise AssertionError("expected exactly one scoped telemetry tool choice")
    call = calls[0]
    validated = INPUT_TYPES[call.tool_name].model_validate(call.args_as_dict())
    arguments = validated.model_dump(mode="json")
    if (
        "service" in arguments
        and arguments["service"] not in deps.scope.allowed_services
    ):
        raise AssertionError("model selected a service outside the investigation scope")
    if "start" in arguments and (
        validated.start < deps.scope.start or validated.end > deps.scope.end
    ):
        raise AssertionError(
            "model selected a time window outside the investigation scope"
        )
    emit(
        {
            "input": "checkout_trigger.json and trigger-time telemetry snapshot",
            "expected": "one scoped telemetry tool call",
            "tool_name": call.tool_name,
            "arguments": arguments,
            "usage": usage,
            "trace_id": trace_id,
        }
    )


if __name__ == "__main__":
    require_key("OPENAI_API_KEY")
    asyncio.run(check())
