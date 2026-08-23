from app.core import telemetry
import time
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="US Market Regime Dashboard API", version="0.2.0",
                  description="Yahoo Finance daily market data with explicit snapshot fallback.")
    app.include_router(router)
    app.include_router(router, prefix="/api")
    app.add_middleware(CORSMiddleware,
        allow_origins=["https://johan-vaz-site.vercel.app", "http://localhost:3000", "http://localhost:5173"],
        allow_methods=["GET"], allow_headers=["*"])

    @app.middleware("http")
    async def cache_headers(request, call_next):
        started = time.perf_counter()
        telemetry.REQUEST_COUNT += 1
        count = telemetry.REQUEST_COUNT
        response = await call_next(request)
        elapsed = (time.perf_counter() - started) * 1000
        delivery = getattr(request.state, "market_delivery", {})
        response.headers["Server-Timing"] = f'app;dur={elapsed:.2f}, import;dur={telemetry.IMPORT_MS:.2f}, yahoo;dur={delivery.get("fetch_ms", 0):.2f}'
        response.headers["X-Market-Cache"] = delivery.get("cache", "none")
        response.headers["X-Market-Revision"] = os.getenv("VERCEL_GIT_COMMIT_SHA", "local")
        response.headers["X-Market-Instance"] = telemetry.INSTANCE_ID
        response.headers["X-Market-Request"] = str(count)
        telemetry.log_event("api_request", instance=telemetry.INSTANCE_ID, request=count, app_ms=round(elapsed, 2))
        response.headers["Cache-Control"] = (
            "public, max-age=0, s-maxage=900, stale-while-revalidate=3600"
            if request.method == "GET" and response.status_code == 200
            else "no-store"
        )
        return response
    return app


app = create_app()

telemetry.IMPORT_MS = (time.perf_counter() - telemetry.IMPORT_STARTED) * 1000
