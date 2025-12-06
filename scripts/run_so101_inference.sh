#!/bin/bash
#
# SO101 Robot Inference Launcher
#
# This script starts DORA control dataflow and inference.py for robot control.
# Uses the SAME device port configuration as run_so101.sh for consistency.
#
# Usage:
#   bash scripts/run_so101_inference.sh --model /path/to/model [options]
#
# Required:
#   --model PATH    Path to trained model directory

set -e

# Configuration - Single unified environment
CONDA_ENV="${CONDA_ENV:-dorobot}"

# NPU Configuration - enabled by default for Orange Pi/Ascend hardware
USE_NPU="${USE_NPU:-1}"
ASCEND_TOOLKIT_PATH="${ASCEND_TOOLKIT_PATH:-/usr/local/Ascend/ascend-toolkit}"

# Display Configuration
SHOW="${SHOW:-1}"

# ===========================================================================
# DEVICE PORT CONFIGURATION
# ===========================================================================
# IMPORTANT: Use the SAME ports as data collection (run_so101.sh)
# This ensures consistency between training data and inference.
#
# For stable operation, use persistent paths:
#   python scripts/detect_usb_ports.py --yaml

# Camera paths (same as run_so101.sh)
CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-2}"

# Arm ports - only follower for inference (no leader needed)
ARM_FOLLOWER_PORT="${ARM_FOLLOWER_PORT:-/dev/ttyACM1}"
# ===========================================================================

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DORA_DIR="$PROJECT_ROOT/operating_platform/robot/robots/so101_v1"
SOCKET_IMAGE="/tmp/dora-zeromq-so101-image"
SOCKET_JOINT="/tmp/dora-zeromq-so101-joint"
SOCKET_TIMEOUT="${SOCKET_TIMEOUT:-30}"
DORA_INIT_DELAY="${DORA_INIT_DELAY:-5}"
DORA_PID=""
DORA_GRAPH_NAME=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Initialize conda for this shell
init_conda() {
    if [ -n "$CONDA_EXE" ]; then
        CONDA_BASE="$(dirname "$(dirname "$CONDA_EXE")")"
    elif [ -d "$HOME/miniconda3" ]; then
        CONDA_BASE="$HOME/miniconda3"
    elif [ -d "$HOME/anaconda3" ]; then
        CONDA_BASE="$HOME/anaconda3"
    elif [ -d "/opt/conda" ]; then
        CONDA_BASE="/opt/conda"
    else
        log_error "Cannot find conda installation."
        exit 1
    fi

    if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
    else
        log_error "Cannot find conda.sh"
        exit 1
    fi
}

# Activate the conda environment
activate_env() {
    local env_name="$1"
    if ! conda env list | grep -q "^${env_name} "; then
        log_error "Conda environment '$env_name' does not exist."
        exit 1
    fi
    conda activate "$env_name"
    log_info "Activated conda environment: $env_name"
}

# Source Ascend NPU environment if needed
setup_npu_env() {
    if [ "$USE_NPU" == "1" ]; then
        log_step "Setting up Ascend NPU environment..."
        local set_env_script="$ASCEND_TOOLKIT_PATH/set_env.sh"
        if [ -f "$set_env_script" ]; then
            source "$set_env_script"
            log_info "Sourced CANN environment from: $set_env_script"
        else
            log_warn "CANN set_env.sh not found at: $set_env_script"
        fi
    fi
}

# Export device port environment variables for DORA dataflow
export_device_ports() {
    log_step "Configuring device ports..."

    # Export camera paths
    export CAMERA_TOP_PATH
    export CAMERA_WRIST_PATH

    # Export arm ports (only follower for inference)
    export ARM_FOLLOWER_PORT

    # Log configuration
    log_info "Camera configuration:"
    log_info "  camera_top:   $CAMERA_TOP_PATH"
    log_info "  camera_wrist: $CAMERA_WRIST_PATH"
    log_info "Arm configuration:"
    log_info "  follower: $ARM_FOLLOWER_PORT"

    # Warn if using default indices
    if [[ "$CAMERA_TOP_PATH" =~ ^[0-9]+$ ]] || [[ "$CAMERA_WRIST_PATH" =~ ^[0-9]+$ ]]; then
        log_warn "Using numeric camera indices - ensure same as data collection!"
    fi
}

