"""List Gemma 4 models available to the configured Gemini API key."""

from __future__ import annotations

import sys
from pathlib import Path

from google import genai

# Make ``python ai/scripts/list_gemma_models.py`` work from the repository root.
AI_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = AI_ROOT.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "back-end"))

from backend.api.config import load_settings


def main() -> int:
    settings = load_settings()
    api_key = settings.gemini_api_key
    if not api_key:
        print("GEMINI_API_KEY is not configured in the environment or .env files.")
        return 1

    try:
        client = genai.Client(api_key=api_key)
        matches = []
        for model in client.models.list():
            name = getattr(model, "name", "") or ""
            display_name = getattr(model, "display_name", "") or ""
            description = getattr(model, "description", "") or ""
            searchable = f"{name} {display_name} {description}".lower()
            if "gemma-4" in searchable or "gemma4" in searchable:
                supported_actions = list(getattr(model, "supported_actions", None) or [])
                if "generateContent" not in supported_actions:
                    continue
                matches.append(
                    (
                        name,
                        supported_actions,
                        display_name,
                    )
                )
    except Exception as exc:  # pragma: no cover - this is a live diagnostic script
        message = str(exc).replace(api_key, "***")
        print(f"Gemini model lookup failed: {type(exc).__name__}: {message}")
        return 1

    if not matches:
        print("No Gemma 4 models were returned for this API key.")
        return 0

    print("Gemma 4 models available for generateContent:")
    for name, supported_actions, display_name in matches:
        actions = ", ".join(str(action) for action in supported_actions) or "unknown"
        label = f" — {display_name}" if display_name else ""
        print(f"- {name}{label} [supported actions: {actions}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
