# Hermes WASM UI (Experimental)

Hybrid control-plane UI for Hermes Orchestrator.

## Architecture

- Browser UI shell: `/local/apps/wasm-ui`
- Local gateway API + SSE: `/local/scripts/ui-gateway`
- Operational source of truth: `scripts/clone/clone_manager.py`
- Targeted compute acceleration: Rust/WASM worker under `/local/apps/wasm-ui/wasm/log-worker`

V1 intentionally limits scope to observability and safe operations:

- Fleet and node status
- Multi-channel logs
- Safe actions: `start`, `stop`, `restart`

## Start

```bash
WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
```

Open: `http://127.0.0.1:8787/`

Optional auth:

```bash
export WASM_UI_API_TOKEN='your-token'
WASM_UI_EXPERIMENTAL=1 python3 /local/scripts/ui-gateway/run.py
```

If auth is enabled, the browser prompts once and stores token in `localStorage` key `wasm_ui_api_token`.

Quick scripts:

```bash
/local/apps/wasm-ui/scripts/run-local.sh
WASM_UI_API_TOKEN='your-token' /local/apps/wasm-ui/scripts/run-local-auth.sh
```

## Build Workflow

`apps/wasm-ui/Makefile` provides one-command workflows:

```bash
make -C /local/apps/wasm-ui help
```

Local toolchain mode:

```bash
make -C /local/apps/wasm-ui check-js
make -C /local/apps/wasm-ui build-wasm
make -C /local/apps/wasm-ui benchmark
```

Containerized mode (recommended for reproducibility/CI):

```bash
make -C /local/apps/wasm-ui docker-image
make -C /local/apps/wasm-ui docker-all
```

Or via helper script:

```bash
/local/apps/wasm-ui/scripts/docker-ui-build.sh
```

## Build WASM Worker (Optional)

Runtime already supports JS fallback. Build WASM only when benchmark proves value.

```bash
cd /local/apps/wasm-ui/wasm/log-worker
wasm-pack build --target web --out-dir ../pkg
```

Expected outputs:

- `/local/apps/wasm-ui/wasm/pkg/log_worker.js`
- `/local/apps/wasm-ui/wasm/pkg/log_worker_bg.wasm`

## Benchmark Policy

Use benchmark before enabling WASM by default:

```bash
node /local/apps/wasm-ui/scripts/benchmark-log-parser.mjs \
  --input /local/logs/nodes/orchestrator/runtime.log \
  --lines 120000 \
  --iterations 6
```

Adopt WASM only when it is at least ~15% faster on representative corpora.

## CLI Parity

Each UI action maps to `clone_manager.py` operations:

- UI `start` -> `clone_manager.py start --name <node>`
- UI `stop` -> `clone_manager.py stop --name <node>`
- UI `restart` -> `stop` then `start`
- UI status/log views call `status` and log filesystem readers only

No destructive operations are exposed in V1.

## Docker vs Local Recommendation

- Prefer Docker builds for CI/release parity and predictable toolchain versions (`node`, `rust`, `wasm-pack`).
- Prefer local host builds for fastest iterative development when your machine already has the toolchain.
- Runtime serving still happens on host via `scripts/ui-gateway`; Docker here is for build/test tooling.
