from __future__ import annotations

from datetime import date

from app.data.instruments import SECTOR_SYMBOLS
from app.services.regime import classify_regime
from conftest import insert_macro_path, insert_price_path


def test_regime_rules_identify_risk_off_defensive(empty_conn):
    base = [100.0] * 210
    risk_off = [100.0 - idx * 0.55 for idx in range(1, 71)]
    spy = base + risk_off
    start = date(2025, 1, 2)

    insert_price_path(empty_conn, "SPY", spy, start)
    insert_price_path(empty_conn, "QQQ", [value * (0.98 if idx > 210 else 1.0) for idx, value in enumerate(spy)], start)
    insert_price_path(empty_conn, "IWM", [value * (0.96 if idx > 210 else 1.0) for idx, value in enumerate(spy)], start)
    insert_price_path(empty_conn, "DIA", spy, start)
    insert_price_path(empty_conn, "VIX", [15.0] * 210 + [20.0 + idx * 0.25 for idx in range(70)], start)
    insert_price_path(empty_conn, "GLD", [100.0] * 210 + [100.0 + idx * 0.2 for idx in range(70)], start)
    insert_price_path(empty_conn, "USO", [100.0] * 280, start)
    insert_price_path(empty_conn, "CPER", [100.0] * 280, start)
    insert_price_path(empty_conn, "DXY", [100.0] * 280, start)
    for symbol in SECTOR_SYMBOLS:
        if symbol in {"XLU", "XLP"}:
            values = [100.0] * 210 + [100.0 + idx * 0.05 for idx in range(70)]
        else:
            values = [100.0] * 210 + [100.0 - idx * 0.25 for idx in range(70)]
        insert_price_path(empty_conn, symbol, values, start)
    for symbol, values in {
        "DGS3MO": [3.0] * 280,
        "DGS2": [3.5] * 280,
        "DGS10": [4.0] * 280,
        "DGS30": [4.3] * 280,
        "CPI_YOY": [2.2] * 280,
        "FEDFUNDS": [3.25] * 280,
        "UNRATE": [4.0] * 280,
    }.items():
        insert_macro_path(empty_conn, symbol, values, start)

    snapshot = classify_regime(empty_conn)

    assert snapshot["regime_label"] == "risk_off_defensive"
    assert snapshot["confidence"] in {"medium", "high"}
    assert any(signal["name"] == "defensives_outperform_cyclicals_1m" for signal in snapshot["signals"]["top_positive"])
