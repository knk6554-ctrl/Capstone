"""Uvicorn entry point: ``uvicorn app:app --reload``."""

from wayband.api import app

__all__ = ["app"]
