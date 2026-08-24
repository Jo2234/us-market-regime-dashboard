"""Small, bounded FRED client. No pandas and no credentials in telemetry."""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from app.core.telemetry import log_event
from app.ingestion.providers import normalize_macro_rows

BUDGET_SECONDS = 6


def parse_csv(series_id: str, text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    if series_id not in (reader.fieldnames or []):
        raise ValueError("FRED CSV has no requested series column")
    return [{"date": item.date.isoformat(), "value": item.value}
            for item in normalize_macro_rows(series_id, reader, "fred")]


async def fetch_series(client, series_id, *, api_key=None, fixture_dir=None, stats=None):
    stats = stats if stats is not None else {}
    stats.update(attempts=0, retries=0, http_429=0, http_401=0, http_5xx=0)
    started = time.perf_counter()
    start = f"{date.today().year - 4}-01-01"
    try:
        for attempt in range(3):
            stats["attempts"] += 1
            try:
                if api_key:
                    response = await client.get("https://api.stlouisfed.org/fred/series/observations", params={
                        "series_id": series_id, "api_key": api_key, "file_type": "json", "observation_start": start})
                else:
                    response = await client.get("https://fred.stlouisfed.org/graph/fredgraph.csv",
                                                params={"id": series_id, "cosd": start})
                status = response.status_code
                stats["status"] = status
                for code in (429, 401):
                    stats[f"http_{code}"] += int(status == code)
                stats["http_5xx"] += int(status >= 500)
                if status == 200:
                    if api_key:
                        observations = [{"date": r.date.isoformat(), "value": r.value} for r in
                            normalize_macro_rows(series_id, response.json().get("observations", []), "fred")]
                    else:
                        observations = parse_csv(series_id, response.text)
                        if fixture_dir:
                            Path(fixture_dir, f"{series_id}.csv").write_text(response.text)
                    if not observations:
                        raise ValueError("Empty FRED observations")
                    return {"source": "fred", "fred_series_id": series_id,
                            "fetched_at": datetime.now(timezone.utc).isoformat(), "observations": observations}
                if status != 429 and status < 500:
                    raise ValueError(f"FRED HTTP {status}")
            except httpx.TransportError:
                pass
            if attempt < 2:
                stats["retries"] += 1
                await asyncio.sleep(.2 * 2 ** attempt + random.uniform(0, .1))
        raise ValueError("FRED retry budget exhausted")
    finally:
        stats["fetch_ms"] = round((time.perf_counter() - started) * 1000, 2)


async def fetch_batch(series_ids, *, fixture_dir=None):
    started = time.perf_counter()
    stats = {"transport": "json" if os.getenv("FRED_API_KEY") else "csv", "symbols": {}}
    results = {}
    # HTTPX's INFO request logger includes query strings; FRED keys must stay private.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    async with httpx.AsyncClient(timeout=3.5, headers={"User-Agent": "Python-urllib/3.11"},
                                 limits=httpx.Limits(max_connections=5)) as client:
        async def one(series_id):
            detail = stats["symbols"][series_id] = {}
            try:
                if os.getenv("MARKET_REGIME_FORCE_FRED_FAILURE") == "1":
                    raise ValueError("Forced FRED failure")
                results[series_id] = await fetch_series(client, series_id, api_key=os.getenv("FRED_API_KEY"),
                                                       fixture_dir=fixture_dir, stats=detail)
            except Exception as exc:
                detail["error"] = type(exc).__name__  # Never log response URLs/keys.
        tasks = [asyncio.create_task(one(s)) for s in series_ids]
        done, pending = await asyncio.wait(tasks, timeout=BUDGET_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for series_id in series_ids:
            if series_id not in results:
                stats["symbols"][series_id].setdefault("error", "Timeout")
    stats["fetch_ms"] = round((time.perf_counter() - started) * 1000, 2)
    log_event("fred_fetch", **stats)
    return results, stats
