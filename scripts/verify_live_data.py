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
        for symbol in ["SPY", "QQQ", "DGS3MO", "DGS2", "DGS5", "DGS10", "DGS30"]:
            ticker = YAHOO_TICKERS[symbol]
            response = client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                                  params={"range": "2y", "interval": "1d"})
            response.raise_for_status()
            chart = response.json()["chart"]["result"][0]
            tz = ZoneInfo(chart["meta"]["exchangeTimezoneName"])
            closes = chart["indicators"]["quote"][0]["close"]
            adjusted = chart["indicators"].get("adjclose", [{}])[0].get("adjclose", closes)
            bars = [(datetime.fromtimestamp(t, tz).date(), c, a)
                    for t, c, a in zip(chart["timestamp"], closes, adjusted)
                    if c is not None and datetime.fromtimestamp(t, tz).date() <= cutoff]
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
        for symbol, fred_id in {"FEDFUNDS": "DFF", "CPI_YOY": "CPIAUCSL", "CORE_CPI_YOY": "CPILFESL", "UNRATE": "UNRATE", "FEDFUNDS_MONTHLY": "FEDFUNDS"}.items():
            response = client.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": fred_id},
                                  headers={"User-Agent": "Python-urllib/3.11"})
            response.raise_for_status()
            observations = {r.get("observation_date", r.get("DATE")): float(r[fred_id])
                            for r in csv.DictReader(io.StringIO(response.text)) if r[fred_id] not in {"", "."}}
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
        if any(row[-1] != "PASS" for row in rows):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
