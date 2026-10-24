"""Vercel entrypoint for the AgroMind FastAPI backend.

This entrypoint lives at the repository root so the Vercel project can include
the shared ``ai``, ``contracts``, and ``data-set`` directories.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "back-end"

sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from backend.api.main import app  # noqa: E402


__all__ = ["app"]
