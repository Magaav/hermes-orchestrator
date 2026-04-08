#!/usr/bin/env bash
set -euo pipefail

: "${OPENVIKING_CONFIG_FILE:=/etc/openviking/ov.conf}"
: "${OPENVIKING_EFFECTIVE_CONFIG_FILE:=/var/run/openviking/ov.effective.conf}"
: "${OPENVIKING_LOG_DIR:=/var/log/openviking}"
: "${OPENVIKING_HOST:=0.0.0.0}"
: "${OPENVIKING_PORT:=1933}"
: "${OPENVIKING_AUTH_MODE:=trusted}"
: "${OPENVIKING_ROOT_API_KEY:=}"
: "${OPENVIKING_STORAGE_WORKSPACE:=/data}"

: "${OPENVIKING_DEFAULT_ACCOUNT:=colmeio}"
: "${OPENVIKING_DEFAULT_USER:=colmeio}"
: "${OPENVIKING_DEFAULT_AGENT:=colmeio}"

: "${OPENVIKING_REQUIRE_NVIDIA_KEY:=1}"
: "${NVIDIA_API_KEY:=}"
: "${NVIDIA_NIM_API_KEY:=}"

: "${OPENVIKING_EMBEDDING_MODEL_KIND:=text}"
: "${OPENVIKING_EMBEDDING_TEXT_MODEL:=nvidia/llama-nemotron-embed-1b-v2}"
: "${OPENVIKING_EMBEDDING_MULTIMODAL_MODEL:=nvidia/llama-nemotron-embed-vl-1b-v2}"
: "${OPENVIKING_EMBEDDING_TEXT_DIM:=2048}"
: "${OPENVIKING_EMBEDDING_MULTIMODAL_DIM:=2048}"
: "${OPENVIKING_EMBEDDING_API_BASE:=https://integrate.api.nvidia.com/v1}"
: "${OPENVIKING_EMBEDDING_QUERY_PARAM:=query}"
: "${OPENVIKING_EMBEDDING_DOCUMENT_PARAM:=passage}"
: "${OPENVIKING_EMBEDDING_MAX_RETRIES:=3}"
: "${OPENVIKING_EMBEDDING_TEXT_SOURCE:=summary_first}"

: "${OPENVIKING_ENABLE_RERANK:=1}"
: "${OPENVIKING_RERANK_MODEL_KIND:=text}"
: "${OPENVIKING_RERANK_TEXT_MODEL:=nvidia/llama-nemotron-rerank-1b-v2}"
: "${OPENVIKING_RERANK_MULTIMODAL_MODEL:=nvidia/llama-nemotron-rerank-vl-1b-v2}"
: "${OPENVIKING_RERANK_API_BASE:=https://ai.api.nvidia.com/v1}"
: "${OPENVIKING_RERANK_THRESHOLD:=0.1}"

: "${OPENVIKING_VLM_MODEL:=nvidia/llama-3.1-nemotron-nano-vl-8b-v1}"
: "${OPENVIKING_VLM_API_BASE:=https://integrate.api.nvidia.com/v1}"
: "${OPENVIKING_VLM_MAX_RETRIES:=3}"

: "${OPENVIKING_PDF_STRATEGY:=local}"
: "${OPENVIKING_PARSE_ENDPOINT:=}"
: "${OPENVIKING_PARSE_API_KEY:=}"
: "${OPENVIKING_PARSER_MAX_SECTION_SIZE:=1000}"
: "${OPENVIKING_PARSER_SECTION_FLEXIBILITY:=0.3}"
: "${OPENVIKING_PARSER_MAX_SECTION_CHARS:=6000}"

: "${OPENVIKING_STARTUP_MODEL_PROBE:=1}"
: "${OPENVIKING_STRICT_MODEL_PROBE:=0}"

mkdir -p "$(dirname "$OPENVIKING_EFFECTIVE_CONFIG_FILE")" "$OPENVIKING_STORAGE_WORKSPACE" "$OPENVIKING_LOG_DIR"

BOOTSTRAP_LOG="$OPENVIKING_LOG_DIR/bootstrap.log"
SERVER_LOG="$OPENVIKING_LOG_DIR/server.log"

