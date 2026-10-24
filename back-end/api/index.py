"""Vercel entrypoint for the AgroMind FastAPI backend."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.api.main import app  # noqa: E402


__all__ = ["app"]
