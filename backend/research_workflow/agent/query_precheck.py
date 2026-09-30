"""Cheap request checks and keyword signals before model classification."""

import re
from datetime import datetime

from backend.research_workflow.contracts import BriefingRequest, ResearchQueryPrecheck

TOPIC_PATTERNS = {
    "financials": re.compile(
        r"\b(revenue|sales|earnings|profit|margin|cash\s+flow|financials?|balance\s+sheet)\b",
        re.IGNORECASE,
    ),
    "markets": re.compile(
        r"\b(stocks?|shares?|price|valuation|investors?|dividends?)\b",
        re.IGNORECASE,
    ),
    "operations": re.compile(
        r"\b(products?|services?|customers?|suppliers?|shipments?|growth|strategy|competition)\b",
        re.IGNORECASE,
    ),
    "risk": re.compile(
        r"\b(risks?|tariffs?|regulat\w*|litigation|guidance|outlook)\b",
        re.IGNORECASE,
    ),
}

INSTRUCTION_PATTERNS = {
    "ignore_prior_instructions": re.compile(
        r"\b(ignore|disregard)\s+(all\s+)?(previous|prior|above)\s+(instructions|rules)\b",
        re.IGNORECASE,
    ),
    "prompt_reference": re.compile(
        r"\b(system|developer)\s+(prompt|message)\b", re.IGNORECASE
    ),
    "role_override": re.compile(r"\b(act\s+as|you\s+are\s+now)\b", re.IGNORECASE),
}


def precheck_research_query(
    request: BriefingRequest, *, now: datetime
) -> ResearchQueryPrecheck:
    """Reject structurally invalid input; send keyword signals to Jev as hints."""
    symbol = request.symbol.strip().upper()
    question = " ".join(request.research_question.split())
    if not symbol:
        raise ValueError("Research symbol must not be blank")
    if request.as_of > now:
        raise ValueError(f"{request.as_of} cannot be after today")
    if len(question) < 30 or not any(character.isalpha() for character in question):
        raise ValueError(
            "Research question must contain at least 30 meaningful characters"
        )

    return ResearchQueryPrecheck(
        symbol=symbol,
        normalized_question=question,
        symbol_mentioned=bool(
            re.search(rf"\b{re.escape(symbol)}\b", question, re.IGNORECASE)
        ),
        topic_matches=[
            name for name, pattern in TOPIC_PATTERNS.items() if pattern.search(question)
        ],
        instruction_pattern_matches=[
            name
            for name, pattern in INSTRUCTION_PATTERNS.items()
            if pattern.search(question)
        ],
    )
