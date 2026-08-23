FROM electronuserland/builder:wine

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y --no-install-recommends golang-go nsis unar \
  && rm -rf /var/lib/apt/lists/*
