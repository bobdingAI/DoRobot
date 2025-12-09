#!/bin/bash
#
# Unified SO101 Robot Data Collection Launcher
#
# This script starts both DORA dataflow and CLI with proper ordering:
# 1. Cleans up stale ZeroMQ socket files
# 2. Starts DORA dataflow in background
# 3. Waits for ZeroMQ sockets to be ready
# 4. Starts CLI in foreground
# 5. Handles cleanup on exit
#
# Usage:
#   bash scripts/run_so101.sh [options]
#
# Options are passed directly to the CLI (main.py)

set -e

# Version
VERSION="0.2.83"

# Configuration - Single unified environment
CONDA_ENV="${CONDA_ENV:-dorobot}"

# ===========================================================================
# LOAD CONFIG FILE FIRST (before setting any defaults)
# ===========================================================================
# The config file can define any of the settings below. Values from the config
# file take precedence over script defaults, but command-line environment
# variables override everything.
#
# Config file locations (checked in order):
#   1. ~/.dorobot_device.conf
#   2. /etc/dorobot/device.conf
#   3. $PROJECT_ROOT/.device.conf
#
# Generate config with: python scripts/detect_usb_ports.py --save
# ===========================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Device config file locations (checked in order)
DEVICE_CONFIG_FILES=(
    "$HOME/.dorobot_device.conf"
    "/etc/dorobot/device.conf"
    "$PROJECT_ROOT/.device.conf"
)

# Load device config if available (BEFORE setting defaults)
# This allows config file values to be used as defaults
for config_file in "${DEVICE_CONFIG_FILES[@]}"; do
    if [ -f "$config_file" ]; then
        source "$config_file"
        LOADED_DEVICE_CONFIG="$config_file"
        break
    fi
done

# ===========================================================================
# DEFAULT VALUES (only applied if not set by config file or environment)
# ===========================================================================

# NPU Configuration - enabled by default for Orange Pi/Ascend hardware
# Set NPU=0 to disable if not on NPU hardware
NPU="${NPU:-1}"
ASCEND_TOOLKIT_PATH="${ASCEND_TOOLKIT_PATH:-/usr/local/Ascend/ascend-toolkit}"

# Cloud Mode Configuration (shorter name for international users)
# CLOUD modes:
#   0 = Local only (encode locally, no upload)
#   1 = Cloud raw (upload raw images to cloud for encoding)
#   2 = Edge (rsync raw images to edge server)
#   3 = Cloud encoded (encode locally, upload encoded to cloud)
# Edge mode (2) is fastest for LAN transfer
CLOUD="${CLOUD:-2}"

# Edge Server Configuration (only used when CLOUD=2)
EDGE_SERVER_HOST="${EDGE_SERVER_HOST:-127.0.0.1}"
EDGE_SERVER_USER="${EDGE_SERVER_USER:-nupylot}"
EDGE_SERVER_PASSWORD="${EDGE_SERVER_PASSWORD:-}"  # SSH password (uses paramiko if set)
EDGE_SERVER_PORT="${EDGE_SERVER_PORT:-22}"
EDGE_SERVER_PATH="${EDGE_SERVER_PATH:-/uploaded_data}"

# API Server Configuration (for cloud training)
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
API_USERNAME="${API_USERNAME:-}"
API_PASSWORD="${API_PASSWORD:-}"

# ===========================================================================
# DEVICE PORT CONFIGURATION
# ===========================================================================
# For stable operation, use persistent paths instead of numeric indices.
#
# OPTION 1: Create a device config file (RECOMMENDED)
#   Run: python scripts/detect_usb_ports.py --save
#   This creates ~/.dorobot_device.conf with your persistent paths
#
# OPTION 2: Set environment variables before running
#   export CAMERA_TOP_PATH="/dev/v4l/by-path/..."
#   export ARM_LEADER_PORT="/dev/serial/by-path/..."
#
# To find your persistent paths manually:
#   python scripts/detect_usb_ports.py --yaml
#
# ===========================================================================

# Source device config if exists (for logging function, config already loaded above)
load_device_config() {
    for config_file in "${DEVICE_CONFIG_FILES[@]}"; do
        if [ -f "$config_file" ]; then
            log_info "Loading device config from: $config_file"
            source "$config_file"
            return 0
        fi
    done
    return 1
}

# Default values (only used if not set by config file or environment)
# Camera paths - use /dev/v4l/by-path/... for stability
CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-2}"
CAMERA_WRIST2_PATH="${CAMERA_WRIST2_PATH:-4}"

