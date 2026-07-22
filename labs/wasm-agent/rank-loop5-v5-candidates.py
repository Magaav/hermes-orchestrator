#!/usr/bin/env python3
"""Rank only exact-digest Loop 4-passing V5 variants."""
import json
from pathlib import Path
from loop5_candidate_policy import rank_passing_candidates
ROOT=Path(__file__).resolve().parents[2];PROOF=ROOT/"reports/context/latest/loop4-loop5-v5-matrix-proof.json";OUT=ROOT/"reports/context/latest/loop5-v5-promotion-decision.json"
def main():
 proof=json.loads(PROOF.read_text());result=rank_passing_candidates(proof)
 OUT.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
