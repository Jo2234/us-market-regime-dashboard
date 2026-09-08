# Recorded Yahoo chart responses

Recorded on 2026-09-29 from `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2y&interval=1d` with `User-Agent: Mozilla/5.0`. Symbols are mapped in `app/data/instruments.py`. These are unmodified response payloads serialized as JSON, not generated price paths. Some include an unfinished September 29 bar; tests normalize with a September 28 cutoff. Yield quotes are already in percent.

Recording is an explicit maintenance operation: `python scripts/refresh_snapshot.py --record-fixtures backend/tests/fixtures`. CI never downloads fixtures and unit tests prohibit network connections. The production fallback is a separate normalized snapshot.

Phase 1 additions recorded October 1, 2026: Yahoo HYG, LQD, RSP, VIX3M and DBC chart responses (history from January 2020), and FRED ICSA, NFCI, T10YIE, DFII10 CSV responses. The committed provider snapshots are recorded complete inputs for deterministic model tests; unit tests prohibit network access.
