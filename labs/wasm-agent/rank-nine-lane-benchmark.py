#!/usr/bin/env python3
"""Rank a proven nine-lane benchmark without weakening semantic gates."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from efficiency_policy import warnings_for

def inverse(values, value):
    low,high=min(values),max(values)
    return 1.0 if high==low else 1.0-(value-low)/(high-low)

def main():
    p=argparse.ArgumentParser();p.add_argument("report");p.add_argument("--output",default="reports/context/latest/nine-lane-ranking-result.json");a=p.parse_args()
    report=json.loads(Path(a.report).read_text()); errors=[]
    if report.get("status")!="benchmark_complete" or report.get("semanticAllPassed") is not True or report.get("rankingAllowed") is not True: errors.append("benchmark is not admitted for ranking")
    results=report.get("results") or []; receipts=report.get("gatewayReceipts") or []; task=report.get("task") or {}
    slots={x.get("slot") for x in results}; attributed={x.get("laneId") for x in receipts}
    if len(results)!=9 or slots!={f"harness-{i:02d}" for i in range(1,10)}: errors.append("nine unique lanes required")
    if not attributed.issubset(slots) or not slots.issubset(attributed): errors.append("every receipt must have an exact registered lane attribution")
    rows=[]
    for item in results:
        lane=item.get("lane") or {}; slot=item.get("slot"); own=[x for x in receipts if x.get("laneId")==slot and x.get("status")==200 and x.get("upstreamCalled")]
        semantic=(item.get("answer") or {}).get("semantic") or {}
        warnings=warnings_for(task,own)
        rows.append({"slot":slot,"adapter":lane.get("adapter"),"semanticPassed":semantic.get("passed") is True,"latencyMs":int(lane.get("durationMs") or 0),"promptTokens":sum(int(x.get("promptTokens") or 0) for x in own),"completionTokens":sum(int(x.get("completionTokens") or 0) for x in own),"providerCalls":len(own),"toolCalls":sum(int(x.get("toolCallCount") or 0) for x in own),"warnings":warnings})
    if any(not x["semanticPassed"] for x in rows): errors.append("semantic failure forbids ranking")
    if errors:
        out={"schema":"wasm-agent.safe-lab.nine-lane-ranking.v1","ok":False,"errors":errors};print(json.dumps(out,indent=2));return 1
    lat=[x["latencyMs"] for x in rows];prompt=[x["promptTokens"] for x in rows];calls=[x["providerCalls"] for x in rows];tools=[x["toolCalls"] for x in rows];warn=[len(x["warnings"]) for x in rows]
    for x in rows:
        parts={"latency":35*inverse(lat,x["latencyMs"]),"promptEfficiency":30*inverse(prompt,x["promptTokens"]),"callEfficiency":15*inverse(calls,x["providerCalls"]),"toolEfficiency":10*inverse(tools,x["toolCalls"]),"warningCleanliness":10*inverse(warn,len(x["warnings"]))}
        x["scoreParts"]={k:round(v,3) for k,v in parts.items()};x["efficiencyScore"]=round(sum(parts.values()),3)
    rows.sort(key=lambda x:(-x["efficiencyScore"],x["latencyMs"],x["adapter"]))
    for i,x in enumerate(rows,1):x["rank"]=i
    leaders=[x["adapter"] for x in rows[:3]]
    out={"schema":"wasm-agent.safe-lab.nine-lane-ranking.v1","ok":True,"classification":"nine_lane_ranking_pass","sourceRunId":report.get("runId"),"semanticGate":"all_passed","weights":{"latency":35,"promptEfficiency":30,"callEfficiency":15,"toolEfficiency":10,"warningCleanliness":10},"ranking":rows,"goldenPatternCandidates":[{"pattern":"direct_semantic_answer","evidence":"All ranked lanes passed the same private semantic contract."},{"pattern":"single_provider_call","leaders":[x["adapter"] for x in rows if x["providerCalls"]==1]},{"pattern":"zero_nonterminal_tools","leaders":[x["adapter"] for x in rows if x["toolCalls"]==0]},{"pattern":"compact_context_and_low_latency","leaders":leaders}],"promotionDecision":"candidate_patterns_only_loop4_regression_required"}
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
