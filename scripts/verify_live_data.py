#!/usr/bin/env python3
"""Independent Yahoo/FRED/API comparison; intentionally does not import app analytics."""
import argparse
import calendar
import csv
import io
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.calendar import latest_completed_session
from app.data.instruments import YAHOO_TICKERS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://market-regime-dashboard-mu.vercel.app")
    args = parser.parse_args()
    base = args.base_url.rstrip("/").removesuffix("/api")
    cutoff = latest_completed_session()
    with httpx.Client(timeout=28, headers={"User-Agent": "Mozilla/5.0"}) as client:
        api_response = client.get(f"{base}/api/dashboard/summary")
        api_response.raise_for_status()
        payload = api_response.json()
        curve_response = client.get(f"{base}/api/rates/yield-curve")
        curve_response.raise_for_status()
        curve = curve_response.json()
        assert "demo_seed" not in json.dumps([payload, curve]), "Synthetic provenance in production"
        rows = []
        price_history = {}
        for symbol in ["SPY", "QQQ"]:
            ticker = YAHOO_TICKERS[symbol]
            response = client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                                  params={"range": "2y", "interval": "1d"})
            response.raise_for_status()
            chart = response.json()["chart"]["result"][0]
            tz = ZoneInfo(chart["meta"]["exchangeTimezoneName"])
            closes = chart["indicators"]["quote"][0]["close"]
            # Independent same-session closing-quote check for Yahoo's delayed bar.
            meta = chart["meta"]
            last_day = datetime.fromtimestamp(chart["timestamp"][-1], tz).date()
            from app.services.calendar import session_close
            symbol_cutoff = cutoff
            official_close = session_close(last_day)
            meta_time = meta.get("regularMarketTime", 0)
            repaired = (closes[-1] is None and last_day <= symbol_cutoff and official_close
                        and meta_time >= official_close.timestamp()
                        and datetime.fromtimestamp(meta_time, tz).date() == last_day)
            if repaired:
                closes[-1] = meta["regularMarketPrice"]
            adjusted = chart["indicators"].get("adjclose", [{}])[0].get("adjclose", closes)
            if repaired:
                adjusted[-1] = closes[-1]
            bars = [(datetime.fromtimestamp(t, tz).date(), c, a)
                    for t, c, a in zip(chart["timestamp"], closes, adjusted)
                    if c is not None and datetime.fromtimestamp(t, tz).date() <= symbol_cutoff]
            price_history[symbol] = bars
            observed, close, adj = bars[-1]
            item = next(i for i in (payload["major_indices"] if symbol in {"SPY", "QQQ"} else curve["maturities"]) if i["symbol"] == symbol)
            def add(metric, actual, expected, tolerance):
                ok = (abs(actual - expected) <= tolerance and item["date"] == observed.isoformat()
                      and item["source"] == "yahoo_finance" and item["yahoo_ticker"] == ticker)
                rows.append((ticker, metric, observed.isoformat(), item["date"], actual, expected, "PASS" if ok else "FAIL"))
            add("price" if symbol in {"SPY", "QQQ"} else "yield %", item.get("price", item["value"]), close, 0.00011)
            if symbol in {"SPY", "QQQ"}:
                year, month = (observed.year - 1, 12) if observed.month == 1 else (observed.year, observed.month - 1)
                anchor = date(year, month, min(observed.day, calendar.monthrange(year, month)[1]))
                baseline = [bar for bar in bars if bar[0] <= anchor][-1]
                expected_return = (adj / baseline[2] - 1) * 100
                add("1M %", item["returns"]["1m"] * 100, expected_return, 0.000051)
        if payload.get("market_status", {}).get("is_open"):
            tickers = list(YAHOO_TICKERS.values())
            direct = {}
            for offset in range(0, len(tickers), 20):
                response = client.get("https://query1.finance.yahoo.com/v7/finance/spark",
                                      params={"symbols": ",".join(tickers[offset:offset+20]), "range": "1d", "interval": "5m"})
                response.raise_for_status()
                for quote in response.json()["spark"]["result"]:
                    direct[quote["symbol"]] = quote["response"][0]["meta"]
            for symbol, item in payload.get("live_quotes", {}).items():
                if not item.get("is_current_session") or item.get("is_stale"):
                    continue
                meta = direct[item["yahoo_ticker"]]
                same_tick = datetime.fromisoformat(item["observed_at"]).timestamp() == meta.get("regularMarketTime")
                difference = abs(item["price"] - meta["regularMarketPrice"])
                status = "PASS" if difference <= .00011 else "FAIL" if same_tick else "TIME-DIFF"
                rows.append((item["yahoo_ticker"], "live", item["observation_date"], item["observation_date"], item["price"], meta["regularMarketPrice"], status))
                if symbol in {"SPY", "QQQ"}:
                    observed = date.fromisoformat(item["observation_date"])
                    year, month = (observed.year - 1, 12) if observed.month == 1 else (observed.year, observed.month - 1)
                    anchor = date(year, month, min(observed.day, calendar.monthrange(year, month)[1]))
                    baseline = [bar for bar in price_history[symbol] if bar[0] <= anchor][-1]
                    # Hold the API's timestamped endpoint fixed while independently
                    # checking its calculation against Yahoo's historical denominator.
                    expected = (item["price"] / baseline[2] - 1) * 100
                    actual = item["returns"]["1m"] * 100
                    rows.append((item["yahoo_ticker"], "live 1M %", observed.isoformat(), item["observation_date"], actual, expected,
                                 "PASS" if abs(actual - expected) <= .000051 else "FAIL"))
            print("Intraday comparisons use the exact quote timestamp; TIME-DIFF means a newer market tick, not verified equality.")
        else:
            print("Market closed: live polling is paused; comparing completed-session prices and returns.")
        fred_cache = {}
        def fred_values(series_id):
            if series_id not in fred_cache:
                response = client.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": series_id}, headers={"User-Agent": "Python-urllib/3.11"})
                response.raise_for_status()
                fred_cache[series_id] = {r.get("observation_date", r.get("DATE")): float(r[series_id])
                    for r in csv.DictReader(io.StringIO(response.text)) if r[series_id] not in {"", "."}}
            return fred_cache[series_id]
        # Independently select the common curve date, allowing next-business-day publication.
        from datetime import timedelta
        from app.services.calendar import session_close
        def eligible(day):
            release = date.fromisoformat(day) + timedelta(days=1)
            while session_close(release) is None:
                release += timedelta(days=1)
            return release <= date.fromisoformat(payload["as_of"])
        rate_ids = ["DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"]
        common = set.intersection(*(set(fred_values(s)) for s in rate_ids))
        curve_day = max(day for day in common if eligible(day))
        for series_id in rate_ids:
            expected = fred_values(series_id)[curve_day]
            item = next(r for r in curve["maturities"] if r["symbol"] == series_id)
            ok = item["source"] == "fred" and item["fred_series_id"] == series_id and item["date"] == curve_day and abs(item["value"] - expected) < .000051
            rows.append((series_id, "yield %", curve_day, item["date"], item["value"], expected, "PASS" if ok else "FAIL"))
        for series_id, key in [("T10Y2Y", "10y_2y"), ("T10Y3M", "10y_3m")]:
            expected = fred_values(series_id)[curve_day]
            meta = curve["spread_metadata"][key]
            actual = curve["spreads"][key]
            ok = meta["date"] == curve_day and meta["fred_series_id"] == series_id and abs(actual - expected) < .000051
            rows.append((series_id, "spread pp", curve_day, meta["date"], actual, expected, "PASS" if ok else "FAIL"))
        for symbol, fred_id in {"FEDFUNDS": "DFF", "CPI_YOY": "CPIAUCSL", "CORE_CPI_YOY": "CPILFESL", "UNRATE": "UNRATE", "FEDFUNDS_MONTHLY": "FEDFUNDS"}.items():
            observations = fred_values(fred_id)
            observed = max(d for d in observations if d <= payload["as_of"])
            expected = observations[observed]
            if symbol.endswith("CPI_YOY"):
                baseline = date.fromisoformat(observed).replace(year=int(observed[:4]) - 1).isoformat()
                expected = (expected / observations[baseline] - 1) * 100
            item = payload.get("macro_summary", {}).get(symbol)
            actual = item["value"] if item else float("nan")
            api_date = item["date"] if item else "unavailable"
            ok = bool(item and abs(actual - expected) <= .000051 and api_date == observed
                      and item["source"] == "fred" and item["fred_series_id"] == fred_id)
            rows.append((fred_id, "YoY %" if symbol.endswith("CPI_YOY") else "rate %", observed,
                         api_date, actual, expected, "PASS" if ok else "FAIL"))
        print("Macro delivery: " + ", ".join(f"{s}={v['mode']}" for s, v in payload.get("macro_delivery", {}).get("series", {}).items()))
        print(f"API mode: {payload.get('data_mode')} | as of {payload['as_of']} | completed-session cutoff {cutoff}")
        print("Series     Metric    Source date API date    API         Source      Check")
        for ticker, metric, yahoo_date, api_date, actual, expected, status in rows:
            print(f"{ticker:10} {metric:9} {yahoo_date}  {api_date}  {actual:10.5f}  {expected:10.5f}  {status}")
        if any(row[-1] == "FAIL" for row in rows):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
