import json
from datetime import datetime

import redis
import yfinance as yf

r = redis.Redis(host="localhost", port=6379, decode_responses=True)


def get_close_data(symbol: str):
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

    # Normalize data
    result = df[["Close"]].reset_index()
    result["Date"] = result["Date"].dt.strftime("%Y-%m-%d")
    result["Close"] = format(result["Close"], ".2f")

    # Store in redis cache
    data = result.to_json(orient="records")
    r.set(cache_key, data, ex=12 * 60 * 60)

    # Return normalized data
    return result


def get_company_snapshot(symbol: str) -> dict:
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


print(get_company_snapshot("AAPL"))
