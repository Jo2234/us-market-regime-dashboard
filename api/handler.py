"""Vercel ASGI entrypoint for the market regime FastAPI application."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402


__all__ = ["app"]
