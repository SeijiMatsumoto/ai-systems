import json
from datetime import datetime

import redis
import yfinance as yf


def get_close_data(symbol: str):
    today = datetime.today().strftime("%Y-%m-%d")
    cache_key = f"close_data-{symbol}-{today}"

    # Check redis first
    r = redis.Redis(host="localhost", port=6379, decode_responses=True)
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
    r.close()
    return result