# Arm ports - use /dev/serial/by-path/... or /dev/serial/by-id/... for stability
ARM_LEADER_PORT="${ARM_LEADER_PORT:-/dev/ttyACM0}"
ARM_FOLLOWER_PORT="${ARM_FOLLOWER_PORT:-/dev/ttyACM1}"
ARM_LEADER2_PORT="${ARM_LEADER2_PORT:-/dev/ttyACM2}"
ARM_FOLLOWER2_PORT="${ARM_FOLLOWER2_PORT:-/dev/ttyACM3}"
# ===========================================================================

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DORA_DIR="$PROJECT_ROOT/operating_platform/robot/robots/so101_v1"
SOCKET_IMAGE="/tmp/dora-zeromq-so101-image"
SOCKET_JOINT="/tmp/dora-zeromq-so101-joint"
SOCKET_TIMEOUT="${SOCKET_TIMEOUT:-30}"  # seconds to wait for sockets
DORA_INIT_DELAY="${DORA_INIT_DELAY:-5}"  # seconds to wait after sockets ready for DORA to fully initialize
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
    # Find conda installation
    if [ -n "$CONDA_EXE" ]; then
        CONDA_BASE="$(dirname "$(dirname "$CONDA_EXE")")"
    elif [ -d "$HOME/miniconda3" ]; then
        CONDA_BASE="$HOME/miniconda3"
    elif [ -d "$HOME/anaconda3" ]; then
        CONDA_BASE="$HOME/anaconda3"
    elif [ -d "/opt/conda" ]; then
        CONDA_BASE="/opt/conda"
    else
        log_error "Cannot find conda installation. Please ensure conda is installed."
        exit 1
    fi

    # Source conda.sh to enable conda activate
    if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
    else
        log_error "Cannot find conda.sh at $CONDA_BASE/etc/profile.d/conda.sh"
        exit 1
    fi
}

# Activate the conda environment
activate_env() {
    local env_name="$1"

    # Check if environment exists
    if ! conda env list | grep -q "^${env_name} "; then
        log_error "Conda environment '$env_name' does not exist."
        log_error "Please run: bash scripts/setup_env.sh"
        exit 1
    fi

    conda activate "$env_name"
    log_info "Activated conda environment: $env_name"
}

# Source Ascend NPU environment if needed
setup_npu_env() {
    if [ "$NPU" == "1" ]; then
        log_step "Setting up Ascend NPU environment..."

        local set_env_script="$ASCEND_TOOLKIT_PATH/set_env.sh"
        if [ -f "$set_env_script" ]; then
            source "$set_env_script"
            log_info "Sourced CANN environment from: $set_env_script"
        else
            log_warn "CANN set_env.sh not found at: $set_env_script"
            log_warn "NPU may not work correctly. Set ASCEND_TOOLKIT_PATH if needed."
        fi
    fi
}

# Export device port environment variables for DORA dataflow
export_device_ports() {
    log_step "Configuring device ports..."

    # Log if config file was loaded
    if [ -n "$LOADED_DEVICE_CONFIG" ]; then
        log_info "Loaded device config from: $LOADED_DEVICE_CONFIG"
    fi

    # Export camera paths
    export CAMERA_TOP_PATH
    export CAMERA_WRIST_PATH
    export CAMERA_WRIST2_PATH

    # Export arm ports
    export ARM_LEADER_PORT
    export ARM_FOLLOWER_PORT
    export ARM_LEADER2_PORT
    export ARM_FOLLOWER2_PORT

    # Log configuration
    log_info "Camera configuration:"
    log_info "  camera_top:   $CAMERA_TOP_PATH"
    log_info "  camera_wrist: $CAMERA_WRIST_PATH"
    log_info "Arm configuration:"
    log_info "  leader:   $ARM_LEADER_PORT"
    log_info "  follower: $ARM_FOLLOWER_PORT"

    # Warn if using default indices (may be unstable)
    if [[ "$CAMERA_TOP_PATH" =~ ^[0-9]+$ ]] || [[ "$CAMERA_WRIST_PATH" =~ ^[0-9]+$ ]]; then
        log_warn "Using numeric camera indices - ports may change on restart!"
        log_warn "For stability, create a device config file:"
        log_warn "  python scripts/detect_usb_ports.py --save"
    fi

    if [[ "$ARM_LEADER_PORT" == /dev/ttyACM* ]] || [[ "$ARM_FOLLOWER_PORT" == /dev/ttyACM* ]]; then
        log_warn "Using /dev/ttyACMx paths - ports may change on restart!"
        log_warn "For stability, create a device config file:"
        log_warn "  python scripts/detect_usb_ports.py --save"
    fi
}

