#!/usr/bin/env bash
# ============================================================================
#  GESH Multi-Vendor Lab — Shared containerlab runners
#  Sourced by deploy.sh and destroy.sh. Provides run_clab().
# ============================================================================

# Resolve repo paths from this file's own location so callers don't pass them.
_CLAB_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAB_PROJECT_DIR="$(dirname "$_CLAB_COMMON_DIR")"
CLAB_TOPO_DIR="${CLAB_PROJECT_DIR}/topologies"
CLAB_OS="$(uname -s)"

# Color fallbacks (callers usually define these already).
: "${RED:=\033[0;31m}"
: "${CYAN:=\033[0;36m}"
: "${NC:=\033[0m}"

# Run a native containerlab/clab binary, elevating with sudo when needed.
run_native_clab() {
    local clab_bin="$1"
    shift

    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        "$clab_bin" "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$clab_bin" "$@"
    else
        "$clab_bin" "$@"
    fi
}

# Run containerlab via the clab Docker image with --pid host (macOS/Docker Desktop).
run_macos_clab_container() {
    if ! command -v docker &>/dev/null; then
        echo -e "${RED}[ERROR]${NC} docker not found. Install Docker Desktop or OrbStack first."
        exit 1
    fi

    local docker_sock="${DOCKER_HOST_SOCKET:-}"
    local -a netns_mount=()

    if [[ -z "$docker_sock" ]]; then
        if [[ -S "$HOME/.docker/run/docker.sock" ]]; then
            docker_sock="$HOME/.docker/run/docker.sock"
        elif [[ -S /var/run/docker.sock ]]; then
            docker_sock="/var/run/docker.sock"
        else
            echo -e "${RED}[ERROR]${NC} Docker socket not found."
            echo "Set DOCKER_HOST_SOCKET to your Docker socket path and retry."
            exit 1
        fi
    fi

    if [[ -d /run/netns ]]; then
        netns_mount=(-v /run/netns:/run/netns)
    fi

    docker run --rm --privileged --network host --pid host \
        -v "${docker_sock}:/var/run/docker.sock" \
        "${netns_mount[@]}" \
        -v "${CLAB_PROJECT_DIR}:${CLAB_PROJECT_DIR}" \
        -w "$CLAB_TOPO_DIR" \
        --entrypoint /usr/bin/containerlab \
        ghcr.io/srl-labs/clab:latest "$@"
}

# run_clab <clab-subcommand> [args...]
#   macOS      -> dockerized clab image (--pid host)
#   other Unix -> native containerlab/clab binary
run_clab() {
    if [[ "$CLAB_OS" == "Darwin" ]]; then
        echo -e "${CYAN}[INFO]${NC}  macOS detected; using clab Docker image with --pid host."
        run_macos_clab_container "$@"
    elif command -v containerlab &>/dev/null; then
        run_native_clab containerlab "$@"
    elif command -v clab &>/dev/null; then
        run_native_clab clab "$@"
    else
        echo -e "${RED}[ERROR]${NC} containerlab not found in PATH."
        echo "Run ./scripts/setup.sh first."
        exit 1
    fi
}
