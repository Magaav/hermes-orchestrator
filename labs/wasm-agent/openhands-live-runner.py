#!/usr/bin/env python3
"""OpenHands adapter for the canonical safe-lab fixture task."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

def text_parts(value):
    if isinstance(value, str): return [value]
    if isinstance(value, list): return [p for item in value for p in text_parts(item)]
    if isinstance(value, dict):
        parts=[]
        for key in ("text","content","message","llm_message"):
            if key in value: parts.extend(text_parts(value[key]))
        return parts
    return []

def main():
    p=argparse.ArgumentParser(); p.add_argument("--task",required=True); args=p.parse_args()
    task=json.loads(Path(args.task).read_text()); endpoint=os.environ.get("FRONTIER_ENDPOINT","").rstrip("/"); token=os.environ.get("OPENAI_API_KEY","")
    if task.get("schema")!="wasm-agent.safe-lab.fixture-task.v1" or not task.get("taskDigest"): raise SystemExit("invalid digest-bound fixture task")
    if os.environ.get("FRONTIER_MODEL")!="frank/GLM-5.2" or not endpoint or not token: raise SystemExit("exact brokered model contract missing")
    home=Path("/workspace/openhands-home"); state=Path("/workspace/openhands-state"); home.mkdir(parents=True,exist_ok=True); state.mkdir(parents=True,exist_ok=True)
    budgets=task.get("budgets") or {}; env=dict(os.environ); env.update({
      "HOME":str(home),"XDG_CONFIG_HOME":str(home/"config"),"XDG_DATA_HOME":str(home/"data"),"XDG_CACHE_HOME":str(home/"cache"),"OH_PERSISTENCE_DIR":str(state),
      "LLM_MODEL":"openai/glm-5.2","LLM_API_KEY":token,"LLM_BASE_URL":endpoint,"LLM_MAX_OUTPUT_TOKENS":str(int(budgets.get("maxOutputTokensPerCall") or 1024)),
      "LLM_NUM_RETRIES":"0","LLM_DISABLE_VISION":"true","LLM_CACHING_PROMPT":"false","RUNTIME":"process","LOCAL_RUNTIME_MODE":"1","NO_COLOR":"1","DISABLE_TELEMETRY":"true"
    })
    cmd=["/adapter/venv/bin/openhands","--headless","--json","--override-with-envs","--exit-without-confirmation","--task",str(task.get("prompt") or "")]
    done=subprocess.run(cmd,cwd="/workspace",env=env,capture_output=True,text=True,check=False)
    if done.returncode:
        print((done.stderr or "OpenHands failed").replace(token,"[redacted]")[-2000:],file=sys.stderr); return done.returncode
    answers=[]
    for line in done.stdout.splitlines():
        try: event=json.loads(line)
        except json.JSONDecodeError: continue
        if event.get("source") == "agent" and event.get("tool_name") == "finish":
            action = event.get("action") if isinstance(event.get("action"), dict) else {}
            if isinstance(action.get("message"), str) and action["message"].strip():
                answers.append(action["message"].strip())
                continue
        marker=" ".join(str(event.get(k,"")).lower() for k in ("kind","type","source","role"))
        if ("agent" in marker or "assistant" in marker) and ("message" in marker or "agent" in marker):
            candidate="\n".join(x.strip() for x in text_parts(event) if x.strip())
            if candidate: answers.append(candidate)
    if not answers: print("OpenHands final agent message was absent from JSONL output.",file=sys.stderr); return 1
    print(answers[-1]); return 0
if __name__=="__main__": raise SystemExit(main())
