from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from app.data.database import load_previous_regime, save_regime_snapshot
from app.services import analytics


def _signal(name: str, passed: bool, value: float | None, threshold: str, evidence: str) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "value": analytics._rounded(value, 6),
        "threshold": threshold,
        "evidence": evidence,
    }


def _ret(conn, symbol: str, window: str, as_of: date | None) -> float | None:
    frame = analytics._price_frame(conn, symbol, end=as_of)
    return analytics.period_return(frame, window, as_of)


def _latest_as_of(conn, requested: date | None = None) -> date:
    latest = analytics.latest_date(conn, "SPY", requested)
    if not latest:
        raise ValueError("No SPY data is available to classify a regime")
    return latest


def classify_regime(conn, as_of: date | None = None) -> dict[str, Any]:
    observed_date = _latest_as_of(conn, as_of)
    spy = analytics._price_frame(conn, "SPY", end=observed_date)
    qqq_1m = _ret(conn, "QQQ", "1m", observed_date)
    spy_1m = _ret(conn, "SPY", "1m", observed_date)
    iwm_1m = _ret(conn, "IWM", "1m", observed_date)
    vix = analytics._price_frame(conn, "VIX", end=observed_date)
    uso_1m = _ret(conn, "USO", "1m", observed_date)
    gld_1m = _ret(conn, "GLD", "1m", observed_date)
    cper_1m = _ret(conn, "CPER", "1m", observed_date)
    xlu_1m = _ret(conn, "XLU", "1m", observed_date)
    xlp_1m = _ret(conn, "XLP", "1m", observed_date)
    xlk_1m = _ret(conn, "XLK", "1m", observed_date)
    xly_1m = _ret(conn, "XLY", "1m", observed_date)
    xli_1m = _ret(conn, "XLI", "1m", observed_date)
    xlf_1m = _ret(conn, "XLF", "1m", observed_date)
    cpi = analytics.latest_macro_value(conn, "CPI_YOY", observed_date)
    dgs10_change = analytics.macro_change(conn, "DGS10", 21, observed_date)
    dgs2_change = analytics.macro_change(conn, "DGS2", 21, observed_date)
    curve = analytics.yield_curve(conn, observed_date)
    spread_10y_2y = curve["spreads"].get("10y_2y")

    spy_latest = float(spy.iloc[-1]["value"])
    spy_ma50 = analytics.moving_average(spy, 50, observed_date)
    vix_latest = float(vix.iloc[-1]["value"]) if not vix.empty else None
    vix_avg_63 = analytics.moving_average(vix, 63, observed_date)
    qqq_minus_spy = None if qqq_1m is None or spy_1m is None else qqq_1m - spy_1m
    iwm_minus_spy = None if iwm_1m is None or spy_1m is None else iwm_1m - spy_1m
    gold_minus_spy = None if gld_1m is None or spy_1m is None else gld_1m - spy_1m
    defensive = None
    cyclical = None
    if None not in (xlu_1m, xlp_1m, xlk_1m, xly_1m, xli_1m, xlf_1m):
        defensive = (xlu_1m + xlp_1m) / 2
        cyclical = (xlk_1m + xly_1m + xli_1m + xlf_1m) / 4
    defensive_minus_cyclical = None if defensive is None or cyclical is None else defensive - cyclical

    signals = [
        _signal("sp500_above_50d_ma", bool(spy_ma50 and spy_latest > spy_ma50), spy_latest - spy_ma50 if spy_ma50 else None, "> 0", "S&P 500 price is compared with its 50-day moving average."),
        _signal("nasdaq_outperforming_sp500_1m", bool(qqq_minus_spy and qqq_minus_spy > 0), qqq_minus_spy, "> 0", "QQQ 1-month return minus SPY 1-month return."),
        _signal("vix_below_3m_average", bool(vix_latest and vix_avg_63 and vix_latest < vix_avg_63), vix_latest - vix_avg_63 if vix_latest and vix_avg_63 else None, "< 0", "VIX is compared with its 63-trading-day average."),
        _signal("defensives_outperform_cyclicals_1m", bool(defensive_minus_cyclical and defensive_minus_cyclical > 0), defensive_minus_cyclical, "> 0", "Utilities and staples average return minus cyclicals average return."),
        _signal("russell_underperforming_sp500_1m", bool(iwm_minus_spy and iwm_minus_spy < -0.01), iwm_minus_spy, "< -1%", "IWM 1-month return minus SPY 1-month return."),
        _signal("gold_outperforming_equities_1m", bool(gold_minus_spy and gold_minus_spy > 0), gold_minus_spy, "> 0", "GLD 1-month return minus SPY 1-month return."),
        _signal("oil_up_more_than_5pct_1m", bool(uso_1m and uso_1m > 0.05), uso_1m, "> 5%", "USO 1-month return."),
        _signal("copper_up_more_than_5pct_1m", bool(cper_1m and cper_1m > 0.05), cper_1m, "> 5%", "CPER 1-month return."),
        _signal("cpi_above_target", bool(cpi and cpi["value"] > 2.5), cpi["value"] if cpi else None, "> 2.5%", "Latest CPI year-over-year observation."),
        _signal("ten_year_rising_sharply_1m", bool(dgs10_change and dgs10_change > 0.25), dgs10_change, "> 0.25 percentage points", "10-year Treasury yield change over roughly 21 trading days."),
        _signal("two_year_rising_sharply_1m", bool(dgs2_change and dgs2_change > 0.25), dgs2_change, "> 0.25 percentage points", "2-year Treasury yield change over roughly 21 trading days."),
        _signal("yield_curve_inverted", bool(spread_10y_2y is not None and spread_10y_2y < 0), spread_10y_2y, "< 0", "10-year Treasury yield minus 2-year Treasury yield."),
    ]
    signal_by_name = {item["name"]: item for item in signals}

    risk_score = 0.0
    risk_score += 1 if signal_by_name["sp500_above_50d_ma"]["passed"] else -1
    risk_score += 1 if signal_by_name["vix_below_3m_average"]["passed"] else -1
    risk_score += 1 if signal_by_name["nasdaq_outperforming_sp500_1m"]["passed"] else 0
    risk_score -= 1 if signal_by_name["defensives_outperform_cyclicals_1m"]["passed"] else 0
    risk_score -= 1 if signal_by_name["russell_underperforming_sp500_1m"]["passed"] else 0
    risk_score -= 1 if signal_by_name["gold_outperforming_equities_1m"]["passed"] else 0

    growth_score = 0.0
    growth_score += 1 if signal_by_name["nasdaq_outperforming_sp500_1m"]["passed"] else 0
    growth_score += 1 if bool(iwm_minus_spy and iwm_minus_spy > 0) else 0
    growth_score += 1 if bool(spy_1m and spy_1m > 0) else -1

    inflation_score = 0.0
    inflation_score += 1 if signal_by_name["oil_up_more_than_5pct_1m"]["passed"] else 0
    inflation_score += 1 if signal_by_name["copper_up_more_than_5pct_1m"]["passed"] else 0
    inflation_score += 1 if signal_by_name["cpi_above_target"]["passed"] else 0

    rates_pressure_score = 0.0
    rates_pressure_score += 1 if signal_by_name["ten_year_rising_sharply_1m"]["passed"] else 0
    rates_pressure_score += 1 if signal_by_name["two_year_rising_sharply_1m"]["passed"] else 0
    rates_pressure_score += 1 if signal_by_name["yield_curve_inverted"]["passed"] else 0
    rates_pressure_score += 1 if bool(qqq_minus_spy and qqq_minus_spy < -0.01) else 0

    if bool(uso_1m and uso_1m > 0.1) and bool(cper_1m and cper_1m > 0.08):
        label = "commodity_shock"
    elif rates_pressure_score >= 2 and risk_score <= 1:
        label = "rates_pressure"
    elif inflation_score >= 2 and risk_score < 2:
        label = "inflation_pressure"
    elif risk_score <= -2:
        label = "risk_off_defensive"
    elif risk_score >= 2 and growth_score >= 2:
        label = "risk_on_broadening" if bool(iwm_minus_spy and iwm_minus_spy > 0) else "risk_on_growth_led"
    else:
        label = "mixed_transition"

    confidence_points = max(abs(risk_score), inflation_score, rates_pressure_score)
    confidence = "high" if confidence_points >= 3 else "medium" if confidence_points >= 2 else "low"

    previous = load_previous_regime(conn, observed_date)
    change_note = "No prior regime snapshot is available."
    if previous and previous["date"] != observed_date.isoformat():
        risk_delta = risk_score - float(previous["risk_score"])
        if previous["regime_label"] != label:
            change_note = f"Regime changed from {previous['regime_label']} to {label}; risk score moved {risk_delta:+.1f}."
        else:
            change_note = f"Regime label is unchanged; risk score moved {risk_delta:+.1f}."

    positive = [item for item in signals if item["passed"]][:5]
    negative = [item for item in signals if not item["passed"]][:5]
    summary = deterministic_summary(label, confidence, positive, negative, curve, observed_date, change_note)
    return {
        "id": str(uuid5(NAMESPACE_URL, f"regime:{observed_date.isoformat()}")),
        "date": observed_date.isoformat(),
        "regime_label": label,
        "confidence": confidence,
        "risk_score": round(risk_score, 3),
        "growth_score": round(growth_score, 3),
        "inflation_score": round(inflation_score, 3),
        "rates_pressure_score": round(rates_pressure_score, 3),
        "signals": {
            "top_positive": positive,
            "top_negative": negative,
            "all": signals,
            "what_changed": change_note,
            "data_limitations": [
                "Demo mode uses ETF proxies and generated historical data until public ingestion is configured.",
                "Signals are daily and do not represent real-time market conditions.",
            ],
        },
        "summary": summary,
    }


