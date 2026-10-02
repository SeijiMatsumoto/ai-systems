"""Intent thresholds affect action authority; subject resolution belongs to the agent."""

from .contracts import Intent

INTENT_THRESHOLD = 0.8
INTENT_MARGIN = 0.1


def intent_branch(judgment):
    confident = judgment.probability >= INTENT_THRESHOLD and (
        judgment.confidence_gap is None or judgment.confidence_gap >= INTENT_MARGIN
    )
    if judgment.intent == Intent.INFORMATION:
        return "read_only"
    if judgment.intent == Intent.ACTION:
        return "proposal" if confident else "read_only"
    if judgment.intent == Intent.HUMAN:
        return "human_review" if confident else "clarify"
    return "unsupported" if confident else "clarify"
