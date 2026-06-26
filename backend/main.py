from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.data.database import connect, init_schema
from app.data.seed import seed_demo_data
from app.main import app
from app.services import analytics, regime


@lru_cache(maxsize=1)
def _compat_conn():
    conn = connect(":memory:")
    init_schema(conn)
    seed_demo_data(conn)
    return conn


def return_window(symbol: str, days: int) -> float:
    """Backward-compatible helper for root-level smoke tests."""
    conn = _compat_conn()
    frame = analytics._price_frame(conn, symbol.upper())
    if len(frame) <= days:
        return 0.0
    current = float(frame.iloc[-1]["value"])
    base = float(frame.iloc[-days - 1]["value"])
    return 0.0 if base == 0 else current / base - 1.0


def regime_snapshot() -> dict:
    """Backward-compatible helper for root-level smoke tests."""
    return regime.classify_regime(_compat_conn())
