#!/usr/bin/env bash
# ============================================================================
# Hermes Orchestrator Installer (Node Edition)
# ============================================================================
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Magaav/hermes-orchestrator/main/scripts/install.sh | bash
#
# ============================================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

REPO_URL="https://github.com/Magaav/hermes-orchestrator.git"
INSTALL_DIR="${HERMES_ORCHESTRATOR_DIR:-/local}"
HORC_INSTALL_PATH="${HORC_INSTALL_PATH:-/usr/local/bin/horc}"
HORD_INSTALL_PATH="${HORD_INSTALL_PATH:-/usr/local/bin/hord}"

info()    { echo -e "${CYAN}[horc]${NC} $1"; }
success() { echo -e "${GREEN}[horc]${NC} $1"; }
warn()    { echo -e "${YELLOW}[horc]${NC} $1"; }
error()   { echo -e "${RED}[horc]${NC} $1"; }

require_cmd() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        error "Missing required command: $cmd"
        exit 1
    fi
}

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
require_cmd git

# Clone or pull
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Repository exists — pulling latest..."
    git -C "${INSTALL_DIR}" fetch origin "${BRANCH}"
    git -C "${INSTALL_DIR}" checkout "${BRANCH}"
    git -C "${INSTALL_DIR}" pull --ff-only origin "${BRANCH}"
else
    if [[ -e "${INSTALL_DIR}" ]] && [[ -n "$(ls -A "${INSTALL_DIR}" 2>/dev/null || true)" ]]; then
        error "Target directory exists and is not a git repo: ${INSTALL_DIR}"
        error "Use --dir to choose an empty path, or convert ${INSTALL_DIR} into a repo first."
        exit 1
    fi

    info "Cloning repository..."
    mkdir -p "${INSTALL_DIR}"
    git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
fi

# Install horc/hord commands
info "Installing 'horc' and 'hord' commands..."
WRAPPER_CONTENT=$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "${INSTALL_DIR}/scripts/clone/horc.sh" "\$@"
EOF
)

TARGET_DIR="$(dirname "${HORC_INSTALL_PATH}")"
TMP_WRAPPER="$(mktemp)"
printf "%s\n" "${WRAPPER_CONTENT}" > "${TMP_WRAPPER}"
chmod +x "${TMP_WRAPPER}"

if [[ -d "${TARGET_DIR}" && -w "${TARGET_DIR}" ]] || mkdir -p "${TARGET_DIR}" 2>/dev/null; then
    install -m 0755 "${TMP_WRAPPER}" "${HORC_INSTALL_PATH}"
else
    require_cmd sudo
    sudo mkdir -p "${TARGET_DIR}"
    sudo install -m 0755 "${TMP_WRAPPER}" "${HORC_INSTALL_PATH}"
fi
rm -f "${TMP_WRAPPER}"

TARGET_DIR_HORD="$(dirname "${HORD_INSTALL_PATH}")"
TMP_WRAPPER_HORD="$(mktemp)"
printf "%s\n" "${WRAPPER_CONTENT}" > "${TMP_WRAPPER_HORD}"
chmod +x "${TMP_WRAPPER_HORD}"

if [[ -d "${TARGET_DIR_HORD}" && -w "${TARGET_DIR_HORD}" ]] || mkdir -p "${TARGET_DIR_HORD}" 2>/dev/null; then
    install -m 0755 "${TMP_WRAPPER_HORD}" "${HORD_INSTALL_PATH}"
else
    require_cmd sudo
    sudo mkdir -p "${TARGET_DIR_HORD}"
    sudo install -m 0755 "${TMP_WRAPPER_HORD}" "${HORD_INSTALL_PATH}"
fi
rm -f "${TMP_WRAPPER_HORD}"

# Git safety hooks (best-effort)
if git -C "${INSTALL_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "${INSTALL_DIR}" config core.hooksPath .githooks || true
fi

success "'horc' installed to ${HORC_INSTALL_PATH}"
success "'hord' alias installed to ${HORD_INSTALL_PATH}"
success "git hooks path set to .githooks (secret guard)"

# Show horc help
echo ""
success "Installation complete!"
echo ""
echo -e "${BOLD}Usage:${NC}"
echo "  horc start [name]          Start node (default: orchestrator)"
echo "  horc status [name]         Show node status"
echo "  horc stop [name]           Stop node"
echo "  horc restart [name]        Restart node to reload env/credentials"
echo "  horc delete [name]         Delete node container/runtime registration"
echo "  horc logs [name]           View logs"
echo "  horc logs clean [name|all] Truncate centralized logs for fresh tracking"
echo "  horc backup all            Backup all node state to /local/backups"
echo "  horc backup node [name]    Backup one node state to /local/backups"
echo "  horc restore [path]        Restore backup archive into /local/agents"
echo "  horc update                Update hermes-orchestrator (/local)"
echo "  horc agent update [name]   Update hermes-agent template or one node"
echo "  hord ...                   Compatibility alias to horc"
echo ""
echo -e "${BOLD}Examples:${NC}"
echo "  horc start"
echo "  horc status"
echo "  horc start node1"
echo "  horc logs node1 --lines 50"
echo "  horc logs clean"
echo "  horc logs clean node1"
echo "  horc backup all"
echo "  horc backup node node1"
echo "  horc restore /local/backups/horc-backup-node-node1-YYYYMMDDTHHMMSSZ.tar.gz"
echo "  horc restart"
echo "  horc update"
echo "  horc agent update node1"
echo ""
