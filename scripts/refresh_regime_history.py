#!/usr/bin/env python3
"""Build the deterministic regime fallback from the two real provider snapshots."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.data import database
from app.services import market_data, macro_data, regime_history, analytics


def refresh():
    with database.session(':memory:') as conn:
        database.init_schema(conn)
        market_data.populate_database(conn, market_data.validate_snapshot(json.loads(market_data.SNAPSHOT_PATH.read_text())), 'snapshot')
        macro_data.populate_database(conn, macro_data.read_snapshot(), {})
        bundle, elapsed = regime_history.build(conn, analytics.MarketHistory(conn))
    encoded = json.dumps(bundle, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
    path = regime_history.SNAPSHOT_PATH
    if not path.exists() or path.read_text() != encoded:
        temporary = path.with_suffix('.tmp'); temporary.write_text(encoded); temporary.replace(path)
    print(f"Regime history: {len(bundle['snapshots'])} points in {elapsed:.2f} ms")

if __name__ == '__main__':
    refresh()
