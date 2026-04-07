<p align="center">
  <img src="assets/banner.png" alt="Hermes Agent" width="100%">
</p>

# Hermes Orchestrator Framework ☤

Self-improving AI agent orchestration framework built on Hermes. Designed for multi-node deployment with centralized memory, Discord integration, and Google Workspace automation.

## Quick Start

One command install:

```bash
curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
```

This installs to `/local/` and sets up the `horc` command globally.

## Architecture

- `hermes-agent/` - Core agent (Python, self-improving)
- `skills/` - Reusable skill library
- `workspace/` - Working directory, user scripts
- `scripts/clone/clone_manager.py` - Clone lifecycle manager
- `.env.example` - Environment configuration template

## Clone Management with `horc`

After installation, manage Hermes clone nodes with the `horc` command:

```bash
# List all clones
horc list

# Check clone status
horc status <name>

# Start clone (idempotent — creates or restarts)
horc start <name>

# Stop clone
horc stop <name>

# Restart gateway (inside running container)
horc restart <name>

# Reboot container
horc reboot <name>

# Delete clone
horc delete <name>

# View logs
horc logs <name> --lines 50

# Add new clone
horc add <name> [extra args...]

# Delete clone
horc del <name>
```

## Features

- Multi-model routing (MiniMax, OpenRouter, NVIDIA)
- Discord integration with hybrid mode
- Google Workspace integration (Drive, Gmail, Calendar)
- Autonomous skill creation and improvement
- FTS5 session search and recall
- Docker-based clone isolation with `horc` management
- OpenViking centralized memory/knowledge base

## Manual Install

```bash
git clone https://github.com/Magaav/hermes-orchestrator.git
cd hermes-orchestrator

# Install horc command globally
sudo bash scripts/install.sh

# Or run directly
bash scripts/install.sh --dir /path/to/install
```

## License

MIT
