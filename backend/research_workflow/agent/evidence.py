import hashlib
import re
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from pydantic import TypeAdapter

from backend.db.schemas import DocumentType
from backend.research_workflow.contracts import (
    DocumentEvidence,
    DraftResearchBriefing,
    EvidenceRecord,
    FinancialEvidence,
    Finding,
    ResearchBriefing,
    ScalarValue,
)
from backend.shared.article_processing import (
    MIN_ARTICLE_TEXT_CHARS,
    looks_like_article_boilerplate,
    story_key,
)

EVIDENCE_RECORD_ADAPTER = TypeAdapter(EvidenceRecord)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
PARAGRAPH_PATTERN = re.compile(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", re.DOTALL)
SENTENCE_PATTERN = re.compile(r"\S(?:.*?\S)?(?:[.!?](?=\s|\Z)|\Z)", re.DOTALL)
SCRUBBED_PATTERN = re.compile(r"^\[scrubbed due to .+\]$", re.IGNORECASE)
PAGE_HEADER_PATTERN = re.compile(
    r"^[\w .,&'-]+\|.*form\s+(?:10-[kq]|8-k).*\|\s*\d+$",
    re.IGNORECASE,
)


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _split_long_passage(
    text: str, offset: int, max_chars: int
) -> Iterator[tuple[int, int, str]]:
    sentences = list(SENTENCE_PATTERN.finditer(text))
    if not sentences:
        for start in range(0, len(text), max_chars):
            end = min(start + max_chars, len(text))
            yield offset + start, offset + end, text[start:end]
        return

    window_start = sentences[0].start()
    window_end = sentences[0].end()
    for sentence in sentences[1:]:
        if sentence.end() - window_start <= max_chars:
            window_end = sentence.end()
            continue
        yield offset + window_start, offset + window_end, text[window_start:window_end]
        window_start = sentence.start()
        window_end = sentence.end()
    yield offset + window_start, offset + window_end, text[window_start:window_end]


def split_passages(text: str, max_chars: int = 1_200) -> list[tuple[int, int, str]]:
    """Split source text without rewriting it, retaining exact character offsets."""
    passages: list[tuple[int, int, str]] = []
    for paragraph in PARAGRAPH_PATTERN.finditer(text):
        start, end = paragraph.span()
        if end - start <= max_chars:
            passages.append((start, end, text[start:end]))
        else:
            passages.extend(_split_long_passage(text[start:end], start, max_chars))
    return passages or [(0, len(text), text)]


def _relevance_score(
    query: str, passage: str, retrieval_similarity: float
) -> tuple[int, float, int]:
    query_terms = {
        token.lower() for token in TOKEN_PATTERN.findall(query) if len(token) > 2
    }
    passage_terms = {token.lower() for token in TOKEN_PATTERN.findall(passage)}
    return (
        len(query_terms & passage_terms),
        retrieval_similarity,
        min(len(passage), 1_200),
    )


def _is_usable_passage(passage: str, document_type: DocumentType) -> bool:
    normalized = " ".join(passage.split())
    minimum_length = 24 if document_type == DocumentType.ARTICLE else 80
    minimum_tokens = 4 if document_type == DocumentType.ARTICLE else 8
    if len(normalized) < minimum_length:
        return False
    if SCRUBBED_PATTERN.fullmatch(normalized):
        return False
    if PAGE_HEADER_PATTERN.fullmatch(normalized):
        return False
    if document_type == DocumentType.ARTICLE and looks_like_article_boilerplate(
        passage
    ):
        return False
    return len(TOKEN_PATTERN.findall(normalized)) >= minimum_tokens


def build_document_evidence_candidates(
    query: str,
    retrieved_chunks: Sequence[Mapping[str, Any]],
    max_candidates: int = 3,
    require_term_overlap: bool = False,
) -> list[DocumentEvidence]:
    retrieved_at = datetime.now(timezone.utc)
    ranked_passages: list[
        tuple[
            tuple[int, float, int],
            Mapping[str, Any],
            DocumentType,
            str,
            int,
            int,
            str,
        ]
    ] = []
    for row in retrieved_chunks:
        content = str(row["content"])
        if not content.strip():
            continue
        document_type = DocumentType(str(row["document_type"]))
        if (
            document_type == DocumentType.ARTICLE
            and row.get("content_quality") != "full_text"
            and len(content.strip()) < MIN_ARTICLE_TEXT_CHARS
        ):
            continue
        retrieval_similarity = float(row.get("similarity", 0.0))
        for start_char, end_char, quote in split_passages(content):
            if not _is_usable_passage(quote, document_type):
                continue
            ranked_passages.append(
                (
                    _relevance_score(query, quote, retrieval_similarity),
                    row,
                    document_type,
                    content,
                    start_char,
                    end_char,
                    quote,
                )
            )

    candidates: list[DocumentEvidence] = []
    seen_article_stories: set[str] = set()
    for (
        relevance_score,
        row,
        document_type,
        content,
        start_char,
        end_char,
        quote,
    ) in sorted(ranked_passages, key=lambda item: item[0], reverse=True):
        if require_term_overlap and relevance_score[0] == 0:
            continue
        if document_type == DocumentType.ARTICLE:
            normalized_story_key = story_key(str(row["title"]))
            if normalized_story_key in seen_article_stories:
                continue
            seen_article_stories.add(normalized_story_key)
        raw_content_quality = row.get("content_quality")
        content_quality = (
            raw_content_quality
            if raw_content_quality in {"full_text", "snippet"}
            else ("snippet" if document_type == DocumentType.ARTICLE else "full_text")
        )
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        evidence_id = _stable_id(
            "doc", row["chunk_id"], start_char, end_char, content_hash
        )
        candidates.append(
            DocumentEvidence(
                evidence_id=evidence_id,
                reference_id=str(row["reference_id"]),
                title=str(row["title"]),
                url=str(row["source_url"]) if row.get("source_url") else None,
                retrieved_at=retrieved_at,
                published_at=row.get("published_at"),
                document_type=document_type,
                content_quality=content_quality,
                document_id=str(row["document_id"]),
                chunk_id=str(row["chunk_id"]),
                chunk_index=int(row["chunk_index"]),
                start_char=start_char,
                end_char=end_char,
                content_hash=content_hash,
                quote=quote,
            )
        )
        if len(candidates) == max_candidates:
            break
    return candidates


def _walk_scalar_values(
    value: object, path: str = ""
) -> Iterator[tuple[str, ScalarValue]]:
    if isinstance(value, Mapping):
        for key, nested_value in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from _walk_scalar_values(nested_value, child_path)
        return
    if isinstance(value, list):
        for index, nested_value in enumerate(value):
            child_path = f"{path}.{index}" if path else str(index)
            yield from _walk_scalar_values(nested_value, child_path)
        return
    if value is None or isinstance(value, (str, int, float, bool)):
        yield path, value


def build_financial_evidence_candidates(
    *,
    reference_id: str,
    title: str,
    source: str,
    data: object,
    url: str | None = None,
    path_prefix: str = "",
) -> list[FinancialEvidence]:
    retrieved_at = datetime.now(timezone.utc)
    candidates = []
    for field_path, value in _walk_scalar_values(data, path_prefix):
        candidates.append(
            FinancialEvidence(
                evidence_id=_stable_id("fin", reference_id, field_path),
                reference_id=reference_id,
                title=title,
                url=url,
                retrieved_at=retrieved_at,
                source=source,
                field_path=field_path,
                value=value,
            )
        )
    return candidates


def catalog_from_candidates(
    candidates: Sequence[EvidenceRecord],
) -> dict[str, EvidenceRecord]:
    return {candidate.evidence_id: candidate for candidate in candidates}


def compact_document_evidence(candidate: DocumentEvidence) -> dict[str, object]:
    """Return only fields the model needs to evaluate and select a passage."""
    return {
        "evidence_id": candidate.evidence_id,
        "title": candidate.title,
        "document_type": candidate.document_type.value,
        "content_quality": candidate.content_quality,
        "published_at": (
            candidate.published_at.isoformat() if candidate.published_at else None
        ),
        "quote": candidate.quote,
    }


def compact_financial_evidence(candidate: FinancialEvidence) -> dict[str, object]:
    """Return a compact financial value while keeping provenance server-side."""
    compact: dict[str, object] = {
        "evidence_id": candidate.evidence_id,
        "field_path": candidate.field_path,
        "value": candidate.value,
    }
    if candidate.period_end is not None:
        compact["period_end"] = candidate.period_end
    return compact


def load_evidence_catalog(payload: object) -> dict[str, EvidenceRecord]:
    if not isinstance(payload, list):
        raise TypeError("Checkpoint evidence catalog is missing or invalid")
    records = [EVIDENCE_RECORD_ADAPTER.validate_python(item) for item in payload]
    return catalog_from_candidates(records)


def hydrate_briefing(
    draft: DraftResearchBriefing,
    catalog: Mapping[str, EvidenceRecord],
) -> tuple[ResearchBriefing, list[str]]:
    invalid_ids: list[str] = []
    findings: list[Finding] = []
    for draft_finding in draft.key_findings:
        evidence = []
        for evidence_id in dict.fromkeys(draft_finding.evidence_ids):
            record = catalog.get(evidence_id)
            if record is None:
                invalid_ids.append(evidence_id)
            else:
                evidence.append(record)
        findings.append(
            Finding(
                statement=draft_finding.statement,
                claim_type=draft_finding.claim_type,
                confidence=draft_finding.confidence,
                evidence=evidence,
            )
        )
    return (
        ResearchBriefing(
            executive_summary=draft.executive_summary,
            key_findings=findings,
            outlook=draft.outlook,
            limitations=draft.limitations,
        ),
        invalid_ids,
    )
