from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router
from app.data.database import init_schema, session
from app.data.seed import seed_demo_data


def create_app() -> FastAPI:
    app = FastAPI(
        title="US Market Regime Dashboard API",
        version="0.1.0",
        description="FastAPI backend for US market regime analytics, seeded demo data, and freshness APIs.",
    )

    @app.on_event("startup")
    def startup() -> None:
        with session() as conn:
            init_schema(conn)
            seed_demo_data(conn)

    app.include_router(router)
    return app


app = create_app()
