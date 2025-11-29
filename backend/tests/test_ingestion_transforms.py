from __future__ import annotations

from app.ingestion.providers import normalize_macro_rows, normalize_price_rows


def test_normalize_price_rows_skips_missing_close_and_deduplicates_dates():
    rows = [
        {"Date": "2026-01-02", "Open": "100", "High": "102", "Low": "99", "Close": "101", "Adj Close": "100.5", "Volume": "1000"},
        {"Date": "2026-01-03", "Open": "101", "High": "102", "Low": "100", "Close": "", "Adj Close": "", "Volume": "900"},
        {"Date": "2026-01-02", "Open": "100", "High": "103", "Low": "99", "Close": "102", "Adj Close": "101.5", "Volume": "1100"},
    ]

    normalized = normalize_price_rows("spy", rows, "fixture")

    assert len(normalized) == 1
    assert normalized[0].symbol == "SPY"
    assert normalized[0].close == 102.0
    assert normalized[0].adjusted_close == 101.5
    assert normalized[0].volume == 1100


def test_normalize_macro_rows_handles_monthly_sparse_data():
    rows = [
        {"DATE": "2026-01-01", "CPI_YOY": "3.1"},
        {"DATE": "2026-02-01", "CPI_YOY": "."},
        {"DATE": "2026-03-01", "CPI_YOY": "2.9"},
    ]

    normalized = normalize_macro_rows("CPI_YOY", rows, "fixture")

    assert [item.value for item in normalized] == [3.1, 2.9]
    assert [item.date.isoformat() for item in normalized] == ["2026-01-01", "2026-03-01"]
