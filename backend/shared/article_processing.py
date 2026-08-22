import hashlib
import re
import unicodedata

ARTICLE_CLEANING_VERSION = "v1"
MIN_ARTICLE_TEXT_CHARS = 600

TITLE_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
INLINE_RELATED_LINK_PATTERN = re.compile(
    r"\s+(?:ALSO READ|READ MORE):.*\Z",
    re.IGNORECASE | re.DOTALL,
)
END_MARKERS = (
    "for comments and feedback",
    "related news",
    "latest updates",
    "editor's pick",
    "editors pick",
    "most emailed",
    "view more videos",
    "copyright ",
    "about us",
)
LEADING_METADATA_PATTERNS = (
    re.compile(r"^by .+", re.IGNORECASE),
    re.compile(r"^\|?\s*published:", re.IGNORECASE),
    re.compile(r"^add\s*as your preferred news source", re.IGNORECASE),
)
BOILERPLATE_TERMS = {
    "breaking news",
    "conference calls",
    "content licensing",
    "economic calendar",
    "earnings calendar",
    "industry news",
    "latest headlines",
    "press releases",
    "stock alerts",
    "top stories",
}


def story_key(title: str) -> str:
    """Normalize a headline for deterministic syndicated-story deduplication."""
    normalized = unicodedata.normalize("NFKD", title).lower()
    return " ".join(TITLE_TOKEN_PATTERN.findall(normalized))


def story_fingerprint(title: str) -> str:
    return hashlib.sha256(story_key(title).encode()).hexdigest()


def _is_substantive_line(line: str) -> bool:
    return len(line) >= 80 and len(line.split()) >= 12


def _starts_with_marker(line: str, markers: tuple[str, ...]) -> bool:
    normalized = line.casefold().strip()
    return any(normalized.startswith(marker) for marker in markers)


def looks_like_article_boilerplate(text: str) -> bool:
    """Detect navigation/headline collections that should not become evidence."""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    if not lines:
        return True

    normalized_lines = [line.casefold() for line in lines]
    marker_count = sum(line in BOILERPLATE_TERMS for line in normalized_lines)
    short_line_count = sum(len(line) < 80 for line in lines)
    return len(lines) >= 5 and (
        marker_count >= 2 or short_line_count / len(lines) >= 0.75
    )


def clean_article_text(title: str, text: str) -> str:
    """Extract a conservative article body without rewriting source language."""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    title_key = story_key(title)
    title_index = next(
        (index for index, line in enumerate(lines) if story_key(line) == title_key),
        None,
    )
    start_index = title_index + 1 if title_index is not None else 0

    if title_index is not None or looks_like_article_boilerplate(
        "\n".join(lines[: min(len(lines), 40)])
    ):
        substantive_index = next(
            (
                index
                for index in range(start_index, len(lines))
                if _is_substantive_line(lines[index])
            ),
            start_index,
        )
        start_index = substantive_index

    body_lines: list[str] = []
    for line in lines[start_index:]:
        if body_lines and _starts_with_marker(line, END_MARKERS):
            break
        if not body_lines and any(
            pattern.match(line) for pattern in LEADING_METADATA_PATTERNS
        ):
            continue
        if line.casefold() in BOILERPLATE_TERMS:
            continue
        if body_lines and len(line) < 40 and not line.endswith((".", "!", "?")):
            continue
        body_lines.append(line)

    cleaned = "\n\n".join(body_lines).strip()
    return INLINE_RELATED_LINK_PATTERN.sub("", cleaned).strip()
