from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_TRANSFORMED_FIXTURE = Path("tests/fixtures/external_memory_pressure_longmemeval_sample.json")
DEFAULT_REVIEW_MANIFEST = Path("evals/external_memory_pressure/longmemeval_review_manifest.json")
DEFAULT_OUTPUT_DIR = Path("evals/external_memory_pressure/output")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a reviewed external-memory pressure slice from a transformed local fixture.")
    parser.add_argument("--transformed-fixture", type=Path, default=DEFAULT_TRANSFORMED_FIXTURE)
    parser.add_argument("--reviewed-manifest", type=Path, default=DEFAULT_REVIEW_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-name", default="external-memory-pressure-build")
    args = parser.parse_args()

    fixture_rows = load_transformed_episodes(args.transformed_fixture)
    manifest = load_review_manifest(args.reviewed_manifest)
    reviewed = build_reviewed_external_pressure_episodes(episodes=fixture_rows, manifest=manifest)

    output_dir = args.output_dir / args.run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    reviewed_path = output_dir / "reviewed_episodes.json"
    reviewed_path.write_text(json.dumps(reviewed, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps({
        "transformed_fixture": str(args.transformed_fixture),
        "reviewed_manifest": str(args.reviewed_manifest),
        "reviewed_episodes": len(reviewed),
        "source_benchmark_families": sorted({row.get("source_benchmark_family") for row in reviewed}),
        "reviewed_output": str(reviewed_path),
    }, indent=2), encoding="utf-8")
    print(output_dir)
    return 0


def load_review_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_transformed_episodes(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_review_episode_ids(manifest: dict[str, Any]) -> list[str]:
    return [str(item["episode_id"]) for item in manifest.get("episodes", [])]


def build_reviewed_external_pressure_episodes(*, episodes: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(item["episode_id"]): dict(item) for item in episodes}
    reviewed: list[dict[str, Any]] = []
    default_family = str(manifest.get("source_benchmark_family", "longmemeval"))
    default_tier = str(manifest.get("dataset_tier", "confidence"))
    for spec in manifest.get("episodes", []):
        row = dict(by_id[str(spec["episode_id"])])
        row.setdefault("source_benchmark_family", default_family)
        row.setdefault("dataset_tier", default_tier)
        row.setdefault("suggested_native_lane", spec.get("suggested_native_lane"))
        row.setdefault("promotable", bool(spec.get("promotable", False)))
        row.setdefault("expected_failure_target", spec.get("expected_failure_target"))
        if spec.get("pressure_family") is not None:
            row["pressure_family"] = spec["pressure_family"]
        reviewed.append(row)
    return reviewed


if __name__ == "__main__":
    raise SystemExit(main())
