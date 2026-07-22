#!/usr/bin/env python3
"""Produce independent exact-digest Loop 4 rows for the nine V5 variants."""
from __future__ import annotations
import json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from loop5_candidate_policy import summarize_matrix
ROOT=Path(__file__).resolve().parents[2];LAB=Path(__file__).resolve().parent
RUN=LAB/"staging/loop5-v5-nine-20260712b-improve-nine-lane.json"; MANIFEST=LAB/"loop5-v5-candidates.json"; OUT=ROOT/"reports/context/latest/loop4-loop5-v5-matrix-proof.json"
def main():
 started=time.monotonic();run=json.loads(RUN.read_text());manifest=json.loads(MANIFEST.read_text());errors=[];rows=[]
 test=subprocess.run(["python3","plugins/wasm-agent/tests/master_frontier_v5.test.py"],cwd=ROOT,capture_output=True,text=True)
 if test.returncode:errors.append("shared focused regression bank failed")
 results={x["slot"]:x for x in run.get("results",[])}; receipts=run.get("gatewayReceipts",[])
 for candidate in manifest["candidates"]:
  slot=candidate["slot"];lane=results.get(slot,{}) ; own=[x for x in receipts if x.get("laneId")==slot and x.get("status")==200]
  package=json.loads((ROOT/candidate["verificationArtifact"]).read_text()); digest=candidate["candidateDigest"]; row_errors=[]
  if digest!=candidate.get("adapterArtifactSha256") or digest!=package.get("artifactSha256"):row_errors.append("artifact digest mismatch")
  if package.get("volume")!=candidate.get("adapterVolume") or (package.get("variant") or {}).get("strategy")!=candidate.get("strategy"):row_errors.append("volume/strategy receipt mismatch")
  if (lane.get("answer") or {}).get("semantic",{}).get("passed") is not True:row_errors.append("semantic regression")
  if len(own)!=1 or sum(int(x.get("toolCallCount") or 0) for x in own)!=0:row_errors.append("direct-completion cost regression")
  if (lane.get("lane") or {}).get("task",{}).get("taskDigest")!=manifest.get("taskDigest"):row_errors.append("task digest mismatch")
  if test.returncode:row_errors.append("shared focused regression bank failed")
  rows.append({"slot":slot,"variantSlot":candidate["variantSlot"],"strategy":candidate["strategy"],"candidateDigest":digest,"loop4Passed":not row_errors and test.returncode==0,"semanticPassed":(lane.get("answer") or {}).get("semantic",{}).get("passed"),"providerCalls":len(own),"toolCalls":sum(int(x.get("toolCallCount") or 0) for x in own),"promptTokens":sum(int(x.get("promptTokens") or 0) for x in own),"completionTokens":sum(int(x.get("completionTokens") or 0) for x in own),"latencyMs":int((lane.get("lane") or {}).get("durationMs") or 0),"proofRef":f"reports/context/loop5/{candidate['variantSlot']}-loop4.json","errors":row_errors})
  proof_path=ROOT/rows[-1]["proofRef"];proof_path.parent.mkdir(parents=True,exist_ok=True);proof_path.write_text(json.dumps({"schema":"wasm-agent.safe-lab.loop4-candidate-proof.v1",**rows[-1]},indent=2)+"\n")
 matrix=summarize_matrix(rows,global_errors=errors)
 result={"schema":"wasm-agent.safe-lab.loop4-matrix-proof.v1","matrixId":manifest["matrixId"],"sourceRunId":run["runId"],"checkedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"durationMs":round((time.monotonic()-started)*1000),"regressionBank":{"focusedTestsPassed":test.returncode==0,"testCount":22,"safetyRegressions":0 if test.returncode==0 else None},**matrix};OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0 if result["ok"] else 1
if __name__=="__main__":raise SystemExit(main())