def deterministic_summary(
    label: str,
    confidence: str,
    positive: list[dict[str, Any]],
    negative: list[dict[str, Any]],
    curve: dict[str, Any],
    observed_date: date,
    change_note: str,
) -> str:
    leadership = positive[0]["name"].replace("_", " ") if positive else "no dominant positive signal"
    watch = negative[0]["name"].replace("_", " ") if negative else "signal confirmation"
    spread = curve["spreads"].get("10y_2y")
    spread_text = "not available" if spread is None else f"{spread:.2f} percentage points"
    return (
        f"As of {observed_date.isoformat()}, the dashboard classifies the market as {label} "
        f"with {confidence} confidence. The strongest confirming evidence is {leadership}. "
        f"The main watch item is {watch}. The 10Y-2Y Treasury spread is {spread_text}. "
        f"{change_note} This note is deterministic and only uses computed dashboard metrics."
    )


def recalculate_regimes(conn, as_of: date | None = None, trailing_days: int = 260) -> dict[str, Any]:
    frame = analytics._price_frame(conn, "SPY", end=as_of)
    if frame.empty:
        raise ValueError("No SPY data is available to recalculate regimes")
    dates = [item.date() for item in frame["date"].tail(trailing_days)]
    count = 0
    latest_snapshot = None
    for observed_date in dates:
        latest_snapshot = classify_regime(conn, observed_date)
        save_regime_snapshot(conn, latest_snapshot)
        count += 1
    return {"recalculated": count, "latest": latest_snapshot}
