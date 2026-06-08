#!/usr/bin/env bash
# ============================================================================
#  GESH Multi-Vendor Lab — Deploy Topology
#  Usage: ./deploy.sh [topology-name]
#  Available: clos-evpn | 3tier-enterprise | sp-mpls | minimal
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TOPO_DIR="${PROJECT_DIR}/topologies"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

TOPOLOGY="${1:-clos-evpn}"
TOPO_FILE="${TOPO_DIR}/${TOPOLOGY}.clab.yml"

# shellcheck source=clab-common.sh
source "${SCRIPT_DIR}/clab-common.sh"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  GESH Multi-Vendor Lab — Deploying: ${CYAN}${TOPOLOGY}${NC}${BOLD}              ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Validate topology file exists
if [[ ! -f "$TOPO_FILE" ]]; then
    echo -e "${RED}[ERROR]${NC} Topology file not found: ${TOPO_FILE}"
    echo ""
    echo "Available topologies:"
    for f in "${TOPO_DIR}"/*.clab.yml; do
        name=$(basename "$f" .clab.yml)
        echo "  - ${name}"
    done
    exit 1
fi

# Check Docker is running
if ! docker info &>/dev/null 2>&1; then
    echo -e "${RED}[ERROR]${NC} Docker is not running. Start Docker Desktop or OrbStack first."
    exit 1
fi

# Check available memory
DOCKER_MEM=$(docker info 2>/dev/null | grep "Total Memory" | awk '{print $3}' | sed 's/GiB//')
echo -e "${CYAN}[INFO]${NC}  Docker memory available: ${DOCKER_MEM:-unknown}GB"

# Check required images
echo -e "${CYAN}[INFO]${NC}  Checking required images..."

MISSING=0
check_image() {
    local pattern="$1"
    local name="$2"
    if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -qi "$pattern"; then
        echo -e "  ${GREEN}✓${NC} $name"
    else
        echo -e "  ${RED}✗${NC} $name — not found"
        MISSING=$((MISSING + 1))
    fi
}

# Check based on topology
case "$TOPOLOGY" in
    clos-evpn)
        check_image "nokia/srlinux" "Nokia SR Linux"
        check_image "ceos" "Arista cEOS"
        check_image "frrouting/frr" "FRR"
        check_image "network-multitool" "Network Multitool"
        ;;
    minimal)
        check_image "nokia/srlinux" "Nokia SR Linux"
        check_image "frrouting/frr" "FRR"
        ;;
    *)
        check_image "nokia/srlinux" "Nokia SR Linux"
        check_image "frrouting/frr" "FRR"
        ;;
esac

if (( MISSING > 0 )); then
    echo ""
    echo -e "${YELLOW}[WARN]${NC}  ${MISSING} image(s) missing. Nodes using missing images will fail."
    echo -e "${YELLOW}       ${NC}  Run ./scripts/setup.sh to install missing images."
    echo ""
    read -rp "Continue anyway? [y/N] " choice
    [[ "${choice,,}" != "y" ]] && exit 1
fi

# Deploy
echo ""
echo -e "${CYAN}[INFO]${NC}  Deploying topology from: ${TOPO_FILE}"
echo -e "${CYAN}[INFO]${NC}  This may take 1-3 minutes..."
echo ""

cd "$TOPO_DIR"

# Run containerlab (dockerized on macOS, native elsewhere)
run_clab deploy -t "$TOPO_FILE" --reconfigure 2>&1

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║  ${GREEN}Deployment Complete${NC}${BOLD}                                       ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}║  Verify:  ./scripts/verify.sh                              ║${NC}"
echo -e "${BOLD}║  Destroy: ./scripts/destroy.sh ${TOPOLOGY}              ║${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}║  Connect to devices:                                       ║${NC}"
echo -e "${BOLD}║    ssh admin@clab-${TOPOLOGY}-spine1                    ║${NC}"
echo -e "${BOLD}║    ssh admin@clab-${TOPOLOGY}-leaf1                     ║${NC}"
echo -e "${BOLD}║    docker exec -it clab-${TOPOLOGY}-leaf3 vtysh         ║${NC}"
echo -e "${BOLD}║                                                            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
