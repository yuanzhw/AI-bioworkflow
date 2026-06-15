"""FastAPI application factory."""

from __future__ import annotations

import os

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import api_router


DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


def get_cors_origins() -> list[str]:
    configured = os.environ.get("AI_BIOWORKFLOW_CORS_ORIGINS")
    if configured is None:
        return list(DEFAULT_CORS_ORIGINS)

    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="AI-bioworkflow API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["health"])
    def read_root() -> dict[str, str]:
        return {
            "service": "AI-bioworkflow API",
            "status": "ok",
            "docs_url": "/docs",
        }

    @app.get("/health", tags=["health"])
    def read_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    def read_favicon() -> Response:
        return Response(status_code=204)

    app.include_router(api_router)
    return app


app = create_app()
