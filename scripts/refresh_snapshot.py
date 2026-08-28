#!/usr/bin/env python3
"""Refresh real Yahoo and FRED snapshots independently; commit only changed data."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ingestion.yahoo import fetch_snapshot
from app.services.market_data import SNAPSHOT_PATH, validate_snapshot
from app.services import macro_data
from app.data.instruments import FRED_SERIES
from app.ingestion.fred import fetch_batch


def refresh_yahoo(fixture_dir=None):
    snapshot = validate_snapshot(asyncio.run(fetch_snapshot(fixture_dir=fixture_dir)))
    snapshot.pop("_telemetry", None)
    if SNAPSHOT_PATH.exists():
        previous = json.loads(SNAPSHOT_PATH.read_text())
        if previous["series"] == snapshot["series"]:
            print("Yahoo observations unchanged; snapshot retained")
            return
        # A provider outage/partial update must not roll the last good file backwards.
        for symbol, series in previous["series"].items():
            if snapshot["series"][symbol]["bars"][-1]["date"] < series["bars"][-1]["date"]:
                raise RuntimeError(f"Refusing older {symbol} observations")
    temporary = SNAPSHOT_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    temporary.replace(SNAPSHOT_PATH)
    for symbol, series in snapshot["series"].items():
        last = series["bars"][-1]
        print(f"{symbol:7} {series['yahoo_ticker']:10} {last['date']} {last['close']:.4f}")


def refresh_fred(fixture_dir=None):
    previous = macro_data.read_snapshot()
    results, stats = asyncio.run(fetch_batch(list(FRED_SERIES.values()), fixture_dir=fixture_dir))
    merged = dict(previous)
    failures = []
    for series_id in FRED_SERIES.values():
        try:
            series = macro_data.validate_series(series_id, results[series_id])
            old = previous.get(series_id)
            if old and series["observations"][-1]["date"] < old["observations"][-1]["date"]:
                raise ValueError("Refusing older FRED observations")
            if not old or old["observations"] != series["observations"]:
                merged[series_id] = series
            print(f"{series_id:10} {series['observations'][-1]}")
        except (KeyError, ValueError, TypeError):
            failures.append(series_id)
    if merged != previous:
        temporary = macro_data.SNAPSHOT_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "series": merged}, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        temporary.replace(macro_data.SNAPSHOT_PATH)
    else:
        print("FRED observations unchanged; snapshot retained")
    if failures:
        raise RuntimeError(f"FRED unavailable for {', '.join(failures)}; prior observations retained")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-fixtures", type=Path)
    parser.add_argument("--provider", choices=("all", "yahoo", "fred"), default="all")
    args = parser.parse_args()
    if args.record_fixtures:
        args.record_fixtures.mkdir(parents=True, exist_ok=True)
    failed = []
    for name, refresh in (("yahoo", refresh_yahoo), ("fred", refresh_fred)):
        if args.provider not in ("all", name):
            continue
        try:
            refresh(args.record_fixtures)
        except Exception as exc:
            print(f"{name}: {type(exc).__name__}; snapshot retained for failed series", file=sys.stderr)
            failed.append(name)
    from refresh_regime_history import refresh
    refresh()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
