"""FastAPI application factory."""

from fastapi import FastAPI

from src.api.routes import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI-bioworkflow API")
    app.include_router(api_router)
    return app


app = create_app()
