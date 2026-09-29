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
        response = await call_next(request)
        response.headers["Cache-Control"] = (
            "public, max-age=0, s-maxage=900, stale-while-revalidate=3600"
            if request.method == "GET" and response.status_code == 200
            else "no-store"
        )
        return response
    return app


app = create_app()
