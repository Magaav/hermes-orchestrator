#!/bin/bash
# ============================================================================
# Hermes Orchestrator Installer (Colmeio Edition)
# ============================================================================
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
#
# ============================================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

REPO_URL="https://github.com/Magaav/hermes-orchestrator.git"
INSTALL_DIR="${HERMES_ORCHESTRATOR_DIR:-/local}"
HORC_INSTALL_PATH="${HORC_INSTALL_PATH:-/usr/local/bin/horc}"

info()    { echo -e "${CYAN}[horc]${NC} $1"; }
success() { echo -e "${GREEN}[horc]${NC} $1"; }
warn()    { echo -e "${YELLOW}[horc]${NC} $1"; }
error()   { echo -e "${RED}[horc]${NC} $1"; }

# Parse arguments
BRANCH="main"
while [[ $# -gt 0 ]]; do
    case $1 in
        --branch) BRANCH="$2"; shift 2 ;;
        --dir) INSTALL_DIR="$2"; shift 2 ;;
        -h|--help)
            echo "Hermes Orchestrator Installer"
            echo ""
            echo "Usage: curl -fsSL ... | bash [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --branch NAME  Git branch (default: main)"
            echo "  --dir PATH    Install directory (default: /local)"
            echo "  -h, --help    Show this help"
            exit 0 ;;
        *) shift ;;
    esac
done

info "Hermes Orchestrator installation starting..."
info "Target: ${INSTALL_DIR}"

# Detect if already installed
if [[ -d "${INSTALL_DIR}/hermes-agent" ]] || [[ -d "${INSTALL_DIR}/scripts" ]]; then
    warn "Existing installation detected. Updating instead of fresh install."
    UPDATE_MODE=true
fi

# Clone or pull
if [[ -d "${INSTALL_DIR}/.git" ]] || [[ -d "${INSTALL_DIR}/hermes-agent" ]]; then
    info "Repository exists — pulling latest..."
    cd "${INSTALL_DIR}"
    git fetch origin "${BRANCH}"
    git checkout "${BRANCH}"
    git pull origin "${BRANCH}"
else
    info "Cloning repository..."
    git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
fi

# Install horc command
info "Installing 'horc' command..."
cat > "${HORC_INSTALL_PATH}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${INSTALL_DIR}/scripts/clone/horc.sh" "\$@"
EOF
chmod +x "${HORC_INSTALL_PATH}"

success "'horc' installed to ${HORC_INSTALL_PATH}"

# Show horc help
echo ""
success "Installation complete!"
echo ""
echo -e "${BOLD}Usage:${NC}"
echo "  horc start [name]          Start node (default: orchestrator)"
echo "  horc status [name]         Show node status"
echo "  horc stop [name]           Stop node"
echo "  horc delete [name]         Delete node container/runtime registration"
echo "  horc logs [name]           View logs"
echo ""
echo -e "${BOLD}Examples:${NC}"
echo "  horc start"
echo "  horc status"
echo "  horc start node1"
echo "  horc logs node1 --lines 50"
echo ""
