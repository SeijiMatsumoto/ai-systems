import os
from datetime import datetime, timedelta, timezone
from typing import Any

import logfire
import requests
from dotenv import load_dotenv

from backend.shared.article_processing import (
    MIN_ARTICLE_TEXT_CHARS,
    clean_article_text,
    story_fingerprint,
    story_key,
)

load_dotenv()


class WorldNewsTransientError(RuntimeError):
    """A retryable World News API transport, rate-limit, or server failure."""


def _build_world_news_query(
    symbol: str,
    query: str,
    company_name: str | None = None,
) -> str:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise ValueError("query must not be blank")

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be blank")
    company_scope = normalized_symbol
    if company_name:
        escaped_company_name = company_name.strip().replace('"', "")
        company_scope = f'({normalized_symbol} OR "{escaped_company_name}")'

    world_news_query = f"{company_scope} AND ({normalized_query})"
    if len(world_news_query) > 100:
        raise ValueError(
            "World News API query must be at most 100 characters after company scoping"
        )
    return world_news_query


def fetch_news(
    symbol: str,
    query: str,
    date_from: datetime,
    date_to: datetime,
    limit: int = 5,
    company_name: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch and normalize news articles without writing to the database."""
    api_key = os.getenv("WORLD_NEWS_API_KEY")
    if not api_key:
        raise ValueError("WORLD_NEWS_API_KEY is not configured")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    q = _build_world_news_query(symbol, query, company_name)
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    else:
        date_from = date_from.astimezone(timezone.utc)
    if date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    else:
        date_to = date_to.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)

    if date_from > date_to:
        raise ValueError("date_from cannot be after date_to")
    if date_to > now:
        raise ValueError("date_to cannot be in the future")

    age = now - date_from
    if age > timedelta(days=30):
        raise ValueError("date_from cannot be older than 30 days on the free plan")

    formatted_date_from = date_from.strftime("%Y-%m-%d %H:%M:%S")
    formatted_date_to = date_to.strftime("%Y-%m-%d %H:%M:%S")

    with logfire.span(
        "Fetching World News API articles for {symbol}",
        symbol=symbol.upper(),
        query=query,
        world_news_query=q,
        from_date=formatted_date_from,
        to_date=formatted_date_to,
        limit=limit,
    ):
        try:
            response = requests.get(
                "https://api.worldnewsapi.com/search-news",
                headers={"x-api-key": api_key},
                params={
                    "text": q,
                    "text-match-indexes": "title,content",
                    "language": "en",
                    "earliest-publish-date": formatted_date_from,
                    "latest-publish-date": formatted_date_to,
                    "sort": "publish-time",
                    "sort-direction": "DESC",
                    "number": limit,
                },
                timeout=15,
            )
        except requests.RequestException as exc:
            raise WorldNewsTransientError(
                f"World News API request failed with {type(exc).__name__}"
            ) from None

        if response.status_code == 429 or response.status_code >= 500:
            raise WorldNewsTransientError(
                "World News API temporarily unavailable with "
                f"status {response.status_code}"
            )
        if not response.ok:
            logfire.error(
                "World News API request failed for {symbol} with status {status_code}",
                symbol=symbol.upper(),
                status_code=response.status_code,
            )
            raise RuntimeError(
                f"World News API returned {response.status_code}: {response.text[:500]}"
            )

        data = response.json()

    if not isinstance(data, dict):
        raise TypeError("World News API response was not an object")
    articles = data.get("news")
    if not isinstance(articles, list):
        raise TypeError("World News API response did not contain a news list")

    if not articles:
        logfire.warn(
            "World News API returned no articles for {symbol}",
            symbol=symbol.upper(),
            query=query,
            from_date=formatted_date_from,
        )
    else:
        logfire.info(
            "World News API returned {article_count} articles for {symbol}",
            article_count=len(articles),
            available_articles=data.get("available"),
            symbol=symbol.upper(),
            quota_request=response.headers.get("X-API-Quota-Request"),
            quota_left=response.headers.get("X-API-Quota-Left"),
        )

    normalized_articles: list[dict[str, Any]] = []
    skipped_articles = 0
    skipped_duplicate_articles = 0
    seen_story_keys: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            skipped_articles += 1
            continue
        content = article.get("text")
        title = article.get("title")
        source_url = article.get("url")
        published_at = article.get("publish_date")
        summary = article.get("summary")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (content, title, source_url, published_at)
        ):
            skipped_articles += 1
            continue
        assert isinstance(content, str)
        assert isinstance(title, str)
        assert isinstance(source_url, str)
        assert isinstance(published_at, str)

        try:
            published_datetime = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
        except ValueError:
            skipped_articles += 1
            continue
        if published_datetime.tzinfo is None:
            published_datetime = published_datetime.replace(tzinfo=timezone.utc)
        else:
            published_datetime = published_datetime.astimezone(timezone.utc)
        if published_datetime > date_to:
            skipped_articles += 1
            continue

        normalized_story_key = story_key(title)
        if normalized_story_key in seen_story_keys:
            skipped_duplicate_articles += 1
            continue

        cleaned_content = clean_article_text(title, content)
        if len(cleaned_content) < MIN_ARTICLE_TEXT_CHARS:
            skipped_articles += 1
            continue
        seen_story_keys.add(normalized_story_key)

        authors = article.get("authors")
        author = (
            ", ".join(str(value) for value in authors if value)
            if isinstance(authors, list)
            else None
        )
        normalized_articles.append(
            {
                "reference_id": str(article.get("id") or source_url),
                "title": title.strip(),
                "source_url": source_url.strip(),
                "author": author or None,
                "published_at": published_at,
                "content": cleaned_content,
                "summary": summary,
                "raw_content_chars": len(content.strip()),
                "cleaned_content_chars": len(cleaned_content),
                "story_fingerprint": story_fingerprint(title),
            }
        )

    if skipped_articles:
        logfire.warn(
            "Skipped {skipped_articles} World News API articles without full text or required metadata",
            skipped_articles=skipped_articles,
            symbol=symbol.upper(),
        )
    if skipped_duplicate_articles:
        logfire.info(
            "Skipped {skipped_duplicate_articles} duplicate World News API stories",
            skipped_duplicate_articles=skipped_duplicate_articles,
            symbol=symbol.upper(),
        )

    return normalized_articles
