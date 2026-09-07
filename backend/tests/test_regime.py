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


def test_loaded_history_classification_matches_sql_and_does_not_look_ahead(seeded_conn):
    from app.services.analytics import MarketHistory

    history = MarketHistory(seeded_conn)
    for observed in [date(2022, 8, 1), date(2023, 6, 1), date(2024, 6, 3), date(2025, 6, 2), date(2026, 6, 25)]:
        assert classify_regime(seeded_conn, observed, history=history) == classify_regime(seeded_conn, observed)


def test_backfill_matches_sequential_classification_with_bounded_queries(seeded_conn):
    from app.data.database import connect, save_regime_snapshot
    from app.services import analytics
    from app.services.regime import recalculate_regimes

    reference = connect(":memory:")
    seeded_conn.commit()
    seeded_conn.backup(reference)
    try:
        dates = analytics._price_frame(reference, "SPY")["date"].tail(20)
        expected = []
        for timestamp in dates:
            snapshot = classify_regime(reference, timestamp.date())
            save_regime_snapshot(reference, snapshot)
            expected.append(snapshot)
        queries = []
        seeded_conn.set_trace_callback(queries.append)
        result = recalculate_regimes(seeded_conn, trailing_days=20)
        seeded_conn.set_trace_callback(None)
        assert result == {"recalculated": 20, "latest": expected[-1]}
        columns = "date, signals, summary, risk_score, growth_score, inflation_score, rates_pressure_score"
        reference_rows = [tuple(row) for row in reference.execute(f"SELECT {columns} FROM regime_snapshots ORDER BY date")]
        actual_rows = [tuple(row) for row in seeded_conn.execute(f"SELECT {columns} FROM regime_snapshots ORDER BY date")]
        assert actual_rows == reference_rows
        assert sum(query.lstrip().upper().startswith("SELECT") for query in queries) <= 25
    finally:
        reference.close()