# Cleanup function
cleanup() {
    log_step "Cleaning up..."

    if [ -n "$DORA_GRAPH_NAME" ]; then
        log_info "Stopping DORA dataflow: $DORA_GRAPH_NAME"
        dora stop "$DORA_GRAPH_NAME" 2>/dev/null || true
    fi

    if [ -n "$DORA_PID" ] && kill -0 "$DORA_PID" 2>/dev/null; then
        log_info "Killing DORA process (PID: $DORA_PID)"
        kill "$DORA_PID" 2>/dev/null || true
        wait "$DORA_PID" 2>/dev/null || true
    fi

    if [ -S "$SOCKET_IMAGE" ]; then
        rm -f "$SOCKET_IMAGE"
    fi
    if [ -S "$SOCKET_JOINT" ]; then
        rm -f "$SOCKET_JOINT"
    fi

    log_info "Cleanup complete"
}

trap cleanup EXIT INT TERM

# Clean up stale socket files
cleanup_stale_sockets() {
    log_step "Checking for stale socket files..."
    if [ -e "$SOCKET_IMAGE" ]; then
        log_warn "Removing stale socket: $SOCKET_IMAGE"
        rm -f "$SOCKET_IMAGE"
    fi
    if [ -e "$SOCKET_JOINT" ]; then
        log_warn "Removing stale socket: $SOCKET_JOINT"
        rm -f "$SOCKET_JOINT"
    fi
}

# Wait for ZeroMQ sockets
wait_for_sockets() {
    log_step "Waiting for ZeroMQ sockets to be ready..."

    local elapsed=0
    local poll_interval=0.5

    while [ $elapsed -lt $SOCKET_TIMEOUT ]; do
        if [ -S "$SOCKET_IMAGE" ] && [ -S "$SOCKET_JOINT" ]; then
            log_info "ZeroMQ sockets ready!"
            return 0
        fi
        printf "\r  Waiting... %ds / %ds" $elapsed $SOCKET_TIMEOUT
        sleep $poll_interval
        elapsed=$((elapsed + 1))
    done

    echo ""
    log_error "Timeout waiting for ZeroMQ sockets after ${SOCKET_TIMEOUT}s"
    return 1
}

# Start DORA control dataflow (inference mode - no leader arm)
start_dora() {
    log_step "Starting DORA control dataflow (inference mode)..."

    if ! command -v dora &> /dev/null; then
        log_error "'dora' command not found."
        exit 1
    fi

    local dataflow_file="$DORA_DIR/dora_control_dataflow.yml"
    if [ ! -f "$dataflow_file" ]; then
        log_error "Dataflow file not found: $dataflow_file"
        exit 1
    fi

    cd "$DORA_DIR"

    log_info "Running: dora run dora_control_dataflow.yml"
    dora run dora_control_dataflow.yml &
    DORA_PID=$!

    sleep 2

    if ! kill -0 "$DORA_PID" 2>/dev/null; then
        log_error "DORA failed to start"
        exit 1
    fi

    log_info "DORA started (PID: $DORA_PID)"
    DORA_GRAPH_NAME=$(dora list 2>/dev/null | grep -oP 'dora_control_dataflow[^\s]*' | head -1) || true

    cd "$PROJECT_ROOT"
}

# Start inference
start_inference() {
    local model_path="$1"
    shift  # Remove model_path from args

    log_step "Starting inference..."

    local single_task="${SINGLE_TASK:-Perform the trained task.}"

    log_info "Model path: $model_path"
    log_info "Task: $single_task"

    # Build command arguments
    local cmd_args=(
        --robot.type=so101
        --inference.single_task="$single_task"
        --policy.path="$model_path"
    )

    # Start inference
    python "$PROJECT_ROOT/operating_platform/core/inference.py" \
        "${cmd_args[@]}" \
        "$@"
}

