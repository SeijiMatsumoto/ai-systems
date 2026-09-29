import asyncio
from datetime import date
from typing import Any

import logfire

from backend.research_workflow.data.filings import ingest_filings


async def backfill_company_data(
    symbol: str,
    as_of: date,
    include_8k: bool = True,
) -> dict[str, Any]:
    """Backfill SEC filings for research; current news is discovered during a run."""
    normalized_symbol = symbol.strip().upper()
    filing_results: list[dict[str, Any]] = []

    with logfire.span(
        "Backfilling research corpus for {symbol}",
        symbol=normalized_symbol,
        as_of=as_of.isoformat(),
    ):
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
            # Each filing type is independent; retain successful results.
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

        failures = sum(
            result["error"] is not None for result in filing_results
        )
        total_documents_processed = sum(
            result["documents_processed"] for result in filing_results
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
            "status": status,
            "total_documents_processed": total_documents_processed,
            "failures": failures,
            "filings": filing_results,
        }
