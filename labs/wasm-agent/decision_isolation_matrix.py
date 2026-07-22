"""Score staged agent evidence and identify the first categorical failure."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parent
DEFAULT_MATRIX = LAB / "fixtures/decision-isolation-matrix-v1.json"


def load(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    stages = value.get("stages") if isinstance(value, dict) else None
    if value.get("schema") != "wasm-agent.decision-isolation-matrix.v1" or not isinstance(stages, list):
        raise ValueError("invalid decision isolation matrix")
    return value


def evaluate(observations: list[dict[str, Any]], *, matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    declared = matrix or load()
    supplied = {str(item.get("id") or ""): item for item in observations if isinstance(item, dict)}
    results = []
    first_failure = None
    for stage in declared["stages"]:
        stage_id = str(stage["id"])
        observation = supplied.get(stage_id, {})
        evidence = {str(item) for item in (observation.get("evidence") or [])}
        required = [str(item) for item in stage.get("requires") or []]
        missing = [item for item in required if item not in evidence]
        status = "passed" if not missing else "failed"
        result = {
            "id": stage_id, "category": stage["category"], "status": status,
            "required": required, "observed": sorted(evidence), "missing": missing,
            "run_id": str(observation.get("run_id") or "")[:160],
        }
        results.append(result)
        if first_failure is None and missing:
            first_failure = {
                "stage": stage_id, "category": stage["category"], "missing": missing,
                "run_id": result["run_id"],
            }
    return {
        "schema": "wasm-agent.decision-isolation-result.v1",
        "ok": first_failure is None,
        "first_failure": first_failure,
        "stages": results,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("observations", type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(json.loads(args.observations.read_text())), indent=2))