# Print usage
print_usage() {
    echo "Usage: $0 --model PATH [OPTIONS]"
    echo ""
    echo "SO101 Robot Inference Launcher"
    echo ""
    echo "Required:"
    echo "  --model PATH        Path to trained model directory"
    echo ""
    echo "Environment Variables:"
    echo "  CONDA_ENV           Conda environment (default: dorobot)"
    echo "  SINGLE_TASK         Task description for inference"
    echo "  USE_NPU             Ascend NPU support (default: 1)"
    echo "  SHOW                Camera display (default: 1)"
    echo ""
    echo "Device Port Configuration:"
    echo "  CAMERA_TOP_PATH     Camera top path (default: 0)"
    echo "  CAMERA_WRIST_PATH   Camera wrist path (default: 2)"
    echo "  ARM_FOLLOWER_PORT   Follower arm port (default: /dev/ttyACM1)"
    echo ""
    echo "  IMPORTANT: Use the SAME ports as data collection!"
    echo "  Find your paths: python scripts/detect_usb_ports.py --yaml"
    echo ""
    echo "Examples:"
    echo "  $0 --model ~/DoRobot/model"
    echo "  SINGLE_TASK=\"Pick up the apple\" $0 --model ~/DoRobot/model"
    echo ""
    echo "  # With persistent device paths (recommended):"
    echo "  CAMERA_TOP_PATH=\"/dev/v4l/by-path/...\" ARM_FOLLOWER_PORT=\"/dev/serial/by-path/...\" \\"
    echo "    $0 --model ~/DoRobot/model"
}

# Parse arguments
parse_args() {
    MODEL_PATH=""
    EXTRA_ARGS=()

    while [[ $# -gt 0 ]]; do
        case $1 in
            --model)
                MODEL_PATH="$2"
                shift 2
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                EXTRA_ARGS+=("$1")
                shift
                ;;
        esac
    done

    if [ -z "$MODEL_PATH" ]; then
        log_error "Missing required argument: --model PATH"
        echo ""
        print_usage
        exit 1
    fi

    if [ ! -d "$MODEL_PATH" ]; then
        log_error "Model path does not exist: $MODEL_PATH"
        exit 1
    fi
}

# Main entry point
main() {
    parse_args "$@"

    echo ""
    echo "=========================================="
    echo "  SO101 Robot Inference Launcher"
    echo "=========================================="
    echo ""

    # Step 0: Initialize environment
    log_step "Initializing conda environment..."
    init_conda
    activate_env "$CONDA_ENV"

    # Step 0.5: Setup NPU environment
    setup_npu_env

    # Step 0.6: Export device port configuration
    export_device_ports

    # Step 1: Clean up stale sockets
    cleanup_stale_sockets

    # Step 2: Start DORA (control mode)
    start_dora

    # Step 3: Wait for sockets
    if ! wait_for_sockets; then
        log_error "Failed to initialize. Check DORA logs."
        exit 1
    fi

    # Step 3.5: Wait for DORA to fully initialize
    log_step "Waiting ${DORA_INIT_DELAY}s for DORA nodes to initialize..."
    for i in $(seq $DORA_INIT_DELAY -1 1); do
        printf "\r  Initializing... %ds remaining" $i
        sleep 1
    done
    echo ""

    echo ""
    log_info "All systems ready!"
    echo ""
    echo "=========================================="
    echo "  Starting Inference"
    echo "  Model: $MODEL_PATH"
    echo "=========================================="
    echo ""

    # Step 4: Start inference
    start_inference "$MODEL_PATH" "${EXTRA_ARGS[@]}"

    log_info "Inference session ended"
}

# Run main
main "$@"
