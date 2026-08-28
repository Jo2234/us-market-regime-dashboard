"""Small, bounded Yahoo v8 chart client. No cookies, API keys or price fabrication."""
from __future__ import annotations

import asyncio
import math
import os
import random
import time

from app.core.telemetry import log_event
from datetime import date, datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.data.instruments import YAHOO_TICKERS, PRICE_SYMBOLS
from app.services.calendar import latest_completed_session, session_close

# Keep the minimal browser User-Agent verified against Yahoo from Vercel.
USER_AGENT = "Mozilla/5.0"


class YahooUnavailable(RuntimeError):
    def __init__(self, message, telemetry=None):
        super().__init__(message)
        self.telemetry = telemetry or {}


def normalize_chart(symbol: str, payload: dict, cutoff: date) -> list[dict]:
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise YahooUnavailable(f"Yahoo returned no chart for {symbol}")
    result = chart["result"][0]
    if result["meta"]["symbol"].upper() != YAHOO_TICKERS[symbol].upper():
        raise YahooUnavailable(f"Yahoo ticker mismatch for {symbol}")
    tz = ZoneInfo(result["meta"].get("exchangeTimezoneName", "America/New_York"))
    indicators = result["indicators"]
    quotes = indicators["quote"][0]
    adjusted = indicators.get("adjclose", [{}])[0].get("adjclose", [])
    bars = {}

    def number(values, index):
        value = values[index] if index < len(values) else None
        return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None

    for i, timestamp in enumerate(result.get("timestamp", [])):
        observed = datetime.fromtimestamp(timestamp, tz).date()
        close = number(quotes.get("close", []), i)
        close_source = "yahoo_bar"
        # Yahoo may leave the latest completed daily bar empty for hours. Only
        # the same session's post-close regular-market quote can repair it.
        if close is None and i == len(result.get("timestamp", [])) - 1 and observed <= cutoff:
            official_close = session_close(observed)
            meta = result["meta"]
            quote_time = meta.get("regularMarketTime")
            meta_price = meta.get("regularMarketPrice")
            if (official_close and isinstance(quote_time, (int, float))
                    and quote_time >= official_close.timestamp()
                    and datetime.fromtimestamp(quote_time, tz).date() == observed
                    and isinstance(meta_price, (int, float)) and math.isfinite(meta_price) and meta_price > 0):
                close, close_source = float(meta_price), "yahoo_meta"
        if observed > cutoff or close is None or close <= 0:
            continue
        adj = close if close_source == "yahoo_meta" else number(adjusted, i)
        if symbol in PRICE_SYMBOLS and (adj is None or adj <= 0):
            # Reject incomplete adjusted history instead of mixing return bases.
            raise YahooUnavailable(f"Missing adjusted close for {symbol} on {observed}")
        bars[observed] = {
            "date": observed.isoformat(), "close": close, "adjusted_close": adj,
            **({"close_source": "yahoo_meta", "adjusted_close_source": "same_as_unadjusted_close_pending_yahoo_bar"} if close_source == "yahoo_meta" else {}),
            **{key: number(quotes.get(key, []), i) for key in ("open", "high", "low", "volume")},
        }
    if not bars:
        raise YahooUnavailable(f"No completed daily bars for {symbol}")
    return [bars[day] for day in sorted(bars)]


async def fetch_chart(client: httpx.AsyncClient, ticker: str, *, stats=None, history_range="2y") -> dict:
    stats = stats if stats is not None else {}
    stats.update(attempts=0, responses=0, retries=0, http_429=0, http_401=0, http_5xx=0)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(ticker, safe='')}"
    for attempt in range(3):
        try:
            stats["attempts"] += 1
            stats["retries"] = attempt
            response = await client.get(url, params={"range": history_range, "interval": "1d"})
            stats["responses"] += 1
            stats["http_429"] += response.status_code == 429
            stats["http_401"] += response.status_code == 401
            stats["http_5xx"] += response.status_code >= 500
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code == 429 or exc.response.status_code >= 500
            if attempt == 2 or not retryable:
                raise YahooUnavailable(f"Yahoo request failed for {ticker}: {type(exc).__name__}") from exc
            await asyncio.sleep(0.3 * 2**attempt + random.uniform(0, 0.2))
    raise AssertionError("unreachable")


async def fetch_snapshot(*, fixture_dir=None, history_range="2y") -> dict:
    started = time.perf_counter()
    telemetry = {"symbols": {}, "history_range": history_range}
    now = datetime.now(timezone.utc)
    cutoff = latest_completed_session(now)
    semaphore = asyncio.Semaphore(8)
    tasks = []
    failure = None
    try:
        if os.getenv("MARKET_REGIME_FORCE_YAHOO_FAILURE") == "1":
            raise YahooUnavailable("Yahoo failure simulation enabled")
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=8,
                                     limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
                                     follow_redirects=True) as client:
            async def fetch_one(symbol, ticker):
                async with semaphore:
                    stats = telemetry["symbols"][symbol] = {}
                    symbol_started = time.perf_counter()
                    try:
                        payload = await fetch_chart(client, ticker, stats=stats, history_range=history_range)
                        bars = normalize_chart(symbol, payload, cutoff)
                        stats["ok"] = True
                    finally:
                        stats["ms"] = round((time.perf_counter() - symbol_started) * 1000, 2)
                    if fixture_dir:
                        import json
                        (fixture_dir / f"{symbol}.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n")
                    return symbol, {"source": "yahoo_finance", "yahoo_ticker": ticker, "bars": bars}
            tasks = [asyncio.create_task(fetch_one(s, t)) for s, t in YAHOO_TICKERS.items()]
            try:
                # Cancel siblings on error/deadline; never leave unbounded work running.
                results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=18)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as exc:
        failure = exc
    finally:
        telemetry["fetch_ms"] = round((time.perf_counter() - started) * 1000, 2)
        for key in ("attempts", "responses", "retries", "http_429", "http_401", "http_5xx"):
            telemetry[key] = sum(stats.get(key, 0) for stats in telemetry["symbols"].values())
        telemetry["ok"] = failure is None
        log_event("yahoo_fetch", **telemetry)
    if failure is not None:
        raise YahooUnavailable(f"Yahoo refresh failed: {type(failure).__name__}", telemetry) from failure
    return {"version": 1, "fetched_at": now.isoformat(), "series": dict(results), "_telemetry": telemetry}
