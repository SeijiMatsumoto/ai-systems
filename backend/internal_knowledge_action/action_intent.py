"""Cheap deterministic action signals followed by bounded Jev intent classification."""

import asyncio
import re
from typing import Protocol

from typesafe_sdk import AsyncTypeSafeClient, Noul

from backend.internal_knowledge_action.contracts import ActionIntentJudgment

JEV_MODEL = "jev-latest"
TIMEOUT_SECONDS = 10
ACTION_THRESHOLD = 0.8
ACTION_SIGNALS = {
    "create": re.compile(r"\b(create|make|open|file|submit)\b", re.IGNORECASE),
    "assign": re.compile(r"\b(assign|route|hand off)\b", re.IGNORECASE),
    "message": re.compile(r"\b(send|email|notify|message)\b", re.IGNORECASE),
    "change": re.compile(r"\b(update|change|delete|close|cancel)\b", re.IGNORECASE),
}


def detect_action_signals(text: str) -> list[str]:
    return [name for name, pattern in ACTION_SIGNALS.items() if pattern.search(text)]


class ActionIntentProvider(Protocol):
    model_id: str

    async def classify(
        self, question: str, signals: list[str]
    ) -> ActionIntentJudgment: ...


class LiveJevActionIntentProvider:
    model_id = JEV_MODEL

    async def classify(self, question: str, signals: list[str]) -> ActionIntentJudgment:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            async with AsyncTypeSafeClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.system_one(
                    model=JEV_MODEL,
                    state={
                        "request": question,
                        "deterministic_action_signals": signals,
                    },
                    questions={
                        "explicit_action": Noul(
                            instructions=(
                                "Does the user ask the assistant to perform a concrete action now, "
                                "rather than ask how an action works or discuss it hypothetically?"
                            ),
                            criteria={
                                "true": "A concrete action is explicitly requested now.",
                                "false": "It is an informational, hypothetical, or ambiguous question.",
                            },
                        )
                    },
                )
        return ActionIntentJudgment(
            model=response.model,
            probability=response.nouls["explicit_action"].noul,
            usage=response.usage.model_dump(),
        )
