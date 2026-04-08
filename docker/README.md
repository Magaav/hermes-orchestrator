# OpenViking Service for Hermes Agents

This directory contains a production-oriented OpenViking deployment for Hermes multi-agent nodes.

- Compose entrypoint: `/local/docker/compose.yml`
- Runtime env: `/local/docker/.env`
- OpenViking config template: `/local/docker/containers.conf/openviking/ov.conf`
- Docker image artifacts: `/local/docker/dockerfiles/`
- Logs (host volume): `/local/logs/openviking/`
- Persistent memory/index storage (host volume): `/local/plugins/memory/`
- Validation scripts: `/local/scripts/openviking/openviking_doctor.py`

## Architecture

```text
                     +------------------------------+
                     | Hermes Agent (Gateway Node) |
                     | memory.provider=openviking   |
                     +--------------+---------------+
                                    |
                                    | HTTP (trusted network, headers:
                                    | X-OpenViking-Account/User[/Agent])
                                    v
                   +--------------------------------------+
                   | OpenViking Service (Docker)          |
                   | :1933                                |
                   +----------------+---------------------+
                                    |
      +-----------------------------+----------------------------------+
      |                            Query Path                          |
      |                                                                  |
      |  1) Query preprocessing                                           |
      |  2) Candidate generation (vector recall + hierarchy/path scope)  |
      |  3) Metadata/path filtering + dedupe                              |
      |  4) Reranking (NVIDIA NIM via LiteLLM)                            |
      |  5) Context assembly returned to Hermes                           |
      +------------------------------------------------------------------+
                                    ^
                                    |
      +-----------------------------+----------------------------------+
      |                         Ingestion Path                         |
      |                                                                  |
      |  1) Parse/normalize (markdown, code, PDF strategy)              |
      |  2) Chunking (section/heading-aware, semantic boundaries)        |
      |  3) Metadata + hierarchy assignment                              |
      |  4) Embeddings generation (NVIDIA embedding models)              |
      |  5) Storage/indexing in OpenViking workspace                     |
      +------------------------------------------------------------------+
                                    |
                                    v
                    /local/plugins/memory (mounted as /data in container)
```

## Model Mapping (Default)

- Parse / extraction route:
  - `OPENVIKING_PARSE_MODEL=nvidia/nemotron-parse` (for external parser integration when enabled)
- VLM:
  - `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`
- Text embeddings:
  - `nvidia/llama-nemotron-embed-1b-v2`
- Multimodal embeddings:
  - `nvidia/llama-nemotron-embed-vl-1b-v2`
- Text rerank:
  - `nvidia/llama-nemotron-rerank-1b-v2`
  - normalized at runtime to LiteLLM provider form `nvidia_nim/nvidia/llama-nemotron-rerank-1b-v2`
- Multimodal rerank:
  - `nvidia/llama-nemotron-rerank-vl-1b-v2`

## Why Chunking Is Here

Chunking belongs to ingestion/indexing because it defines the retrieval unit before embeddings are generated and indexed. OpenViking parser config in `ov.conf` is set to section-aware controls (`max_section_size`, flexibility, and chars), and code parsing uses code-aware segmentation (`code_summary_mode: ast`), which avoids naive fixed-size-only slicing.

## Why Candidate Generation Is Before Rerank

Candidate generation narrows the search space cheaply (vector recall + path/hierarchy constraints + metadata scope). Reranking is more expensive and should only evaluate a deduped candidate set. Reranking improves ordering quality but does not recover candidates that were never retrieved.

## Hermes Integration (Thin Layer)

Integration is non-invasive:

1. Enable `OPENVIKING_ENABLED=1` in `/local/agents/envs/<agent>.env`.
2. Prestart bootstrap (`openviking_env_bootstrap.py`) enforces:
   - `memory.provider: openviking` in `.hermes/config.yaml` when plugin is supported.
   - defaults for `OPENVIKING_ENDPOINT`, `OPENVIKING_ACCOUNT`, `OPENVIKING_USER`.
3. Hermes core memory manager loads OpenViking plugin from `plugins/memory/openviking/`.
4. Built-in memory remains active; external provider augments long-term retrieval.

Optional adapter example:

- `/local/scripts/openviking/openviking_adapter.py`
  - `commit` memory notes
    - committed under `viking://resources/memory/<OPENVIKING_USER>/<category>/...`
  - `recall` semantic contexts
  - build context blocks for prompt assembly

## Deployment

