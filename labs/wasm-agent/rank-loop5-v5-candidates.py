#!/usr/bin/env python3
"""Rank only exact-digest Loop 4-passing V5 variants."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];PROOF=ROOT/"reports/context/latest/loop4-loop5-v5-matrix-proof.json";OUT=ROOT/"reports/context/latest/loop5-v5-promotion-decision.json"
COMPLEXITY={"minimal_class_allowlist":1,"deny_first_class_policy":2,"explicit_completion_mode":3,"proof_policy_gate":3,"capability_requirement_gate":4,"evidence_requirement_gate":4,"route_owned_execution_profile":5,"structured_policy_decision":5,"single_context_profile_constructor":6}
def main():
 proof=json.loads(PROOF.read_text()); rows=[x for x in proof.get("rows",[]) if x.get("loop4Passed")]
 if proof.get("ok") is not True or len(rows)!=9: raise SystemExit("nine exact-digest Loop 4 passes required")
 for x in rows:x["policyComplexity"]=COMPLEXITY[x["strategy"]]
 rows.sort(key=lambda x:(x["policyComplexity"],x["promptTokens"],x["providerCalls"],x["toolCalls"],x["latencyMs"],x["candidateDigest"]))
 for i,x in enumerate(rows,1):x["rank"]=i
 winner=rows[0];result={"schema":"wasm-agent.safe-lab.loop5-promotion-decision.v1","ok":True,"terminalOutcome":"promoted_candidate_selected","winningVariant":winner,"ranking":rows,"decision":"eligible_for_reviewed_registry_promotion","reason":"All variants preserved semantics and one-call zero-tool behavior; the minimal compatible declared-class policy has the smallest generic surface.","activeRegistryMutated":False};OUT.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
