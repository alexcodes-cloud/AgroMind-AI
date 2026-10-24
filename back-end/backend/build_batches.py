"""CLI: build JSON payloads that are ready to pass to Gemma Stage 1."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:  # Supports both `python -m backend.build_batches` and direct execution.
    from backend.services.batch_builder import build_stage1_batches, load_json_object
except ModuleNotFoundError:  # pragma: no cover - direct script fallback
    from services.batch_builder import build_stage1_batches, load_json_object


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    repository_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--farm",
        default=str(repository_root / "data-set" / "synthetic_farm.json"),
        help="Farm JSON path",
    )
    parser.add_argument("--weather", help="Optional weather snapshot JSON path")
    parser.add_argument("--batch-size", type=int, default=4, help="Zones per batch (default: 4)")
    parser.add_argument("--run-id", default="demo_run_001", help="Analysis run ID")
    parser.add_argument("--output", default="build/stage1_batches.json", help="Output JSON path")
    args = parser.parse_args()

    farm = load_json_object(args.farm)
    weather = load_json_object(args.weather) if args.weather else None
    batches = build_stage1_batches(
        farm,
        weather,
        batch_size=args.batch_size,
        analysis_run_id=args.run_id,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(batches, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Built {len(batches)} Stage 1 batches from {len(farm['zones'])} zones.")
    print(f"Output: {output}")
    for batch in batches:
        zone_ids = [zone["zone_id"] for zone in batch["zones"]]
        print(f"  {batch['batch_id']}: {', '.join(zone_ids)}")


if __name__ == "__main__":
    main()
