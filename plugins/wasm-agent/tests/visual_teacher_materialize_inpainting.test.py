import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "visual_teacher_materialize_inpainting.py"
SPEC = importlib.util.spec_from_file_location("visual_teacher_materialize_inpainting", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_materialized_corpus_withholds_holdout_and_detects_gold_lineage_leakage(tmp_path):
    root = Path(__file__).resolve().parents[1] / "state" / "visual-teacher"
    summary = MODULE.materialize(
        root,
        "property-inpainting-test",
        tmp_path / "public",
        tmp_path / "private",
    )
    public = tmp_path / "public" / "property-inpainting-test"
    public_summary = json.loads((public / "summary.json").read_text())
    training = json.loads((public / "training.json").read_text())
    gold = json.loads((public / "gold.json").read_text())

    assert summary["training"] == 60
    assert summary["holdout"] == 2
    assert summary["holdoutDetail"] == "withheld"
    assert "entries" not in public_summary
    assert len(training["entries"]) == 60
    assert len(gold["excludedForLineageLeakage"]) == 2
    assert gold["entries"] == []
    assert not (public / "holdout.json").exists()
    assert all(entry["mask"]["semantics"] == "alpha_lt_128_reconstruct" for entry in training["entries"])
