#!/usr/bin/env python3
"""Offline sensitivity counts on recorded observations; no parameter fitting."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.data import database
from app.services import analytics, market_data, macro_data, regime_v2
with database.session(':memory:') as conn:
    database.init_schema(conn)
    market_data.populate_database(conn,market_data.validate_snapshot(json.loads(market_data.SNAPSHOT_PATH.read_text())),'snapshot')
    macro_data.populate_database(conn,macro_data.read_snapshot(),{})
    result=regime_v2.sensitivity(analytics.MarketHistory(conn))
path=Path(sys.argv[1] if len(sys.argv)>1 else 'artifacts/redesign/sensitivity.json')
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(result,indent=2)+'\n')
for group, variants in result.items():
    print(group, {label:row['quadrant_changes'] for label,row in variants.items()},flush=True)
