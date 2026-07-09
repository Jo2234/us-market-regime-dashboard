from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.data.database import init_schema, session
from app.data.seed import seed_demo_data


def initialize_demo_database() -> None:
    """Create schema and seed deterministic data when the configured database is empty."""
    with session() as conn:
        init_schema(conn)
        seed_demo_data(conn)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize the demo database without deprecated FastAPI startup hooks."""
    initialize_demo_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="US Market Regime Dashboard API",
        version="0.1.0",
        description="FastAPI backend for US market regime analytics, seeded demo data, and freshness APIs.",
        lifespan=lifespan,
    )

    app.include_router(router)
    app.include_router(router, prefix="/api")
    initialize_demo_database()
    return app


app = create_app()

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://johan-vaz-site.vercel.app", "http://localhost:3000", "http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