# Set device permissions to avoid permission denied errors
set_device_permissions() {
    log_step "Setting device permissions..."

    # Set camera permissions
    for cam_path in "$CAMERA_TOP_PATH" "$CAMERA_WRIST_PATH" "$CAMERA_WRIST2_PATH"; do
        # Skip if it's a numeric index (not a path)
        if [[ "$cam_path" =~ ^[0-9]+$ ]]; then
            # Convert index to /dev/videoX
            cam_path="/dev/video$cam_path"
        fi
        if [ -e "$cam_path" ]; then
            sudo chmod 777 "$cam_path" 2>/dev/null && \
                log_info "Set permissions for: $cam_path" || \
                log_warn "Could not set permissions for: $cam_path"
        fi
    done

    # Set arm serial port permissions
    for arm_port in "$ARM_LEADER_PORT" "$ARM_FOLLOWER_PORT" "$ARM_LEADER2_PORT" "$ARM_FOLLOWER2_PORT"; do
        if [ -e "$arm_port" ]; then
            sudo chmod 777 "$arm_port" 2>/dev/null && \
                log_info "Set permissions for: $arm_port" || \
                log_warn "Could not set permissions for: $arm_port"
        fi
    done
}

# Check device permissions before starting - exit with error if not 777
check_device_permissions() {
    log_step "Checking device permissions..."

    local permission_error=0

    # Check serial port permissions (most critical)
    for arm_port in "$ARM_LEADER_PORT" "$ARM_FOLLOWER_PORT"; do
        if [ -e "$arm_port" ]; then
            # Get permissions (e.g., "crw-rw-rw-" for 666, "crwxrwxrwx" for 777)
            local perms=$(stat -c "%a" "$arm_port" 2>/dev/null || stat -f "%Lp" "$arm_port" 2>/dev/null)
            if [ "$perms" != "777" ]; then
                log_error "Permission denied: $arm_port (current: $perms, required: 777)"
                permission_error=1
            else
                log_info "Permission OK: $arm_port (777)"
            fi
        else
            log_warn "Device not found: $arm_port"
        fi
    done

    if [ $permission_error -eq 1 ]; then
        echo ""
        log_error "=========================================="
        log_error "  PERMISSION ERROR - Cannot continue"
        log_error "=========================================="
        echo ""
        log_error "Serial port permissions are not set correctly."
        log_error "Please run the following command to fix permissions:"
        echo ""
        echo "    bash scripts/detect.sh"
        echo ""
        log_error "Or manually run:"
        echo "    sudo chmod 777 /dev/ttyACM0 /dev/ttyACM1"
        echo "    sudo usermod -aG dialout \$USER"
        echo ""
        log_error "After running detect.sh, you may need to:"
        log_error "  1. Unplug and replug the USB devices"
        log_error "  2. Or log out and log back in"
        echo ""
        exit 1
    fi

    log_info "All device permissions OK"
}

# Cleanup function - called on exit
cleanup() {
    log_step "Cleaning up..."

    # Stop DORA dataflow if running
    if [ -n "$DORA_GRAPH_NAME" ]; then
        log_info "Stopping DORA dataflow: $DORA_GRAPH_NAME"
        dora stop "$DORA_GRAPH_NAME" 2>/dev/null || true
        sleep 1
    fi

    # Destroy DORA graph to ensure all nodes are terminated
    # This is critical to release video devices properly
    if [ -n "$DORA_GRAPH_NAME" ]; then
        log_info "Destroying DORA graph: $DORA_GRAPH_NAME"
        dora destroy "$DORA_GRAPH_NAME" 2>/dev/null || true
        sleep 1
    fi

    # Kill DORA process if still running
    if [ -n "$DORA_PID" ] && kill -0 "$DORA_PID" 2>/dev/null; then
        log_info "Killing DORA process (PID: $DORA_PID)"
        kill "$DORA_PID" 2>/dev/null || true
        sleep 0.5
        # Force kill if still alive
        if kill -0 "$DORA_PID" 2>/dev/null; then
            log_warn "Force killing DORA process..."
            kill -9 "$DORA_PID" 2>/dev/null || true
        fi
        wait "$DORA_PID" 2>/dev/null || true
    fi

    # Kill any remaining camera_opencv processes that might hold /dev/video devices
    log_info "Cleaning up any stale camera processes..."
    pkill -f "camera_opencv/main.py" 2>/dev/null || true

    # Clean up socket files
    if [ -S "$SOCKET_IMAGE" ]; then
        rm -f "$SOCKET_IMAGE"
    fi
    if [ -S "$SOCKET_JOINT" ]; then
        rm -f "$SOCKET_JOINT"
    fi

    log_info "Cleanup complete"
}

