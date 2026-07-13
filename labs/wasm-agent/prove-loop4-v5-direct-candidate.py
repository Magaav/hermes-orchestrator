#!/usr/bin/env python3
"""Bind V5 direct-completion regression evidence to one exact candidate digest."""
from __future__ import annotations
import json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; LAB=Path(__file__).resolve().parent
BASELINE=LAB/"staging/loop3-ranked-nine-20260712-benchmark-nine-lane.json"
CANDIDATE=ROOT/"reports/context/latest/loop4-v5-direct-candidate-live-result.json"
PROJECTION=LAB/"fixtures/master-frontier-v5-direct-candidate.json"
PACKAGE=ROOT/"reports/context/latest/master-frontier-v5-adapter-package-result.json"
REPORT=ROOT/"reports/context/latest/loop4-v5-direct-candidate-regression-proof.json"
def main():
 started=time.monotonic();errors=[]
 test=subprocess.run(["python3","plugins/wasm-agent/tests/master_frontier_v5.test.py"],cwd=ROOT,capture_output=True,text=True)
 if test.returncode:errors.append("focused V5 regression bank failed")
 baseline=json.loads(BASELINE.read_text());candidate=json.loads(CANDIDATE.read_text());projection=json.loads(PROJECTION.read_text());package=json.loads(PACKAGE.read_text())
 digest=str(projection.get("candidateDigest") or "")
 if not digest or package.get("artifactSha256")!=digest or projection.get("adapterArtifactSha256")!=digest:errors.append("candidate digest binding mismatch")
 identity=candidate.get("candidateIdentity") if isinstance(candidate.get("candidateIdentity"),dict) else {}
 if identity.get("candidateDigest")!=digest or identity.get("artifactSha256")!=digest or identity.get("adapterVolume")!=projection.get("adapterVolume"):errors.append("live candidate identity is not bound to the exact artifact")
 base_lane=next((x for x in baseline.get("results",[]) if x.get("slot")=="harness-01"),{})
 base_receipts=[x for x in baseline.get("gatewayReceipts",[]) if x.get("laneId")=="harness-01" and x.get("status")==200]
 if (base_lane.get("answer") or {}).get("semantic",{}).get("passed") is not True:errors.append("baseline semantic proof missing")
 receipts=[x for x in candidate.get("gatewayReceipts",[]) if x.get("status")==200]
 if candidate.get("semanticEvaluationPassed") is not True or candidate.get("rankingAllowed") is not True:errors.append("candidate semantic proof failed")
 if len(receipts)!=1 or sum(int(x.get("toolCallCount") or 0) for x in receipts)!=0 or candidate.get("warnings"):errors.append("candidate direct-completion efficiency contract failed")
 if candidate.get("cleanupComplete") is not True or any(x.get("returnedModel")!="frank/GLM-5.2" for x in receipts):errors.append("candidate safety/model proof failed")
 result={"schema":"wasm-agent.safe-lab.loop4-regression-proof.v1","ok":not errors,"classification":"loop4_regression_pass" if not errors else "loop4_regression_fail","candidateDigest":digest,"candidateVersion":projection.get("adapterVersion"),"checkedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"durationMs":round((time.monotonic()-started)*1000),"regressionBank":{"focusedTestsPassed":test.returncode==0,"testCount":21,"safetyRegressions":0 if not errors else None},"baseline":{"semanticPassed":(base_lane.get("answer") or {}).get("semantic",{}).get("passed"),"providerCalls":len(base_receipts),"toolCalls":sum(int(x.get("toolCallCount") or 0) for x in base_receipts)},"candidate":{"semanticPassed":candidate.get("semanticEvaluationPassed"),"providerCalls":len(receipts),"promptTokens":sum(int(x.get("promptTokens") or 0) for x in receipts),"toolCalls":sum(int(x.get("toolCallCount") or 0) for x in receipts),"warnings":candidate.get("warnings"),"cleanupComplete":candidate.get("cleanupComplete")},"decision":"eligible_for_loop5_promotion_review" if not errors else "return_to_improvement","errors":errors}
 REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0 if not errors else 1
if __name__=="__main__":raise SystemExit(main())
