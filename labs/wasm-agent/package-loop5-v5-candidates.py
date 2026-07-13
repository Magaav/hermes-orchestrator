#!/usr/bin/env python3
"""Package the frozen nine-strategy V5 matrix into independent immutable volumes."""
from __future__ import annotations
import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; LAB=Path(__file__).resolve().parent
STRATEGIES=LAB/"loop5-v5-strategies.json"; OUT=LAB/"loop5-v5-candidates.json"
AUTH="b9502d928b23f23007516f8457e5b6463d97e08e79317799ecdb04cfa11b4960"
def main():
 matrix=json.loads(STRATEGIES.read_text()); candidates=[]
 for item in matrix["variants"]:
  ordinal=item["slot"].rsplit("-",1)[-1]; volume=f"wasm-agent-v5-{item['strategy']}-{ordinal}"
  report=ROOT/f"reports/context/loop5/{item['slot']}-package.json"
  command=["python3",str(LAB/"package-master-frontier-v5-adapter.py"),"--variant-slot",item["slot"],"--strategy",item["strategy"],"--volume",volume,"--report",str(report)]
  done=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
  if done.returncode: raise SystemExit(f"{item['slot']} packaging failed: {done.stderr or done.stdout}")
  receipt=json.loads(report.read_text()); digest=receipt["artifactSha256"]
  candidates.append({"slot":f"harness-{int(ordinal):02d}","variantSlot":item["slot"],"id":f"master-frontier-v5-{ordinal}","displayName":item["strategy"],"strategy":item["strategy"],"hypothesis":item["hypothesis"],"executable":"python3","adapterVersion":receipt["version"],"adapterVolume":volume,"adapterArtifactSha256":digest,"candidateDigest":digest,"modelContractStatus":"verified","toolAuthorityStatus":"verified","toolAuthoritySha256":AUTH,"verificationArtifact":str(report.relative_to(ROOT)),"liveCommand":["python3","/adapter/master-frontier-v5-live-runner.py","--task","{task}"],"liveReady":True,"benchmarkReady":True,"promotionStatus":"loop4_pending"})
 payload={"schema":"wasm-agent.safe-lab.loop5-v5-candidates.v1","matrixId":matrix["matrixId"],"modelContract":{"model":"frank/GLM-5.2","toolAuthoritySha256":AUTH},"fixtureId":matrix["fixtureId"],"taskDigest":matrix["taskDigest"],"candidates":candidates,"status":"nine_artifacts_packaged_loop4_pending"}
 OUT.write_text(json.dumps(payload,indent=2)+"\n");print(json.dumps(payload,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
