"""Two bounded spark batches, separate from the daily-history cache and model."""
from __future__ import annotations
import asyncio
import math
import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from app.core.telemetry import log_event
from app.data.instruments import YAHOO_TICKERS
from app.services import analytics
from app.services.calendar import market_now, market_status

_lock = threading.Lock()
_cached = {}
_expires = 0.0
_interval = 60
_fetched_at = None
_last_stats = {}


def normalize_spark(payload):
    result = {}
    for item in payload.get("spark", {}).get("result", []) or []:
        response = item.get("response") or []
        if not response:
            continue
        meta = response[0].get("meta", {})
        ticker = item.get("symbol")
        price, timestamp = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
        if not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 or not isinstance(timestamp, (int, float)):
            continue
        previous = meta.get("previousClose") or meta.get("chartPreviousClose")
        previous = previous if isinstance(previous, (int, float)) and math.isfinite(previous) and previous > 0 else None
        observed = datetime.fromtimestamp(timestamp, timezone.utc)
        result[ticker] = {"source": "yahoo_finance", "yahoo_ticker": ticker, "price": price,
                          "previous_close": previous, "observed_at": observed.isoformat(),
                          "observation_date": observed.astimezone(ZoneInfo("America/New_York")).date().isoformat(),
                          "price_basis": "regular_market_quote", "close_source": "yahoo_meta"}
    return result


async def fetch_quotes():
    tickers = list(YAHOO_TICKERS.values())
    stats = {"requests": 0, "http_429": 0, "http_401": 0, "retries": 0, "batches": []}
    started = time.perf_counter()
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}, timeout=4.0,
                                 limits=httpx.Limits(max_connections=2)) as client:
        async def batch(symbols):
            tick = time.perf_counter()
            stats["requests"] += 1
            response = await client.get("https://query1.finance.yahoo.com/v7/finance/spark",
                                        params={"symbols": ",".join(symbols), "range": "1d", "interval": "5m"})
            if response.status_code in (401, 429):
                stats[f"http_{response.status_code}"] += 1
            stats["batches"].append({"symbols": len(symbols), "ms": round((time.perf_counter()-tick)*1000, 2), "status": response.status_code})
            response.raise_for_status()
            return normalize_spark(response.json())
        try:
            if os.getenv("MARKET_REGIME_FORCE_QUOTE_FAILURE") == "1":
                raise RuntimeError("Quote failure simulation")
            batches = await asyncio.wait_for(asyncio.gather(*(batch(tickers[i:i+20]) for i in range(0, len(tickers), 20)), return_exceptions=True), timeout=5)
            merged = {}
            for item in batches:
                if isinstance(item, dict):
                    merged.update(item)
            if not merged:
                raise RuntimeError("No valid spark quotes")
            stats["partial"] = len(merged) != len(tickers)
            return merged, stats
        except Exception as exc:
            exc.telemetry = stats
            raise
        finally:
            stats["fetch_ms"] = round((time.perf_counter()-started)*1000, 2)
            log_event("spark_fetch", **stats)


def get_quotes(*, cached_only=False):
    global _cached, _expires, _interval, _fetched_at, _last_stats
    state = market_status()
    if not state["is_open"]:
        return {}, {"cache": "closed", "fetch_ms": 0, "refresh_seconds": state["refresh_seconds"]}
    cache, fetch_ms = "hit", 0
    if not cached_only:
        with _lock:
            if time.monotonic() >= _expires:
                try:
                    quotes, stats = asyncio.run(fetch_quotes())
                    _cached = {**_cached, **quotes}
                    _fetched_at = market_now().isoformat()
                    limited = stats.get("http_429", 0) + stats.get("http_401", 0)
                    _interval = min(900, _interval * 2) if limited else max(60, _interval // 2)
                    cache = "stale" if stats.get("partial") else "miss"
                except Exception as exc:
                    stats = getattr(exc, "telemetry", {})
                    _interval = min(900, _interval * 2)
                    cache = "stale"
                _last_stats = {**stats, "cache": cache}
                fetch_ms = stats.get("fetch_ms", 0)
                _expires = time.monotonic() + _interval
            elif _last_stats.get("cache") == "stale":
                cache = "stale"
    elif not _cached or time.monotonic() >= _expires:
        cache = "stale"
    now = market_now()
    rows = {}
    for symbol, ticker in YAHOO_TICKERS.items():
        if ticker not in _cached:
            continue
        quote = _cached[ticker]
        observed = datetime.fromisoformat(quote["observed_at"])
        age = (now - observed).total_seconds()
        current = quote["observation_date"] == state["session_date"] and -60 <= age
        rows[symbol] = {**quote, "is_current_session": current,
                        "is_stale": not current or age > max(1200, _interval * 2), "age_seconds": max(0, int(age))}
    return rows, {**_last_stats, "cache": cache, "fetch_ms": fetch_ms,
                  "fetched_at": _fetched_at, "refresh_seconds": _interval,
                  "retry_after_seconds": max(0, math.ceil(_expires-time.monotonic())) if cache == "stale" else 0}


def with_returns(quotes, history):
    """Add live endpoints; keep the daily API fields and classification unchanged."""
    result = {}
    for symbol, quote in quotes.items():
        result[symbol] = dict(quote)
        if not quote["is_current_session"]:
            continue
        observed = datetime.fromisoformat(quote["observed_at"]).astimezone(ZoneInfo("America/New_York")).date()
        rows = analytics._price_frame(history, symbol, end=observed)
        if not rows:
            continue
        previous = quote["previous_close"]
        # Missing Yahoo previous close can be recovered from the prior daily bar.
        prior = [r for r in rows if r["date"] < observed]
        if previous is None and prior:
            previous = prior[-1]["close"]
        returns = {"1d": quote["price"] / previous - 1 if previous else None}
        for window in ("1w", "1m", "3m", "ytd", "1y"):
            bases = [r for r in rows if r["date"] <= analytics.calendar_anchor(observed, window)]
            returns[window] = quote["price"] / bases[-1]["value"] - 1 if bases else None
        result[symbol].update(returns=returns, return_basis="live_price_over_adjusted_historical_close", previous_close=previous)
    return result
