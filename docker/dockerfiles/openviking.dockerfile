FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPENVIKING_CONFIG_FILE=/etc/openviking/ov.conf \
    OPENVIKING_HOST=0.0.0.0 \
    OPENVIKING_PORT=1933 \
    OPENVIKING_STORAGE_WORKSPACE=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir openviking litellm requests

COPY openviking-entrypoint.sh /usr/local/bin/openviking-entrypoint.sh
RUN chmod +x /usr/local/bin/openviking-entrypoint.sh

EXPOSE 1933

ENTRYPOINT ["/usr/local/bin/openviking-entrypoint.sh"]
