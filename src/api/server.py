"""Development server entry point for the FastAPI application."""

from __future__ import annotations

import os

import uvicorn


DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8010


def get_api_host() -> str:
    return os.environ.get("AI_BIOWORKFLOW_API_HOST", DEFAULT_API_HOST)


def get_api_port() -> int:
    raw_port = os.environ.get("AI_BIOWORKFLOW_API_PORT")
    if raw_port is None:
        return DEFAULT_API_PORT

    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("AI_BIOWORKFLOW_API_PORT must be an integer") from exc

    if port < 1 or port > 65535:
        raise ValueError("AI_BIOWORKFLOW_API_PORT must be between 1 and 65535")
    return port


def run_dev_server() -> None:
    uvicorn.run(
        "src.api.app:app",
        host=get_api_host(),
        port=get_api_port(),
        reload=True,
    )


if __name__ == "__main__":
    run_dev_server()