# Set up trap for cleanup
trap cleanup EXIT INT TERM

# Clean up stale processes and socket files from previous runs
cleanup_stale_sockets() {
    log_step "Checking for stale processes and socket files..."

    # Kill any stale camera_opencv processes that might be holding /dev/video devices
    if pgrep -f "camera_opencv/main.py" > /dev/null 2>&1; then
        log_warn "Found stale camera processes, killing..."
        pkill -f "camera_opencv/main.py" 2>/dev/null || true
        sleep 1
    fi

    # Kill any stale arm processes
    if pgrep -f "arm_normal_so101_v1/main.py" > /dev/null 2>&1; then
        log_warn "Found stale arm processes, killing..."
        pkill -f "arm_normal_so101_v1/main.py" 2>/dev/null || true
        sleep 1
    fi

    # Kill any stale DORA coordinator processes
    if pgrep -f "dora-coordinator" > /dev/null 2>&1; then
        log_warn "Found stale DORA coordinator, killing..."
        pkill -f "dora-coordinator" 2>/dev/null || true
        sleep 1
    fi

    if [ -e "$SOCKET_IMAGE" ]; then
        log_warn "Removing stale socket: $SOCKET_IMAGE"
        rm -f "$SOCKET_IMAGE"
    fi

    if [ -e "$SOCKET_JOINT" ]; then
        log_warn "Removing stale socket: $SOCKET_JOINT"
        rm -f "$SOCKET_JOINT"
    fi
}

# Wait for ZeroMQ sockets to be created
wait_for_sockets() {
    log_step "Waiting for ZeroMQ sockets to be ready..."

    local elapsed=0
    local poll_interval=0.5

    while [ $elapsed -lt $SOCKET_TIMEOUT ]; do
        # Check if both socket files exist
        if [ -S "$SOCKET_IMAGE" ] && [ -S "$SOCKET_JOINT" ]; then
            log_info "ZeroMQ sockets ready!"
            return 0
        fi

        # Show progress
        printf "\r  Waiting... %ds / %ds" $elapsed $SOCKET_TIMEOUT

        sleep $poll_interval
        elapsed=$((elapsed + 1))
    done

    echo ""  # New line after progress
    log_error "Timeout waiting for ZeroMQ sockets after ${SOCKET_TIMEOUT}s"
    log_error "  Expected: $SOCKET_IMAGE"
    log_error "  Expected: $SOCKET_JOINT"
    return 1
}

# Start DORA dataflow
start_dora() {
    log_step "Starting DORA dataflow..."

    # Check if dora command is available
    if ! command -v dora &> /dev/null; then
        log_error "'dora' command not found. Please ensure dora-rs is installed in the '$CONDA_ENV' environment."
        exit 1
    fi

    # Check if dataflow file exists
    local dataflow_file="$DORA_DIR/dora_teleoperate_dataflow.yml"
    if [ ! -f "$dataflow_file" ]; then
        log_error "Dataflow file not found: $dataflow_file"
        exit 1
    fi

    # Start DORA in background
    cd "$DORA_DIR"

    log_info "Running: dora run dora_teleoperate_dataflow.yml"
    dora run dora_teleoperate_dataflow.yml &
    DORA_PID=$!

    # Give DORA a moment to initialize
    sleep 2

    # Check if DORA is still running
    if ! kill -0 "$DORA_PID" 2>/dev/null; then
        log_error "DORA failed to start"
        exit 1
    fi

    log_info "DORA started (PID: $DORA_PID)"

    # Try to get the graph name for cleaner shutdown
    DORA_GRAPH_NAME=$(dora list 2>/dev/null | grep -oP 'dora_teleoperate_dataflow[^\s]*' | head -1) || true

    cd "$PROJECT_ROOT"
}

