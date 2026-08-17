import asyncio
from datetime import date
from typing import Any

import logfire

from backend.project_02_research_briefing_system.data.filings import ingest_filings
from backend.project_02_research_briefing_system.data.news import ingest_news

DEFAULT_NEWS_TOPICS = (
    "earnings OR revenue OR margins OR strategy",
    "regulation OR antitrust OR legal",
    'products OR "artificial intelligence" OR competition',
    "supply chain OR China OR tariffs OR manufacturing",
)


async def backfill_company_data(
    symbol: str,
    company_name: str,
    from_date: date,
    as_of: date,
    include_filings: bool = True,
    include_news: bool = True,
    include_8k: bool = True,
) -> dict[str, Any]:
    """Backfill a bounded company research corpus and report partial failures."""
    normalized_symbol = symbol.strip().upper()
    normalized_company_name = company_name.strip()
    filing_results: list[dict[str, Any]] = []
    news_results: list[dict[str, Any]] = []

    with logfire.span(
        "Backfilling research corpus for {symbol}",
        symbol=normalized_symbol,
        company_name=normalized_company_name,
        from_date=from_date.isoformat(),
        as_of=as_of.isoformat(),
    ):
        if include_filings:
            filing_start_date = date(max(as_of.year - 2, 1900), 1, 1)
            filing_specs = [("10-K", 2), ("10-Q", 6)]
            if include_8k:
                filing_specs.append(("8-K", 10))

            for form_type, limit in filing_specs:
                try:
                    documents = await asyncio.to_thread(
                        ingest_filings,
                        symbol=normalized_symbol,
                        form_type=form_type,
                        start_date=filing_start_date,
                        end_date=as_of,
                        limit=limit,
                    )
                    filing_results.append(
                        {
                            "form_type": form_type,
                            "documents_processed": len(documents),
                            "error": None,
                        }
                    )
                # Each source is an independent backfill unit. Preserve successful
                # sources even when a provider, database, or embedding call fails.
                except Exception as exc:  # noqa: BLE001
                    logfire.warn(
                        "Filing backfill failed for {symbol} {form_type}",
                        symbol=normalized_symbol,
                        form_type=form_type,
                        error_type=type(exc).__name__,
                    )
                    filing_results.append(
                        {
                            "form_type": form_type,
                            "documents_processed": 0,
                            "error": type(exc).__name__,
                        }
                    )

        if include_news:
            for index, topic in enumerate(DEFAULT_NEWS_TOPICS):
                if index:
                    await asyncio.sleep(1)

                try:
                    documents = await asyncio.to_thread(
                        ingest_news,
                        symbol=normalized_symbol,
                        company_name=normalized_company_name,
                        query=topic,
                        from_date=from_date.isoformat(),
                        limit=10,
                    )
                    news_results.append(
                        {
                            "query": topic,
                            "documents_processed": len(documents),
                            "error": None,
                        }
                    )
                # See the filing loop above: partial completion is the service's
                # explicit contract, regardless of which dependency failed.
                except Exception as exc:  # noqa: BLE001
                    logfire.warn(
                        "News backfill failed for {symbol}",
                        symbol=normalized_symbol,
                        query=topic,
                        error_type=type(exc).__name__,
                    )
                    news_results.append(
                        {
                            "query": topic,
                            "documents_processed": 0,
                            "error": type(exc).__name__,
                        }
                    )

        failures = sum(
            result["error"] is not None for result in [*filing_results, *news_results]
        )
        total_documents_processed = sum(
            result["documents_processed"] for result in [*filing_results, *news_results]
        )
        status = "completed" if failures == 0 else "partial"

        logfire.info(
            "Completed research corpus backfill for {symbol}",
            symbol=normalized_symbol,
            status=status,
            total_documents_processed=total_documents_processed,
            failures=failures,
        )

        return {
            "symbol": normalized_symbol,
            "company_name": normalized_company_name,
            "status": status,
            "total_documents_processed": total_documents_processed,
            "failures": failures,
            "filings": filing_results,
            "news": news_results,
        }
