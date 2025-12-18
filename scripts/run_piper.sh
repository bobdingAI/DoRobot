#!/bin/bash
#
# Unified Piper Robot Data Collection Launcher
#
# This script starts both DORA dataflow and CLI with proper ordering:
# 1. Cleans up stale ZeroMQ socket files
# 2. Starts DORA dataflow in background
# 3. Waits for ZeroMQ sockets to be ready
# 4. Starts CLI in foreground
# 5. Handles cleanup on exit

set -e

# Version
VERSION="0.1.0"

# Configuration
CONDA_ENV="${CONDA_ENV:-dorobot}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DORA_DIR="$PROJECT_ROOT/operating_platform/robot/robots/piper_v1"
SOCKET_IMAGE="/tmp/dora-zeromq-piper-image"
SOCKET_JOINT="/tmp/dora-zeromq-piper-joint"
SOCKET_TIMEOUT="${SOCKET_TIMEOUT:-30}"
DORA_INIT_DELAY="${DORA_INIT_DELAY:-5}"
DORA_PID=""
DORA_GRAPH_NAME=""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "${BLUE}[STEP]${NC} $1"; }

# Default device configuration
export ARM_LEADER_CAN="${ARM_LEADER_CAN:-can_right}"
export ARM_FOLLOWER_CAN="${ARM_FOLLOWER_CAN:-can_left}"
export CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
export CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-1}"

init_conda() {
    if [ -n "$CONDA_EXE" ]; then
        CONDA_BASE="$(dirname "$(dirname "$CONDA_EXE")")"
    elif [ -d "$HOME/miniconda3" ]; then
        CONDA_BASE="$HOME/miniconda3"
    elif [ -d "$HOME/anaconda3" ]; then
        CONDA_BASE="$HOME/anaconda3"
    else
        log_error "Conda not found."
        exit 1
    fi
    source "$CONDA_BASE/etc/profile.d/conda.sh"
}

activate_env() {
    conda activate "$1"
    log_info "Activated conda environment: $1"
}

cleanup() {
    log_step "Cleaning up resources..."
    if [ -n "$DORA_GRAPH_NAME" ]; then
        dora stop "$DORA_GRAPH_NAME" 2>/dev/null || true
        sleep 2
    fi
    if [ -n "$DORA_PID" ] && kill -0 "$DORA_PID" 2>/dev/null; then
        kill -SIGTERM "$DORA_PID" 2>/dev/null || true
    fi
    rm -f "$SOCKET_IMAGE" "$SOCKET_JOINT"
    log_info "Cleanup complete"
}

trap cleanup EXIT INT TERM

cleanup_stale_sockets() {
    log_step "Cleaning up stale sockets..."
    rm -f "$SOCKET_IMAGE" "$SOCKET_JOINT"
    pkill -f "arm_normal_piper_v2/main.py" 2>/dev/null || true
}

wait_for_sockets() {
    log_step "Waiting for ZeroMQ sockets..."
    local elapsed=0
    while [ $elapsed -lt $SOCKET_TIMEOUT ]; do
        if [ -S "$SOCKET_IMAGE" ] && [ -S "$SOCKET_JOINT" ]; then
            log_info "Sockets ready!"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    log_error "Socket timeout."
    return 1
}

start_dora() {
    log_step "Starting DORA dataflow..."
    cd "$DORA_DIR"
    dora run dora_teleoperate_dataflow.yml &
    DORA_PID=$!
    sleep 2
    DORA_GRAPH_NAME=$(dora list 2>/dev/null | grep -oP 'dora_teleoperate_dataflow[^\s]*' | head -1) || true
    cd "$PROJECT_ROOT"
}

start_cli() {
    log_step "Starting CLI..."
    local repo_id="${REPO_ID:-piper-test}"
    local single_task="${SINGLE_TASK:-test piper arm.}"
    
    python "$PROJECT_ROOT/operating_platform/core/main.py" \
        --robot.type=piper_v1 \
        --record.repo_id="$repo_id" \
        --record.single_task="$single_task" \
        "$@"
}

main() {
    init_conda
    activate_env "$CONDA_ENV"
    cleanup_stale_sockets
    start_dora
    wait_for_sockets
    log_step "Waiting ${DORA_INIT_DELAY}s for initialization..."
    sleep $DORA_INIT_DELAY
    start_cli "$@"
}

main "$@"