1. Set secrets in `/local/docker/.env`:
   - `NVIDIA_API_KEY=...`
   - `NVIDIA_NIM_API_KEY=...` (or leave empty to inherit from `NVIDIA_API_KEY`)
2. Build and run:

```bash
docker compose -f /local/docker/compose.yml --env-file /local/docker/.env up -d --build
```

3. Confirm:

```bash
docker ps --filter name=openviking
curl -sS http://127.0.0.1:1933/health
curl -sS http://127.0.0.1:1933/ready
```

## Operations

- Logs:
  - `/local/logs/openviking/bootstrap.log`
  - `/local/logs/openviking/server.log`
  - `/local/logs/openviking/adapter.log`
- Restart service:

```bash
docker compose -f /local/docker/compose.yml --env-file /local/docker/.env restart openviking
```

- Tail logs:

```bash
tail -f /local/logs/openviking/bootstrap.log /local/logs/openviking/server.log
```

## HOW THIS WAS TESTED

Commands run:

1. Build/start service:

```bash
docker compose -f /local/docker/compose.yml --env-file /local/docker/.env up -d --build
```

Validates:
- image builds
- service starts with mounted config/env/log/storage

Success looks like:
- `openviking` container is `Up`
- `/health` returns `{"status":"ok","healthy":true,...}`

2. Boot + health + ingestion + retrieval + rerank + Hermes smoke:

```bash
python3 /local/scripts/openviking/openviking_doctor.py
```

Validates:
- boot test (`docker ps` + `/health`)
- health/readiness diagnostics
- ingestion for sample markdown + structured technical doc
- embeddings observed via telemetry tokens
- retrieval returns expected candidate docs
- rerank connectivity/functionality (ordering changes on meaningful case)
- Hermes adapter commit/recall smoke path
- failure-path diagnostics (unreachable service and invalid API key)

Success looks like:
- final JSON summary has `"ok": true`

Failure means:
- any step with `"ok": false` includes diagnostics for targeted remediation.

3. Direct API smoke:

```bash
curl -sS http://127.0.0.1:1933/health
curl -sS -X POST http://127.0.0.1:1933/api/v1/search/search \
  -H 'Content-Type: application/json' \
  -H 'X-OpenViking-Account: colmeio' \
  -H 'X-OpenViking-User: colmeio' \
  -d '{"query":"milk shortage","target_uri":"viking://resources","limit":5,"telemetry":true}'
```

Validates:
- endpoint reachability
- retrieval response shape and telemetry

## HOW TO VERIFY THIS IN PRODUCTION

Startup checklist:
- `docker ps` shows `openviking` running.
- `/local/logs/openviking/bootstrap.log` has `startup.ready`.
- `curl /health` is healthy.

Runtime health checks:
- monitor `/health` and `/ready`
- check `server.log` for sustained API errors

Ingestion verification:
- ingest a known doc and confirm URI under `viking://resources/...`
- confirm file/index artifacts under `/local/plugins/memory/`

Retrieval verification:
- run known query and confirm expected URI appears in top candidates.

Rerank verification:
- run doctor script rerank step; confirm changed ordering and no provider errors.

Common failure modes:
- missing/invalid NVIDIA keys
- wrong rerank base URL/provider shape
- root-owned volume paths preventing writes
- endpoint mismatch (`127.0.0.1` vs `host.docker.internal`) per runtime context

Log patterns to inspect:
- `validate.env` / `validate.storage` in bootstrap log
- rerank/embedding probe failures
- repeated gateway/provider connection errors

Metrics to watch:
- request latency (`/search/search`)
- retrieval candidate counts
- embedding/rerank token usage (telemetry)
- error rate by endpoint

How to know Hermes receives useful context:
- adapter `context` returns high-relevance snippets for known queries
- Hermes responses cite details from recently-ingested docs
- memory recall quality improves across sessions for same user/account scope

## HOW I ALREADY VERIFIED THIS IN PRODUCTION

On this VM, verification was performed against the running `openviking` container using:

- real health endpoint checks (`/health`, `/ready`)
- real ingestion through `/api/v1/resources/temp_upload` + `/api/v1/resources`
- real retrieval through `/api/v1/search/search`
- real rerank provider probes against NVIDIA NIM via LiteLLM
- real Hermes adapter smoke (`openviking_adapter.py commit/context`)

The exact command list and outcomes are captured in the section **HOW THIS WAS TESTED** and can be rerun at any time with:

```bash
python3 /local/scripts/openviking/openviking_doctor.py
```
