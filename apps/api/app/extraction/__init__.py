"""Extraction API composition; mounted after lead-owned contract integration."""

from fastapi import APIRouter

from app.extraction.routes_history import router as history_router
from app.extraction.routes_review import router as review_router
from app.extraction.routes_runs import router as runs_router

router = APIRouter()
router.include_router(review_router)
router.include_router(runs_router)
router.include_router(history_router)

__all__ = ["router"]
