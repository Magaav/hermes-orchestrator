#!/usr/bin/env python3
"""Run promoted V5 across the frozen seven-golden/two-holdout semantic suite."""
from __future__ import annotations
import argparse,json,sqlite3,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];LAB=Path(__file__).resolve().parent
OVERLAY=LAB/"staging/avatar-chat-adjudication-v3.sqlite3";REGISTRY=LAB/"harness-adapters.json";OUT=ROOT/"reports/context/latest/promoted-v5-fixture-suite-proof.json"
def main():
 parser=argparse.ArgumentParser();parser.add_argument("--candidate-adapter");args=parser.parse_args()
 started=time.monotonic();reg=json.loads(REGISTRY.read_text());adapter=reg["adapters"][0]
 if args.candidate_adapter: adapter=json.loads((ROOT/args.candidate_adapter).read_text())
 digest=adapter["adapterArtifactSha256"]
 conn=sqlite3.connect(OVERLAY);rows=conn.execute("select fixture_id,split from fixture_adjudication where decision='admit' and ranking_allowed=1 order by split,fixture_id").fetchall();conn.close()
 results=[];errors=[]
 for fixture_id,split in rows:
  report=ROOT/f"reports/context/suites/promoted-v5-{fixture_id}.json"
  cmd=["python3",str(LAB/"live-fixture-orchestrator.py"),"--slot","harness-01","--fixture-id",fixture_id,"--report",str(report.relative_to(ROOT))]
  if args.candidate_adapter:cmd.extend(["--candidate-adapter",args.candidate_adapter])
  done=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
  payload=json.loads(report.read_text()) if report.is_file() else {}
  task=payload.get("task") or {}; receipts=[x for x in payload.get("gatewayReceipts",[]) if x.get("status")==200]
  row={"fixtureId":fixture_id,"split":split,"ok":done.returncode==0 and payload.get("ok") is True,"classification":payload.get("classification"),"executionAllowed":(task.get("adjudication") or {}).get("executionAllowed"),"semanticPassed":payload.get("semanticEvaluationPassed"),"providerCalls":len(receipts),"toolCalls":sum(int(x.get("toolCallCount") or 0) for x in receipts),"promptTokens":sum(int(x.get("promptTokens") or 0) for x in receipts),"warnings":payload.get("warnings") or [],"taskDigest":task.get("taskDigest"),"artifactDigest":payload.get("adapterArtifactSha256"),"report":str(report.relative_to(ROOT))}
  if row["artifactDigest"]!=digest:row["ok"]=False;row.setdefault("errors",[]).append("promoted artifact digest mismatch")
  if not row["ok"]:errors.append(f"{fixture_id} failed or was not executable")
  results.append(row)
 golden=[x for x in results if x["split"]=="golden"];holdout=[x for x in results if x["split"]=="holdout"]
 result={"schema":"wasm-agent.safe-lab.promoted-v5-suite-proof.v1","ok":not errors,"classification":"promoted_v5_suite_pass" if not errors else "promoted_v5_suite_fail","checkedAt":datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),"durationMs":round((time.monotonic()-started)*1000),"adapterVersion":adapter["adapterVersion"],"artifactDigest":digest,"fixtureCount":len(results),"golden":{"passed":sum(x["ok"] for x in golden),"total":len(golden)},"holdout":{"passed":sum(x["ok"] for x in holdout),"total":len(holdout)},"semanticPassRate":sum(x["semanticPassed"] is True for x in results)/len(results) if results else 0,"results":results,"errors":errors};OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,indent=2)+"\n");print(json.dumps(result,indent=2));return 0 if not errors else 1
if __name__=="__main__":raise SystemExit(main())
