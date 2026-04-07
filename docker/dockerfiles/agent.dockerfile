# Full-power agent sandbox image
# Built on Ubuntu 24.04 with all dev tools needed for agent freedom
#
# Tools included:
# - Python 3.12 + pip + venv
# - Node.js 20 + npm + yarn
# - curl, wget, git
# - build-essential (gcc, make, etc.)
# - jq, zip, unzip, tree, htop, tmux
# - GitHub CLI (gh)
# - Docker CLI (for building images inside sandbox)

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NPM_CONFIG_PREFIX=/usr/local

# Install all system tools in one layer
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        # Python & Node
        python3.12 \
        python3-pip \
        python3.12-venv \
        nodejs \
        npm \
        # Version managers
        curl \
        wget \
        git \
        git-lfs \
        # Build tools
        build-essential \
        pkg-config \
        libffi-dev \
        libssl-dev \
        # Utilities
        jq \
        zip \
        unzip \
        gzip \
        tar \
        bzip2 \
        xz-utils \
        ca-certificates \
        openssl \
        tzdata \
        less \
        tree \
        vim \
        nano \
        sudo \
        man-db \
        # Process monitoring
        htop \
        tmux \
        screen \
        procps \
        # Network tools
        iputils-ping \
        netcat-openbsd \
        dnsutils \
        # Misc
        unzip \
        zip \
        # GitHub CLI
        && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
        && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
        && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Create symbolic links for python3
RUN ln -sf python3.12 /usr/bin/python3 \
    && ln -sf python3.12 /usr/bin/python

# Install common Python packages needed by skills
RUN python3 -m pip install --break-system-packages requests pandas openpyxl

# Install global Node tools (optional)
RUN npm install -g yarn pnpm

# Create working directory
WORKDIR /workspace

# Default command
CMD ["/bin/bash"]