# Start CLI
start_cli() {
    log_step "Starting CLI..."

    # Default parameters (can be overridden via command line)
    local repo_id="${REPO_ID:-so101-test}"
    local single_task="${SINGLE_TASK:-start and test so101 arm.}"

    log_info "Running main.py with parameters:"
    log_info "  repo_id: $repo_id"
    log_info "  single_task: $single_task"
    if [ "$CLOUD" == "3" ]; then
        log_info "  cloud_offload: cloud encoded mode (local encoding, upload encoded to cloud)"
    elif [ "$CLOUD" == "2" ]; then
        log_info "  cloud_offload: edge mode (rsync to edge server)"
        log_info "  edge_server: $EDGE_SERVER_USER@$EDGE_SERVER_HOST:$EDGE_SERVER_PORT"
    elif [ "$CLOUD" == "1" ]; then
        log_info "  cloud_offload: cloud raw mode (skip local video encoding)"
    else
        log_info "  cloud_offload: disabled (local video encoding, no upload)"
    fi

    # Export edge server environment variables for edge_upload.py
    export EDGE_SERVER_HOST
    export EDGE_SERVER_USER
    export EDGE_SERVER_PASSWORD
    export EDGE_SERVER_PORT
    export EDGE_SERVER_PATH
    export API_BASE_URL

    # Build command arguments
    local cmd_args=(
        --robot.type=so101
        --record.repo_id="$repo_id"
        --record.single_task="$single_task"
    )

    # Add cloud_offload based on mode (0=local, 1=cloud raw, 2=edge, 3=cloud encoded)
    if [ "$CLOUD" == "3" ]; then
        # Cloud encoded mode - encode locally, upload encoded to cloud
        cmd_args+=(--record.cloud_offload=3)
    elif [ "$CLOUD" == "2" ]; then
        # Edge mode - pass integer 2
        cmd_args+=(--record.cloud_offload=2)
    elif [ "$CLOUD" == "1" ]; then
        # Cloud raw mode - pass integer 1
        cmd_args+=(--record.cloud_offload=1)
    fi

    # Start CLI in foreground (blocks until exit)
    python "$PROJECT_ROOT/operating_platform/core/main.py" \
        "${cmd_args[@]}" \
        "$@"
}

# Print usage
print_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "SO101 Robot Data Collection - Unified Launcher"
    echo ""
    echo "Environment Variables:"
    echo "  CONDA_ENV           Conda environment name (default: dorobot)"
    echo "  REPO_ID             Dataset repository ID (default: so101-test)"
    echo "  SINGLE_TASK         Task description (default: 'start and test so101 arm.')"
    echo "  NPU             Ascend NPU support (default: 1, set to 0 to disable)"
    echo "  CLOUD       Offload mode (default: 2):"
    echo "                        0 = Local only (encode videos locally, no upload)"
    echo "                        1 = Cloud raw (upload raw images to cloud for encoding)"
    echo "                        2 = Edge mode (rsync to edge server, fastest for LAN)"
    echo "                        3 = Cloud encoded (encode locally, upload encoded to cloud)"
    echo "  ASCEND_TOOLKIT_PATH Path to CANN toolkit (default: /usr/local/Ascend/ascend-toolkit)"
    echo "  DORA_INIT_DELAY     Seconds to wait for DORA to initialize (default: 5)"
    echo "  SOCKET_TIMEOUT      Seconds to wait for ZeroMQ sockets (default: 30)"
    echo ""
    echo "Edge Server Configuration (for CLOUD=2):"
    echo "  EDGE_SERVER_HOST    Edge server IP address (default: 192.168.1.100)"
    echo "  EDGE_SERVER_USER    SSH user on edge server (default: dorobot)"
    echo "  EDGE_SERVER_PASSWORD SSH password for edge server (uses paramiko if set)"
    echo "  EDGE_SERVER_PORT    SSH port (default: 22)"
    echo "  EDGE_SERVER_PATH    Upload directory on edge server (default: /uploaded_data)"
    echo ""
    echo "Device Port Configuration (for stable operation):"
    echo "  CAMERA_TOP_PATH     Camera top path or index (default: 0)"
    echo "  CAMERA_WRIST_PATH   Camera wrist path or index (default: 2)"
    echo "  ARM_LEADER_PORT     Leader arm serial port (default: /dev/ttyACM0)"
    echo "  ARM_FOLLOWER_PORT   Follower arm serial port (default: /dev/ttyACM1)"
    echo ""
    echo "  For stable ports, use persistent paths:"
    echo "    CAMERA_TOP_PATH=\"/dev/v4l/by-path/platform-xxx-video-index0\""
    echo "    ARM_LEADER_PORT=\"/dev/serial/by-path/platform-xxx-port0\""
    echo ""
    echo "  Find your persistent paths with:"
    echo "    python scripts/detect_usb_ports.py --yaml"
    echo ""
    echo "Examples:"
    echo "  $0                              # Default: local mode + NPU enabled"
    echo "  REPO_ID=my-dataset $0           # Custom dataset name"
    echo ""
    echo "  # Edge mode (fastest - rsync to edge server on same LAN):"
    echo "  CLOUD=2 $0"
    echo ""
    echo "  # Edge mode with custom server:"
    echo "  CLOUD=2 EDGE_SERVER_HOST=192.168.1.200 $0"
    echo ""
    echo "  # Cloud raw mode (upload raw images directly to cloud):"
    echo "  CLOUD=1 $0"
    echo ""
    echo "  # Cloud encoded mode (encode locally, upload encoded to cloud):"
    echo "  CLOUD=3 $0"
    echo ""
    echo "  # Local only mode (encode videos locally, no upload):"
    echo "  CLOUD=0 $0"
    echo ""
    echo "  # With persistent device paths (recommended for stability):"
    echo "  CAMERA_TOP_PATH=\"/dev/v4l/by-path/...\" ARM_LEADER_PORT=\"/dev/serial/by-path/...\" $0"
    echo ""
    echo "  # Disable NPU (for non-Ascend hardware):"
    echo "  NPU=0 $0"
    echo ""
    echo "  # With longer init delay (if timeout issues):"
    echo "  DORA_INIT_DELAY=10 $0"
    echo ""
    echo "Note: This script starts both DORA dataflow and CLI automatically."
    echo "      Press 'n' to save episode and start new one."
    echo "      Press 'e' to stop recording and exit (with cloud training if enabled)."
}

