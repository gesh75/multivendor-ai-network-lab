#!/usr/bin/env bash
# ============================================================================
#  GESH Multi-Vendor Lab — Destroy Topology
#  Usage: ./destroy.sh [topology-name]
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TOPO_DIR="${PROJECT_DIR}/topologies"

TOPOLOGY="${1:-clos-evpn}"
TOPO_FILE="${TOPO_DIR}/${TOPOLOGY}.clab.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# shellcheck source=clab-common.sh
source "${SCRIPT_DIR}/clab-common.sh"

if [[ ! -f "$TOPO_FILE" ]]; then
    echo -e "${RED}[ERROR]${NC} Topology file not found: ${TOPO_FILE}"
    exit 1
fi

echo ""
echo -e "${CYAN}[INFO]${NC}  Destroying topology: ${BOLD}${TOPOLOGY}${NC}"

cd "$TOPO_DIR"

run_clab destroy -t "$TOPO_FILE" --cleanup 2>&1

echo ""
echo -e "${GREEN}[OK]${NC}    Topology ${BOLD}${TOPOLOGY}${NC} destroyed and cleaned up."
echo ""
