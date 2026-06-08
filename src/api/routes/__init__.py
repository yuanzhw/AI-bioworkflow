"""API route modules."""

from fastapi import APIRouter

from src.api.routes.catalog import router as catalog_router
from src.api.routes.workflows import router as workflows_router


api_router = APIRouter()
api_router.include_router(catalog_router)
api_router.include_router(workflows_router)


__all__ = ["api_router"]
