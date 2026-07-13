#!/usr/bin/env python3
import json
from pathlib import Path
S=Path(__file__).with_name("openhands-live-runner.py").read_text()
R={"realCli":'"/adapter/venv/bin/openhands"',"headless":'"--headless"',"jsonl":'"--json"',"envOverride":'"--override-with-envs"',"exactModel":'"LLM_MODEL":"openai/glm-5.2"',"broker":'"LLM_BASE_URL":endpoint',"processRuntime":'"RUNTIME":"process"',"ephemeral":'"OH_PERSISTENCE_DIR":str(state)',"noRetries":'"LLM_NUM_RETRIES":"0"',"noVision":'"LLM_DISABLE_VISION":"true"',"finishAction":'event.get("tool_name") == "finish"',"finishMessage":'action.get("message")'}
checks={k:v in S for k,v in R.items()}; errors=[f"runner contract missing: {k}" for k,v in checks.items() if not v]
for x in ("/var/run/docker.sock","/home/ubuntu/.openhands","SANDBOX_REMOTE_RUNTIME_API_URL"):
    if x in S: errors.append(f"forbidden authority: {x}")
result={"schema":"wasm-agent.safe-lab.openhands-adapter-check.v1","ok":not errors,"checks":checks,"errors":errors}; print(json.dumps(result,indent=2)); raise SystemExit(0 if not errors else 1)
