#!/usr/bin/env bash
# ============================================================================
#  GESH Multi-Vendor Lab — Environment Setup
#  Installs: OrbStack, containerlab, pulls free NOS images
#  Target: macOS Apple Silicon (M3/M4)
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

echo ""
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     GESH Multi-Vendor Network Lab — Setup                  ║${NC}"
echo -e "${BOLD}║     Nokia SR Linux · Arista cEOS · FRR                     ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Check macOS & chip ──────────────────────────────────────────────
info "Checking system requirements..."

ARCH=$(uname -m)
OS=$(uname -s)

case "$OS" in
    Darwin)
        if [[ "$ARCH" == "arm64" ]]; then
            ok "Apple Silicon detected ($ARCH)"
        else
            warn "Intel Mac detected. Some images may require Rosetta."
        fi
        RAM_GB=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}')
        ;;
    Linux)
        ok "Linux detected ($ARCH)"
        RAM_GB=$(awk '/MemTotal/ {printf "%.0f", $2/1048576}' /proc/meminfo)
        ;;
    *)
        fail "Unsupported OS: $OS. Supported platforms: Ubuntu/Linux and macOS."
        ;;
esac
info "System RAM: ${RAM_GB}GB"

if (( RAM_GB < 16 )); then
    fail "Minimum 16GB RAM required. You have ${RAM_GB}GB."
elif (( RAM_GB < 32 )); then
    warn "32GB+ recommended for full 15-node lab. You have ${RAM_GB}GB."
    warn "Consider using the 'minimal' topology (6 nodes, ~5GB)."
else
    ok "RAM sufficient for full 15-node lab"
fi

# ── Step 2: Install Homebrew packages ───────────────────────────────────────
if [[ "$OS" == "Darwin" ]]; then
    info "Checking Homebrew..."
    if ! command -v brew &>/dev/null; then
        fail "Homebrew not found. Install: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    fi
    ok "Homebrew found"
elif [[ "$OS" == "Linux" ]]; then
    if ! command -v curl &>/dev/null; then
        fail "curl not found. Install it first: sudo apt-get update && sudo apt-get install -y curl"
    fi
fi

# ── Step 3: Docker runtime ─────────────────────────────────────────────────
info "Checking Docker runtime..."

DOCKER_RUNTIME="none"

if [[ "$OS" == "Darwin" ]] && command -v orb &>/dev/null; then
    DOCKER_RUNTIME="orbstack"
    ok "OrbStack detected (recommended)"
elif command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    if [[ "$OS" == "Darwin" ]]; then
        DOCKER_RUNTIME="docker-desktop"
        ok "Docker Desktop detected"
    else
        DOCKER_RUNTIME="docker-engine"
        ok "Docker Engine detected"
    fi

    # Check Docker Desktop memory allocation
    DOCKER_MEM=$(docker info 2>/dev/null | grep "Total Memory" | awk '{print $3}' | sed 's/GiB//')
    if [[ -n "$DOCKER_MEM" ]]; then
        DOCKER_MEM_INT=${DOCKER_MEM%.*}
        if (( DOCKER_MEM_INT < 12 )); then
            warn "Docker Desktop has only ${DOCKER_MEM}GB allocated."
            warn "Increase to 16GB+ in Docker Desktop > Settings > Resources."
        else
            ok "Docker Desktop memory: ${DOCKER_MEM}GB"
        fi
    fi
else
    warn "No Docker runtime found."
    if [[ "$OS" == "Linux" ]]; then
        fail "Docker Engine is required. On Ubuntu: curl -fsSL https://get.docker.com | sudo sh"
    fi
    echo ""
    echo "  Option A (Recommended): Install OrbStack"
    echo "    brew install orbstack"
    echo ""
    echo "  Option B: Install Docker Desktop"
    echo "    brew install --cask docker"
    echo ""
    read -rp "Install OrbStack now? [Y/n] " choice
    if [[ "${choice,,}" != "n" ]]; then
        info "Installing OrbStack..."
        brew install orbstack
        DOCKER_RUNTIME="orbstack"
        ok "OrbStack installed"
    else
        fail "Docker runtime required. Install OrbStack or Docker Desktop first."
    fi
fi

# ── Step 4: Containerlab ────────────────────────────────────────────────────
info "Checking containerlab..."

if command -v containerlab &>/dev/null || command -v clab &>/dev/null; then
    CLAB_VER=$(containerlab version 2>/dev/null | head -1 || echo "unknown")
    ok "containerlab found: $CLAB_VER"
