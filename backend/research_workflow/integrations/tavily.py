"""Bounded Tavily discovery and extraction for the research agent."""

import hashlib
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from backend.research_workflow.contracts import ExtractedWebPage, WebSearchResult

API_BASE = "https://api.tavily.com"
MAX_EXTRACT_CHARS = 100_000


def _request(endpoint: str, payload: dict[str, object]) -> dict[str, Any]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY is not configured")
    try:
        response = requests.post(
            f"{API_BASE}/{endpoint}",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Tavily {endpoint} transport failed: {type(exc).__name__}"
        ) from None
    if not response.ok:
        raise RuntimeError(f"Tavily {endpoint} returned HTTP {response.status_code}")
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError(f"Tavily {endpoint} response was not an object")
    return data


def _published_at(value: object) -> tuple[datetime, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    date_precision = "date" if len(value.strip()) == 10 else "instant"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), date_precision


def search(
    *,
    query: str,
    topic: str,
    date_from: datetime,
    as_of: datetime,
    limit: int,
) -> tuple[list[WebSearchResult], int, dict[str, object]]:
    """Return dated discovery records; undated and out-of-scope results are dropped."""
    data = _request(
        "search",
        {
            "query": query,
            "topic": topic,
            "search_depth": "basic",
            "max_results": limit,
            "start_date": date_from.date().isoformat(),
            "end_date": as_of.date().isoformat(),
            "include_published_date": True,
            "filter_by_published_date": True,
            "include_answer": False,
            "include_raw_content": False,
            "include_usage": True,
        },
    )
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        raise TypeError("Tavily search response had no results list")
    accepted: list[WebSearchResult] = []
    rejected = 0
    seen_urls: set[str] = set()
    for raw in raw_results:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        published = _published_at(raw.get("published_date"))
        url = raw.get("url")
        title = raw.get("title")
        if (
            published is None
            or not isinstance(url, str)
            or not url.startswith("https://")
            or not isinstance(title, str)
            or not title.strip()
            or url in seen_urls
        ):
            rejected += 1
            continue
        timestamp, precision = published
        # A date-only result cannot prove it existed earlier on that same day.
        if not date_from <= timestamp <= as_of or (
            precision == "date" and timestamp.date() == as_of.date()
        ):
            rejected += 1
            continue
        seen_urls.add(url)
        accepted.append(
            WebSearchResult(
                result_id="tavily:" + hashlib.sha256(url.encode()).hexdigest()[:24],
                title=title.strip(),
                source_url=url,
                summary=str(raw.get("content") or "")[:600],
                published_at=timestamp,
                date_precision=precision,
            )
        )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return accepted[:limit], rejected + max(0, len(accepted) - limit), usage


def extract(
    urls: list[str],
) -> tuple[list[ExtractedWebPage], list[str], dict[str, object]]:
    """Extract only caller-selected search URLs and surface individual failures."""
    if not 1 <= len(urls) <= 3 or any(not url.startswith("https://") for url in urls):
        raise ValueError("Tavily extraction requires one to three HTTPS URLs")
    data = _request(
        "extract",
        {
            "urls": urls,
            "extract_depth": "basic",
            "format": "text",
            "include_usage": True,
        },
    )
    raw_results = data.get("results")
    raw_failures = data.get("failed_results")
    if not isinstance(raw_results, list) or not isinstance(raw_failures, list):
        raise TypeError("Tavily extract response was missing result lists")
    requested = set(urls)
    pages: list[ExtractedWebPage] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        url, content = raw.get("url"), raw.get("raw_content")
        if (
            isinstance(url, str)
            and url in requested
            and isinstance(content, str)
            and content.strip()
        ):
            pages.append(
                ExtractedWebPage(
                    source_url=url,
                    content=content[:MAX_EXTRACT_CHARS],
                )
            )
    failed = [
        str(item.get("url"))
        for item in raw_failures
        if isinstance(item, dict) and item.get("url") in requested
    ]
    failed.extend(
        url
        for url in urls
        if url not in {page.source_url for page in pages} and url not in failed
    )
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return pages, failed, usage
