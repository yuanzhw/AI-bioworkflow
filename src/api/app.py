"""FastAPI application factory."""

from fastapi import FastAPI, Response

from src.api.routes import api_router


def create_app() -> FastAPI:
    app = FastAPI(title="AI-bioworkflow API")

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