log_json() {
  local level="$1"
  local event="$2"
  local message="$3"
  python3 - "$BOOTSTRAP_LOG" "$level" "$event" "$message" <<'PY'
import datetime
import json
import sys

path, level, event, message = sys.argv[1:5]
payload = {
    "ts": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    "level": level,
    "event": event,
    "message": message,
}
line = json.dumps(payload, ensure_ascii=False)
print(line)
with open(path, "a", encoding="utf-8") as handle:
    handle.write(line + "\n")
PY
}

is_truthy() {
  case "${1,,}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

if ! [[ "$OPENVIKING_PORT" =~ ^[0-9]+$ ]]; then
  log_json "error" "validate.port" "OPENVIKING_PORT must be an integer (got: $OPENVIKING_PORT)"
  exit 1
fi

if [[ ! -f "$OPENVIKING_CONFIG_FILE" ]]; then
  log_json "error" "validate.config" "OpenViking config template not found: $OPENVIKING_CONFIG_FILE"
  exit 1
fi

if is_truthy "$OPENVIKING_REQUIRE_NVIDIA_KEY" && [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  log_json "error" "validate.env" "NVIDIA_API_KEY is required (OPENVIKING_REQUIRE_NVIDIA_KEY=1)"
  exit 1
fi

# Keep one key source-of-truth while satisfying LiteLLM's NVIDIA NIM provider
# expectations for rerank.
if [[ -z "${NVIDIA_NIM_API_KEY:-}" && -n "${NVIDIA_API_KEY:-}" ]]; then
  export NVIDIA_NIM_API_KEY="$NVIDIA_API_KEY"
fi

EMBED_KIND="${OPENVIKING_EMBEDDING_MODEL_KIND,,}"
if [[ "$EMBED_KIND" == "multimodal" || "$EMBED_KIND" == "vl" ]]; then
  export OPENVIKING_EMBEDDING_MODEL="$OPENVIKING_EMBEDDING_MULTIMODAL_MODEL"
  export OPENVIKING_EMBEDDING_DIMENSION="$OPENVIKING_EMBEDDING_MULTIMODAL_DIM"
else
  export OPENVIKING_EMBEDDING_MODEL="$OPENVIKING_EMBEDDING_TEXT_MODEL"
  export OPENVIKING_EMBEDDING_DIMENSION="$OPENVIKING_EMBEDDING_TEXT_DIM"
fi

RERANK_KIND="${OPENVIKING_RERANK_MODEL_KIND,,}"
if [[ "$RERANK_KIND" == "multimodal" || "$RERANK_KIND" == "vl" ]]; then
  export OPENVIKING_RERANK_MODEL="$OPENVIKING_RERANK_MULTIMODAL_MODEL"
else
  export OPENVIKING_RERANK_MODEL="$OPENVIKING_RERANK_TEXT_MODEL"
fi

# LiteLLM rerank for NVIDIA expects provider-qualified model names.
# Keep operator-facing defaults in NVIDIA form and normalize here.
case "${OPENVIKING_RERANK_MODEL}" in
  nvidia/*)
    export OPENVIKING_RERANK_MODEL="nvidia_nim/${OPENVIKING_RERANK_MODEL}"
    ;;
esac

python3 - "$OPENVIKING_CONFIG_FILE" "$OPENVIKING_EFFECTIVE_CONFIG_FILE" <<'PY'
import json
import os
import sys
from pathlib import Path

template_path = Path(sys.argv[1])
effective_path = Path(sys.argv[2])

raw = os.path.expandvars(template_path.read_text(encoding="utf-8"))
cfg = json.loads(raw)
if not isinstance(cfg, dict):
    raise SystemExit("ov.conf template must be a JSON object")

server = cfg.get("server")
if not isinstance(server, dict):
    server = {}
cfg["server"] = server
server["host"] = os.environ["OPENVIKING_HOST"]
server["port"] = int(os.environ["OPENVIKING_PORT"])
server["auth_mode"] = os.environ["OPENVIKING_AUTH_MODE"]
server["workers"] = int(str(server.get("workers", 1) or 1))
if str(os.environ.get("OPENVIKING_ROOT_API_KEY", "") or "").strip():
    server["root_api_key"] = os.environ["OPENVIKING_ROOT_API_KEY"]
else:
    server.pop("root_api_key", None)

cfg["default_account"] = os.environ["OPENVIKING_DEFAULT_ACCOUNT"]
cfg["default_user"] = os.environ["OPENVIKING_DEFAULT_USER"]
cfg["default_agent"] = os.environ["OPENVIKING_DEFAULT_AGENT"]

storage = cfg.get("storage")
if not isinstance(storage, dict):
    storage = {}
cfg["storage"] = storage
storage["workspace"] = os.environ["OPENVIKING_STORAGE_WORKSPACE"]

embedding = cfg.get("embedding")
if not isinstance(embedding, dict):
    embedding = {}
cfg["embedding"] = embedding
dense = embedding.get("dense")
if not isinstance(dense, dict):
    dense = {}
embedding["dense"] = dense
dense["provider"] = "openai"
dense["model"] = os.environ["OPENVIKING_EMBEDDING_MODEL"]
dense["dimension"] = int(os.environ["OPENVIKING_EMBEDDING_DIMENSION"])
dense["api_base"] = os.environ["OPENVIKING_EMBEDDING_API_BASE"]
dense["api_key"] = os.environ.get("NVIDIA_API_KEY", "")
dense["query_param"] = os.environ.get("OPENVIKING_EMBEDDING_QUERY_PARAM", "query")
dense["document_param"] = os.environ.get("OPENVIKING_EMBEDDING_DOCUMENT_PARAM", "passage")
embedding["max_retries"] = int(os.environ.get("OPENVIKING_EMBEDDING_MAX_RETRIES", "3"))
embedding["text_source"] = os.environ.get("OPENVIKING_EMBEDDING_TEXT_SOURCE", "summary_first")

vlm = cfg.get("vlm")
if not isinstance(vlm, dict):
    vlm = {}
cfg["vlm"] = vlm
vlm["model"] = os.environ["OPENVIKING_VLM_MODEL"]
vlm["provider"] = "openai"
vlm["api_key"] = os.environ.get("NVIDIA_API_KEY", "")
vlm["api_base"] = os.environ["OPENVIKING_VLM_API_BASE"]
vlm["max_retries"] = int(os.environ.get("OPENVIKING_VLM_MAX_RETRIES", "3"))
providers = vlm.get("providers")
if not isinstance(providers, dict):
    providers = {}
vlm["providers"] = providers
providers["openai"] = {
    "api_key": os.environ.get("NVIDIA_API_KEY", ""),
    "api_base": os.environ["OPENVIKING_VLM_API_BASE"],
}

enable_rerank = str(os.environ.get("OPENVIKING_ENABLE_RERANK", "1") or "").strip().lower() in {"1", "true", "yes", "on"}
if enable_rerank:
    rerank = cfg.get("rerank")
    if not isinstance(rerank, dict):
        rerank = {}
    cfg["rerank"] = rerank
    rerank["provider"] = "litellm"
    rerank["api_key"] = os.environ.get("NVIDIA_NIM_API_KEY", "") or os.environ.get("NVIDIA_API_KEY", "")
    rerank["api_base"] = os.environ["OPENVIKING_RERANK_API_BASE"]
    rerank["model"] = os.environ["OPENVIKING_RERANK_MODEL"]
    rerank["threshold"] = float(os.environ.get("OPENVIKING_RERANK_THRESHOLD", "0.1"))
else:
    cfg["rerank"] = {}

parsers = cfg.get("parsers")
if not isinstance(parsers, dict):
    parsers = {}
cfg["parsers"] = parsers
markdown = parsers.get("markdown")
if not isinstance(markdown, dict):
    markdown = {}
parsers["markdown"] = markdown
markdown["max_section_size"] = int(os.environ.get("OPENVIKING_PARSER_MAX_SECTION_SIZE", "1000"))
markdown["section_size_flexibility"] = float(os.environ.get("OPENVIKING_PARSER_SECTION_FLEXIBILITY", "0.3"))
markdown["max_section_chars"] = int(os.environ.get("OPENVIKING_PARSER_MAX_SECTION_CHARS", "6000"))

code = parsers.get("code")
if not isinstance(code, dict):
    code = {}
parsers["code"] = code
code["max_section_size"] = int(os.environ.get("OPENVIKING_PARSER_MAX_SECTION_SIZE", "1000"))
code["section_size_flexibility"] = float(os.environ.get("OPENVIKING_PARSER_SECTION_FLEXIBILITY", "0.3"))
code["max_section_chars"] = int(os.environ.get("OPENVIKING_PARSER_MAX_SECTION_CHARS", "6000"))
code["code_summary_mode"] = str(code.get("code_summary_mode", "ast"))

pdf = parsers.get("pdf")
if not isinstance(pdf, dict):
    pdf = {}
parsers["pdf"] = pdf
pdf["strategy"] = os.environ.get("OPENVIKING_PDF_STRATEGY", "local")
parse_endpoint = str(os.environ.get("OPENVIKING_PARSE_ENDPOINT", "") or "").strip()
if parse_endpoint:
    pdf["mineru_endpoint"] = parse_endpoint
parse_api_key = str(os.environ.get("OPENVIKING_PARSE_API_KEY", "") or "").strip()
if parse_api_key:
    pdf["mineru_api_key"] = parse_api_key

cfg["default_search_mode"] = str(cfg.get("default_search_mode", "thinking") or "thinking")
cfg["default_search_limit"] = int(str(cfg.get("default_search_limit", 8) or 8))

effective_path.parent.mkdir(parents=True, exist_ok=True)
effective_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if ! touch "$OPENVIKING_STORAGE_WORKSPACE/.ov-write-check"; then
  log_json "error" "validate.storage" "storage workspace is not writable: $OPENVIKING_STORAGE_WORKSPACE"
  exit 1
fi
rm -f "$OPENVIKING_STORAGE_WORKSPACE/.ov-write-check" || true

if is_truthy "$OPENVIKING_STARTUP_MODEL_PROBE"; then
  set +e
  python3 - <<'PY'
import json
import os
import sys
import requests

strict = str(os.environ.get("OPENVIKING_STRICT_MODEL_PROBE", "0")).strip().lower() in {"1", "true", "yes", "on"}
api_key = str(os.environ.get("NVIDIA_API_KEY", "") or "").strip()
nim_api_key = str(os.environ.get("NVIDIA_NIM_API_KEY", "") or api_key).strip()
embedding_base = str(os.environ.get("OPENVIKING_EMBEDDING_API_BASE", "") or "").rstrip("/")
embedding_model = str(os.environ.get("OPENVIKING_EMBEDDING_MODEL", "") or "").strip()
rerank_enabled = str(os.environ.get("OPENVIKING_ENABLE_RERANK", "1") or "").strip().lower() in {"1", "true", "yes", "on"}
rerank_base = str(os.environ.get("OPENVIKING_RERANK_API_BASE", "") or "").strip()
rerank_model = str(os.environ.get("OPENVIKING_RERANK_MODEL", "") or "").strip()

errors = []
if api_key and embedding_base and embedding_model:
    url = f"{embedding_base}/embeddings"
    payload = {"model": embedding_model, "input": ["openviking startup probe"], "input_type": "query"}
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if resp.status_code >= 300:
            errors.append(f"embedding probe failed [{resp.status_code}] {resp.text[:120]}")
    except Exception as exc:
        errors.append(f"embedding probe exception: {exc}")

if rerank_enabled and nim_api_key and rerank_model:
    try:
        import litellm

        os.environ.setdefault("NVIDIA_NIM_API_KEY", nim_api_key)
        os.environ.setdefault("NVIDIA_NIM_API_BASE", rerank_base or "https://ai.api.nvidia.com/v1")
        response = litellm.rerank(
            model=rerank_model,
            query="milk shortage",
            documents=[{"text": "buy milk now"}, {"text": "book accounting review"}],
            api_key=nim_api_key,
            api_base=rerank_base or "https://ai.api.nvidia.com/v1",
        )
        results = getattr(response, "results", None)
        if not results:
            errors.append("rerank probe failed: empty results")
    except Exception as exc:
        errors.append(f"rerank probe exception: {exc}")

payload = {"strict": strict, "errors": errors}
print(json.dumps(payload, ensure_ascii=False))
if strict and errors:
    sys.exit(1)
PY
  model_probe_rc=$?
  set -e
  if [[ $model_probe_rc -ne 0 ]]; then
    log_json "error" "startup.model_probe" "strict model probe failed"
    exit 1
  fi
fi

log_json "info" "startup.ready" "starting openviking-server with effective config $OPENVIKING_EFFECTIVE_CONFIG_FILE"

set +e
openviking-server \
  --host "$OPENVIKING_HOST" \
  --port "$OPENVIKING_PORT" \
  --config "$OPENVIKING_EFFECTIVE_CONFIG_FILE" \
  2>&1 | tee -a "$SERVER_LOG"
rc=${PIPESTATUS[0]}
set -e

if [[ $rc -ne 0 ]]; then
  log_json "error" "startup.exit" "openviking-server exited with code $rc"
else
  log_json "info" "startup.exit" "openviking-server exited cleanly"
fi
exit $rc
