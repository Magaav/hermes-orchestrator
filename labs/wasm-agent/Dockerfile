FROM python:3.12-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates git nodejs npm ripgrep sqlite3 tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10000 --create-home --shell /bin/bash frontier \
    && mkdir -p /local /lab-seed /lab-output /lab-canary /source /fixtures /workspace /result /task /gateway-output \
    && chown frontier:frontier /local /lab-output /workspace /result /task /gateway-output

COPY --chmod=0755 entrypoint.sh /usr/local/bin/safe-lab-entrypoint
COPY --chmod=0755 containment-canary.sh /usr/local/bin/containment-canary
COPY --chmod=0755 lane-runner.py /usr/local/bin/lane-runner
COPY --chmod=0755 model-gateway.py /usr/local/bin/model-gateway
COPY --chmod=0644 responses_bridge.py /usr/local/bin/responses_bridge.py
COPY --chmod=0644 anthropic_bridge.py /usr/local/bin/anthropic_bridge.py
COPY --chmod=0644 gemini_bridge.py /usr/local/bin/gemini_bridge.py
COPY --chmod=0755 materialize-fixture-task.py /usr/local/bin/materialize-fixture-task
COPY --chmod=0755 hermes-live-runner.py /usr/local/bin/hermes-live-runner

USER 10000:10000
WORKDIR /local
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/safe-lab-entrypoint"]
CMD ["bash"]
