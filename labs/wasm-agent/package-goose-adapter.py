#!/usr/bin/env python3
"""Package the official integrity-pinned Goose binary in an immutable volume."""
from __future__ import annotations
import hashlib, io, json, subprocess, tarfile, tempfile, time, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; VERSION="1.41.0"
URL=f"https://github.com/aaif-goose/goose/releases/download/v{VERSION}/goose-aarch64-unknown-linux-gnu.tar.bz2"
ASSET_SHA="01f57bbec56a62ed3903bf466d407e784c119aabface695f72d3f914dc90d410"
VOLUME="wasm-agent-adapter-goose-1-41-0-v2"; IMAGE="wasm-agent-frontier:latest"
RUNNER=ROOT/"labs/wasm-agent/goose-live-runner.py"; STAGING=ROOT/"labs/wasm-agent/staging/goose-package.tar"
REPORT=ROOT/"reports/context/latest/goose-adapter-package-result.json"

def run(c,**kw): return subprocess.run(c,capture_output=True,check=False,**kw)
def sha(p):
 d=hashlib.sha256()
 with p.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""): d.update(chunk)
 return d.hexdigest()
def import_tar(path):
 with path.open("rb") as f: r=subprocess.run(["docker","run","--rm","-i","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user","0","-v",f"{VOLUME}:/adapter","--entrypoint","tar",IMAGE,"--no-same-owner","--no-same-permissions","-xf","-","-C","/adapter"],stdin=f,capture_output=True,check=False)
 if r.returncode: raise RuntimeError(r.stderr.decode(errors="replace"))
def tree():
 s="import hashlib,json,pathlib; r=pathlib.Path('/adapter'); a=[(str(p.relative_to(r)),p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(r.rglob('*')) if p.is_file() and p.name!='adapter-package.json']; print(json.dumps({'fileCount':len(a),'totalBytes':sum(x[1] for x in a),'treeSha256':hashlib.sha256(json.dumps(a,separators=(',',':')).encode()).hexdigest()}))"
 r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","-v",f"{VOLUME}:/adapter:ro","--entrypoint","python3",IMAGE,"-c",s],text=True)
 if r.returncode: raise RuntimeError(r.stderr)
 return json.loads(r.stdout)
def preflight():
 r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","--user","10000:10000","--tmpfs","/tmp:rw,nosuid,nodev,noexec,size=64m","-e","HOME=/tmp/home","-e","GOOSE_PATH_ROOT=/tmp/goose","-e","GOOSE_DISABLE_KEYRING=1","-v",f"{VOLUME}:/adapter:ro","--entrypoint","/adapter/goose",IMAGE,"--version"],text=True)
 if r.returncode or VERSION not in r.stdout: raise RuntimeError(r.stderr or "Goose version preflight failed")
def receipt_file(receipt):
 payload=(json.dumps(receipt,indent=2)+"\n").encode(); STAGING.parent.mkdir(parents=True,exist_ok=True)
 with tarfile.open(STAGING,"w") as a:
  i=tarfile.TarInfo("adapter-package.json"); i.size=len(payload); i.mode=0o444; a.addfile(i,io.BytesIO(payload))
 import_tar(STAGING); STAGING.unlink(missing_ok=True)
def main():
 if not RUNNER.is_file(): raise SystemExit("Goose runner missing")
 if run(["docker","volume","inspect",VOLUME],text=True).returncode==0:
  r=run(["docker","run","--rm","--network","none","--read-only","--cap-drop","ALL","--security-opt","no-new-privileges","-v",f"{VOLUME}:/adapter:ro","--entrypoint","cat",IMAGE,"/adapter/adapter-package.json"],text=True)
  if r.returncode: raise SystemExit("refusing unreceipted Goose volume")
  receipt=json.loads(r.stdout)
  if receipt.get("tree")!=tree() or receipt.get("assetSha256")!=ASSET_SHA: raise SystemExit("refusing changed Goose volume")
  preflight(); REPORT.write_text(json.dumps({**receipt,"preflightVersionPassed":True},indent=2)+"\n"); print(REPORT.read_text()); return 0
 if run(["docker","volume","create",VOLUME],text=True).returncode: raise SystemExit("volume creation failed")
 started=time.monotonic()
 try:
  with tempfile.TemporaryDirectory() as td:
   asset=Path(td)/"goose.tar.bz2"; urllib.request.urlretrieve(URL,asset)
   if sha(asset)!=ASSET_SHA: raise RuntimeError("Goose release checksum mismatch")
   with tarfile.open(asset,"r:bz2") as src:
    member=next((m for m in src.getmembers() if m.isfile() and Path(m.name).name=="goose"),None)
    if not member: raise RuntimeError("Goose binary absent from release")
    data=src.extractfile(member).read()
   with tarfile.open(STAGING,"w") as out:
    i=tarfile.TarInfo("goose"); i.size=len(data); i.mode=0o555; out.addfile(i,io.BytesIO(data)); out.add(RUNNER,arcname="goose-live-runner.py",recursive=False)
   import_tar(STAGING); STAGING.unlink(missing_ok=True)
  tr=tree(); artifact=hashlib.sha256(json.dumps({"version":VERSION,"assetSha256":ASSET_SHA,"runnerSha256":sha(RUNNER),"tree":tr},sort_keys=True,separators=(",",":")).encode()).hexdigest()
  receipt={"schema":"wasm-agent.safe-lab.adapter-package.v1","adapter":"goose","version":VERSION,"volume":VOLUME,"artifactSha256":artifact,"tree":tr,"source":"official aaif-goose ARM64 GNU release plus safe-lab runner","sourceUrl":URL,"assetSha256":ASSET_SHA,"runnerSha256":sha(RUNNER),"secretsIncluded":False,"runtimeStateIncluded":False,"gooseConfigIncluded":False,"gooseSessionsIncluded":False}
  receipt_file(receipt); preflight(); report={**receipt,"preflightVersionPassed":True,"durationMs":round((time.monotonic()-started)*1000)}; REPORT.parent.mkdir(parents=True,exist_ok=True); REPORT.write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report,indent=2)); return 0
 except Exception as e:
  STAGING.unlink(missing_ok=True); run(["docker","volume","rm","-f",VOLUME],text=True); raise SystemExit(str(e))
if __name__=="__main__": raise SystemExit(main())
