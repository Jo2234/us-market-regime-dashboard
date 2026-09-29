# Backend

FastAPI serves Yahoo Finance daily observations, with a per-instance cache and a validated committed snapshot fallback. See the root [README](../README.md) for setup, ticker mappings, refresh behavior and failure handling; see [formulas](../docs/formulas.md) for return and freshness definitions.

Run from the repository root: `PYTHONPATH=backend python -m uvicorn app.main:app --port 8000`.

Run offline unit tests: `PYTHONPATH=backend python -m pytest backend/tests`.

Production requests use an isolated in-memory database. No seed runs on startup. `MARKET_REGIME_DEMO_MODE=1` is a local-only opt-in.