# Main entry point
main() {
    # Handle help flag
    if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
        print_usage
        exit 0
    fi

    echo ""
    echo "=========================================="
    echo "  SO101 Robot Data Collection Launcher"
    echo "  Version: $VERSION"
    echo "=========================================="
    echo ""

    # Step 0: Initialize and activate conda environment
    log_step "Initializing conda environment..."
    init_conda
    activate_env "$CONDA_ENV"

    # Step 0.5: Setup NPU environment if needed
    setup_npu_env

    # Step 0.6: Export device port configuration
    export_device_ports

    # Step 0.7: Set device permissions
    set_device_permissions

    # Step 1: Clean up stale sockets
    cleanup_stale_sockets

    # Step 2: Start DORA
    start_dora

    # Step 3: Wait for sockets
    if ! wait_for_sockets; then
        log_error "Failed to initialize. Check DORA logs for errors."
        exit 1
    fi

    # Step 3.5: Wait for DORA to fully initialize (cameras, arms, etc.)
    log_step "Waiting ${DORA_INIT_DELAY}s for DORA nodes to fully initialize..."
    for i in $(seq $DORA_INIT_DELAY -1 1); do
        printf "\r  Initializing... %ds remaining" $i
        sleep 1
    done
    echo ""

    # Step 3.6: Final permission check before starting
    check_device_permissions

    echo ""
    log_info "All systems ready!"
    echo ""
    echo "=========================================="
    echo "  Controls:"
    echo "    'n'     - Save episode and start new one"
    echo "    'p'     - Proceed after robot reset"
    if [ "$CLOUD" == "3" ]; then
        echo "    'e'     - Stop, encode locally, upload to cloud"
    elif [ "$CLOUD" == "2" ]; then
        echo "    'e'     - Stop, rsync to edge server"
    elif [ "$CLOUD" == "1" ]; then
        echo "    'e'     - Stop, upload raw to cloud, and train"
    else
        echo "    'e'     - Stop recording and exit (no upload)"
    fi
    echo "    Ctrl+C  - Emergency stop and exit"
    echo ""
    if [ "$CLOUD" == "3" ]; then
        echo "  Mode: Cloud Encoded (local encode → cloud)"
    elif [ "$CLOUD" == "2" ]; then
        echo "  Mode: Edge Upload (rsync to $EDGE_SERVER_HOST)"
    elif [ "$CLOUD" == "1" ]; then
        echo "  Mode: Cloud Raw (upload raw images)"
    else
        echo "  Mode: Local Only (encode locally, no upload)"
    fi
    echo "=========================================="
    echo ""

    # Step 4: Start CLI (blocks until exit)
    start_cli "$@"

    log_info "Recording session ended"
}

# Run main
main "$@"
