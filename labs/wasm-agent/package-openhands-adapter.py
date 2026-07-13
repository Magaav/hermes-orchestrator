#!/usr/bin/env python3
"""Package official OpenHands in an immutable credential-free Python volume."""
from __future__ import annotations
import hashlib,io,json,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; VERSION="1.16.0"; SPEC=f"openhands=={VERSION}"; WHEEL_SHA="e5495ddc76bff6ad8cf332b2e366c665f6735da31bc60fba9d430e19d11ffd3d"
VOLUME="wasm-agent-adapter-openhands-1-16-0-v2"; IMAGE="wasm-agent-frontier:latest"; RUNNER=ROOT/"labs/wasm-agent/openhands-live-runner.py"; STAGING=ROOT/"labs/wasm-agent/staging/openhands-runner.tar"; REPORT=ROOT/"reports/context/latest/openhands-adapter-package-result.json"
def run(c,**kw): return subprocess.run(c,capture_output=True,check=False,**kw)
def sha(p):
 d=hashlib.sha256();
 with p.open("rb") as f:
  for x in iter(lambda:f.read(1048576),b""): d.update(x)
 return d.hexdigest()
def tree():
 s="import hashlib,json,pathlib; r=pathlib.Path('/adapter'); a=[(str(p.relative_to(r)),p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(r.rglob('*')) if p.is_file() and p.name!='adapter-package.json']; print(json.dumps({'fileCount':len(a),'totalBytes':sum(x[1] for x in a),'treeSha256':hashlib.sha256(json.dumps(a,separators=(',',':')).encode()).hexdigest()}))"
 r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","-v",f"{VOLUME}:/adapter:ro","--entrypoint","python3",IMAGE,"-c",s],text=True)
 if r.returncode: raise RuntimeError(r.stderr)
 return json.loads(r.stdout)
def freeze():
 r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user","10000:10000","-v",f"{VOLUME}:/adapter:ro","--entrypoint","/adapter/venv/bin/pip",IMAGE,"freeze","--all"],text=True)
 if r.returncode: raise RuntimeError(r.stderr)
 return hashlib.sha256(r.stdout.encode()).hexdigest()
def import_tar():
 with STAGING.open("rb") as f:r=subprocess.run(["docker","run","--rm","-i","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user","0","-v",f"{VOLUME}:/adapter","--entrypoint","tar",IMAGE,"--no-same-owner","--no-same-permissions","-xf","-","-C","/adapter"],stdin=f,capture_output=True)
 if r.returncode: raise RuntimeError(r.stderr.decode(errors="replace"))
 STAGING.unlink(missing_ok=True)
def preflight():
 r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user","10000:10000","--tmpfs","/tmp:rw,nosuid,nodev,noexec,size=64m","-e","HOME=/tmp/home","-e","OH_PERSISTENCE_DIR=/tmp/state","-v",f"{VOLUME}:/adapter:ro","--entrypoint","/adapter/venv/bin/openhands",IMAGE,"--version"],text=True)
 if r.returncode or VERSION not in r.stdout: raise RuntimeError(r.stderr or "OpenHands preflight failed")
def receipt_file(receipt):
 payload=(json.dumps(receipt,indent=2)+"\n").encode(); STAGING.parent.mkdir(parents=True,exist_ok=True)
 with tarfile.open(STAGING,"w") as a:i=tarfile.TarInfo("adapter-package.json");i.size=len(payload);i.mode=0o444;a.addfile(i,io.BytesIO(payload))
 import_tar()
def main():
 if not RUNNER.is_file(): raise SystemExit("OpenHands runner missing")
 if run(["docker","volume","inspect",VOLUME],text=True).returncode==0:
  r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","-v",f"{VOLUME}:/adapter:ro","--entrypoint","cat",IMAGE,"/adapter/adapter-package.json"],text=True)
  if r.returncode: raise SystemExit("refusing unreceipted OpenHands volume")
  q=json.loads(r.stdout)
  if q.get("tree")!=tree() or q.get("dependencyFreezeSha256")!=freeze(): raise SystemExit("refusing changed OpenHands volume")
  preflight(); REPORT.write_text(json.dumps({**q,"preflightVersionPassed":True},indent=2)+"\n");print(REPORT.read_text());return 0
 if run(["docker","volume","create",VOLUME],text=True).returncode: raise SystemExit("volume creation failed")
 started=time.monotonic()
 try:
  r=run(["docker","run","--rm","--network","none","--user","0","-v",f"{VOLUME}:/adapter","--entrypoint","python3",IMAGE,"-m","venv","/adapter/venv"],text=True)
  if r.returncode: raise RuntimeError(r.stderr)
  r=run(["docker","run","--rm","--network","bridge","--user","0","-v",f"{VOLUME}:/adapter","--entrypoint","/adapter/venv/bin/pip",IMAGE,"install","--no-cache-dir","--disable-pip-version-check","uv"],text=True)
  if r.returncode: raise RuntimeError(r.stderr)
  r=run(["docker","run","--rm","--network","bridge","--user","0","-v",f"{VOLUME}:/adapter","--entrypoint","/adapter/venv/bin/uv",IMAGE,"pip","install","--python","/adapter/venv/bin/python",SPEC],text=True)
  if r.returncode: raise RuntimeError(r.stderr)
  with tarfile.open(STAGING,"w") as a:a.add(RUNNER,arcname="openhands-live-runner.py",recursive=False)
  import_tar(); tr=tree(); fr=freeze(); artifact=hashlib.sha256(json.dumps({"version":VERSION,"wheelSha256":WHEEL_SHA,"runnerSha256":sha(RUNNER),"tree":tr,"dependencyFreezeSha256":fr},sort_keys=True,separators=(",",":")).encode()).hexdigest()
  q={"schema":"wasm-agent.safe-lab.adapter-package.v1","adapter":"openhands","version":VERSION,"volume":VOLUME,"artifactSha256":artifact,"tree":tr,"dependencyFreezeSha256":fr,"wheelSha256":WHEEL_SHA,"runnerSha256":sha(RUNNER),"source":"official openhands PyPI distribution in isolated venv plus safe-lab runner","packageSpec":SPEC,"secretsIncluded":False,"runtimeStateIncluded":False,"openhandsConfigIncluded":False,"openhandsConversationsIncluded":False};receipt_file(q);preflight();q={**q,"preflightVersionPassed":True,"durationMs":round((time.monotonic()-started)*1000)};REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(q,indent=2)+"\n");print(json.dumps(q,indent=2));return 0
 except Exception as e: STAGING.unlink(missing_ok=True);run(["docker","volume","rm","-f",VOLUME],text=True);raise SystemExit(str(e))
if __name__=="__main__":raise SystemExit(main())