else
    info "Installing containerlab..."

    if [[ "$OS" == "Linux" ]]; then
        # Linux: install the native containerlab binary
        bash -c "$(curl -sL https://get.containerlab.dev)"
        ok "containerlab installed"
    elif [[ "$DOCKER_RUNTIME" == "orbstack" ]]; then
        # For OrbStack: install inside a Linux VM
        info "Creating 'clab' Linux VM in OrbStack..."
        orb create ubuntu:noble clab 2>/dev/null || true
        orb -m clab bash -c 'bash -c "$(curl -sL https://get.containerlab.dev)"'
        ok "containerlab installed inside OrbStack VM 'clab'"
        echo ""
        echo -e "${YELLOW}To use containerlab, connect to the OrbStack VM:${NC}"
        echo "  orb -m clab"
        echo "  cd /path/to/containerlab-multivendor/topologies"
        echo "  sudo clab deploy -t clos-evpn.clab.yml"
    else
        # For Docker Desktop: install on macOS directly (devcontainer approach)
        info "Setting up devcontainer for containerlab..."
        mkdir -p "${PROJECT_DIR}/.devcontainer"
        cat > "${PROJECT_DIR}/.devcontainer/devcontainer.json" << 'DEVEOF'
{
    "image": "ghcr.io/srl-labs/containerlab/devcontainer-dood-slim:0.72.0",
    "runArgs": [
        "--network=host",
        "--pid=host",
        "--privileged"
    ],
    "mounts": [
        "type=bind,src=/var/lib/docker,dst=/var/lib/docker",
        "type=bind,src=/lib/modules,dst=/lib/modules"
    ],
    "workspaceFolder": "${localWorkspaceFolder}",
    "workspaceMount": "source=${localWorkspaceFolder},target=${localWorkspaceFolder},type=bind"
}
DEVEOF
        ok "DevContainer config created at .devcontainer/devcontainer.json"
        echo ""
        echo -e "${YELLOW}To use containerlab with Docker Desktop:${NC}"
        echo "  1. Open this folder in VS Code"
        echo "  2. Cmd+Shift+P → 'Reopen in Container'"
        echo "  3. In the devcontainer terminal: clab deploy -t topologies/clos-evpn.clab.yml"
    fi
fi

# ── Step 5: Pull free NOS images ────────────────────────────────────────────
echo ""
info "Checking NOS container images..."

# Nokia SR Linux (free, public registry)
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "ghcr.io/nokia/srlinux"; then
    ok "Nokia SR Linux image found"
else
    info "Pulling Nokia SR Linux (free, ~1.5GB)..."
    docker pull ghcr.io/nokia/srlinux:24.10.3 2>/dev/null && ok "Nokia SR Linux pulled" || warn "SR Linux pull failed — try manually: docker pull ghcr.io/nokia/srlinux:24.10.3"
fi

# FRR (free, public registry)
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "frrouting/frr"; then
    ok "FRR image found"
else
    info "Pulling FRR (free, ~200MB)..."
    docker pull frrouting/frr:v10.3.1 2>/dev/null && ok "FRR pulled" || warn "FRR pull failed — try manually: docker pull frrouting/frr:v10.3.1"
fi

# Network multitool for hosts
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "network-multitool"; then
    ok "Network multitool image found"
else
    info "Pulling network-multitool for hosts..."
    docker pull ghcr.io/hellt/network-multitool:latest 2>/dev/null && ok "network-multitool pulled" || warn "Pull failed"
fi

# Arista cEOS — requires manual download
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qi "ceos"; then
    ok "Arista cEOS image found"
else
    echo ""
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}  Arista cEOS requires manual download (free, guest account):${NC}"
    echo ""
    echo "  1. Go to: https://www.arista.com/en/support/software-download"
    echo "  2. Register a free guest account"
    echo "  3. Download: cEOS Lab → latest version → cEOS-lab-*.tar.xz"
    echo "  4. Import: docker import cEOS-lab-4.33.1F.tar.xz ceosimage:4.33.1F"
    echo ""
    echo -e "${YELLOW}  Until then, cEOS nodes will fail to start.${NC}"
    echo -e "${YELLOW}  The 'minimal' topology works with just SR Linux + FRR.${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
fi

# ── Step 6: Ansible (optional, for automated config push) ───────────────────
info "Checking Ansible..."
if command -v ansible &>/dev/null; then
    ok "Ansible found: $(ansible --version | head -1)"
else
    if [[ "$OS" == "Darwin" ]]; then
        warn "Ansible not found. Install for automated config: brew install ansible"
    else
        warn "Ansible not found. Install for automated config: sudo apt-get install -y ansible"
    fi
fi

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  Setup Complete                                            ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}║  Docker runtime: ${GREEN}${DOCKER_RUNTIME}${NC}${BOLD}                               ║${NC}"
echo -e "${BOLD}║  System RAM:     ${GREEN}${RAM_GB}GB${NC}${BOLD}                                      ║${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}║  Next steps:                                               ║${NC}"
echo -e "${BOLD}║  1. Import Arista cEOS (if not done)                       ║${NC}"
echo -e "${BOLD}║  2. Run: ./scripts/deploy.sh clos-evpn                     ║${NC}"
echo -e "${BOLD}║  3. Run: ./scripts/verify.sh                               ║${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
