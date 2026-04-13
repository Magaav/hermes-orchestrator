SHELL := /bin/bash

UI_DIR := /local/apps/wasm-ui
WASM_CRATE_DIR := $(UI_DIR)/wasm/log-worker
WASM_OUT_DIR := $(UI_DIR)/wasm/pkg
GATEWAY_RUN := python3 /local/scripts/ui-gateway/run.py
PY_TEST := python3 -m unittest discover -s /local/scripts/ui-gateway/tests -v

# Docker build tooling
BUILDER_IMAGE ?= hermes-wasm-ui-builder:latest
DOCKERFILE_BUILD := $(UI_DIR)/Dockerfile.build

JS_FILES_LOCAL := \
	$(UI_DIR)/api.js \
	$(UI_DIR)/app.js \
	$(UI_DIR)/analyzer/js-fallback.js \
	$(UI_DIR)/analyzer/wasm-runtime.js \
	$(UI_DIR)/analyzer/log-analyzer.js \
	$(UI_DIR)/analyzer/analysis.worker.js \
	$(UI_DIR)/scripts/benchmark-log-parser.mjs

JS_FILES_DOCKER := \
	/workspace/apps/wasm-ui/api.js \
	/workspace/apps/wasm-ui/app.js \
	/workspace/apps/wasm-ui/analyzer/js-fallback.js \
	/workspace/apps/wasm-ui/analyzer/wasm-runtime.js \
	/workspace/apps/wasm-ui/analyzer/log-analyzer.js \
	/workspace/apps/wasm-ui/analyzer/analysis.worker.js \
	/workspace/apps/wasm-ui/scripts/benchmark-log-parser.mjs

.PHONY: help gateway gateway-auth test-gateway check-js build-wasm benchmark all docker-image docker-check-js docker-build-wasm docker-benchmark docker-all

help:
	@echo "Targets:"
	@echo "  make gateway            # run local gateway (experimental on)"
	@echo "  make gateway-auth       # run gateway with WASM_UI_API_TOKEN set"
	@echo "  make test-gateway       # run gateway python tests"
	@echo "  make check-js           # node --check for UI JS files"
	@echo "  make build-wasm         # build Rust/WASM worker with wasm-pack"
	@echo "  make benchmark          # benchmark JS vs WASM parser"
	@echo "  make all                # check-js + build-wasm + benchmark"
	@echo "  make docker-image       # build containerized toolchain image"
	@echo "  make docker-check-js    # run JS checks inside Docker"
	@echo "  make docker-build-wasm  # build WASM inside Docker"
	@echo "  make docker-benchmark   # run benchmark inside Docker"
	@echo "  make docker-all         # docker-check-js + docker-build-wasm + docker-benchmark"

gateway:
	@WASM_UI_EXPERIMENTAL=1 $(GATEWAY_RUN)

gateway-auth:
	@if [[ -z "$$WASM_UI_API_TOKEN" ]]; then \
		echo "Set WASM_UI_API_TOKEN before running gateway-auth"; \
		exit 1; \
	fi
	@WASM_UI_EXPERIMENTAL=1 $(GATEWAY_RUN)

test-gateway:
	@$(PY_TEST)

check-js:
	@command -v node >/dev/null 2>&1 || { echo "node is required for check-js"; exit 1; }
	@for f in $(JS_FILES_LOCAL); do \
		echo "Checking $$f"; \
		node --check $$f; \
	done

build-wasm:
	@command -v wasm-pack >/dev/null 2>&1 || { echo "wasm-pack is required for build-wasm"; exit 1; }
	@cd $(WASM_CRATE_DIR) && wasm-pack build --target web --out-dir ../pkg

benchmark:
	@command -v node >/dev/null 2>&1 || { echo "node is required for benchmark"; exit 1; }
	@node $(UI_DIR)/scripts/benchmark-log-parser.mjs \
		--input /local/logs/nodes/orchestrator/runtime.log \
		--lines 120000 \
		--iterations 6

all: check-js build-wasm benchmark

docker-image:
	@docker build -f $(DOCKERFILE_BUILD) -t $(BUILDER_IMAGE) /local

docker-check-js: docker-image
	@docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui $(BUILDER_IMAGE) \
		'for f in $(JS_FILES_DOCKER); do echo "Checking $$f"; node --check "$$f"; done'

docker-build-wasm: docker-image
	@docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui/wasm/log-worker $(BUILDER_IMAGE) \
		"wasm-pack build --target web --out-dir ../pkg"

docker-benchmark: docker-image
	@docker run --rm -v /local:/workspace -w /workspace/apps/wasm-ui $(BUILDER_IMAGE) \
		"node /workspace/apps/wasm-ui/scripts/benchmark-log-parser.mjs \
			--input /workspace/logs/nodes/orchestrator/runtime.log \
			--lines 120000 \
			--iterations 6"

docker-all: docker-check-js docker-build-wasm docker-benchmark
