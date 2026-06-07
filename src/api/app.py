"""FastAPI application factory."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    return FastAPI(title="AI-bioworkflow API")


app = create_app()
