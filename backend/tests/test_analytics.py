from __future__ import annotations

import math
from datetime import date

import pandas as pd
import pytest

from app.services import analytics
from conftest import insert_price_path


def test_returns_use_adjusted_close_and_ytd_handles_year_boundary(empty_conn):
    insert_price_path(empty_conn, "SPY", [100, 110, 121, 133.1], start=date(2025, 12, 30))

    frame = analytics._price_frame(empty_conn, "SPY")

    assert analytics.period_return(frame, "1d") == pytest.approx(0.1)
    assert analytics.period_return(frame, "ytd") == pytest.approx(0.1)


def test_rolling_volatility_is_annualized():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=6, freq="B"),
            "value": [100.0, 101.0, 100.0, 102.0, 101.0, 103.0],
        }
    )
    expected = frame["value"].pct_change().dropna().tail(5).std(ddof=1) * math.sqrt(252)

    assert analytics.rolling_volatility(frame, 5) == pytest.approx(expected)


def test_drawdown_calculation():
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=5, freq="B"),
            "value": [100.0, 110.0, 105.0, 88.0, 99.0],
        }
    )

    assert analytics.max_drawdown(frame, lookback=5) == pytest.approx(-0.2)
