"""Extraction API composition; mounted after lead-owned contract integration."""

from app.extraction.routes_runs import router

__all__ = ["router"]
