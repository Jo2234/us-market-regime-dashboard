#!/usr/bin/env python3
"""Refresh the committed Yahoo snapshot; never rewrite unchanged observations."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.ingestion.yahoo import fetch_snapshot
from app.services.market_data import SNAPSHOT_PATH, validate_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record-fixtures", type=Path)
    args = parser.parse_args()
    if args.record_fixtures:
        args.record_fixtures.mkdir(parents=True, exist_ok=True)
    snapshot = validate_snapshot(asyncio.run(fetch_snapshot(fixture_dir=args.record_fixtures)))
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


if __name__ == "__main__":
    main()
