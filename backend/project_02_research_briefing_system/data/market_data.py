import json
from datetime import datetime
from typing import Any, Literal, cast

import pandas as pd
import redis
import yfinance as yf

r = redis.Redis(host="localhost", port=6379, decode_responses=True)

StatementType = Literal["income", "balance_sheet", "cash_flow"]
FinancialFrequency = Literal["yearly", "quarterly"]


def _format_date(value: object) -> str:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _json_safe_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def get_close_data(symbol: str) -> list[dict[str, str | float]]:
    # To be prefetched
    today = datetime.today().strftime("%Y-%m-%d")  # noqa: DTZ002
    cache_key = f"close_data-{symbol}-{today}"

    # Check redis first
    cached_data = r.get(cache_key)

    # If cache hit, return data
    if cached_data:
        print("Cache hit!")
        return json.loads(cached_data)

    print("Cache miss: calling yfinance api")
    # If cache miss, hit yfinance API
    df = yf.Ticker(symbol).history(period="3mo")
    if not isinstance(df, pd.DataFrame):
        raise TypeError("yfinance history response was not a DataFrame")
    close_series = cast(pd.Series, df["Close"])

    # Normalize data into the same JSON-serializable shape returned by Redis.
    result = [
        {
            "Date": _format_date(date),
            "Close": round(float(cast(Any, close)), 2),
        }
        for date, close in close_series.items()
    ]

    # Store in redis cache
    r.set(cache_key, json.dumps(result), ex=12 * 60 * 60)

    # Return normalized data
    return result


def get_company_snapshot(symbol: str) -> dict:
    # To be prefetched
    cache_key = f"snapshot-{symbol}"

    cached_data = r.get(cache_key)

    if cached_data:
        print("Cache hit!")
        return json.loads(cached_data)

    ticker = yf.Ticker(symbol)
    info = ticker.info

    snapshot = {
        "symbol": symbol,
        "company_name": info.get("longName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "valuation": {
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
        },
        "profitability": {
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "roe": info.get("returnOnEquity"),
            "revenue_growth": info.get("revenueGrowth"),
        },
        "analyst_consensus": {
            "target_mean_price": info.get("targetMeanPrice"),
            "recommendation": info.get("recommendationKey"),
            "num_opinions": info.get("numberOfAnalystOpinions"),
        },
        "latest_news_headlines": [
            item.get("content", {}).get("title") for item in ticker.news[:5]
        ],
    }

    r.set(cache_key, json.dumps(snapshot), ex=12 * 60 * 60)  # 30 days
    return snapshot


def get_historical_financials(
    symbol: str,
    statement_type: StatementType = "income",
    frequency: FinancialFrequency = "yearly",
    periods: int = 4,
) -> dict:
    """Fetch historical financial statements in a period-first JSON shape."""
    valid_statement_types = {"income", "balance_sheet", "cash_flow"}
    if statement_type not in valid_statement_types:
        raise ValueError(
            "statement_type must be income, balance_sheet, or cash_flow"
        )
    if frequency not in {"yearly", "quarterly"}:
        raise ValueError("frequency must be yearly or quarterly")
    if not 1 <= periods <= 8:
        raise ValueError("periods must be between 1 and 8")

    normalized_symbol = symbol.upper()
    today = datetime.today().strftime("%Y-%m-%d")  # noqa: DTZ002
    cache_key = (
        f"financials-{normalized_symbol}-{statement_type}-{frequency}-{periods}-"
        f"{today}"
    )
    cached_data = r.get(cache_key)
    if cached_data:
        return json.loads(cached_data)

    ticker = yf.Ticker(normalized_symbol)
    if statement_type == "income":
        dataframe = ticker.get_income_stmt(freq=frequency)
    elif statement_type == "balance_sheet":
        dataframe = ticker.get_balance_sheet(freq=frequency)
    else:
        dataframe = ticker.get_cash_flow(freq=frequency)

    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("yfinance financial statement response was not a DataFrame")

    dataframe = dataframe.iloc[:, :periods]
    period_results = []
    for period_end in dataframe.columns:
        metrics = {
            str(metric): _json_safe_value(value)
            for metric, value in dataframe[period_end].items()
        }
        period_results.append(
            {
                "period_end": _format_date(period_end),
                "metrics": metrics,
            }
        )

    result = {
        "symbol": normalized_symbol,
        "statement_type": statement_type,
        "frequency": frequency,
        "requested_periods": periods,
        "returned_periods": len(period_results),
        "periods": period_results,
    }
    r.set(cache_key, json.dumps(result), ex=12 * 60 * 60)
    return result
