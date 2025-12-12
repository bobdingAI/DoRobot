#!/bin/bash
# =============================================================================
# SO101 Robot Inference Launcher (All-in-One)
# =============================================================================
#
# Starts DORA dataflow + Python inference in a single command.
# Uses dora_control_dataflow.yml (follower arm only, no leader needed).
#
# Usage:
#   bash scripts/run_so101_inference.sh [DATASET_PATH] [MODEL_PATH] [SINGLE_TASK]
#
# Examples:
#   bash scripts/run_so101_inference.sh
#   bash scripts/run_so101_inference.sh ~/DoRobot/dataset/my-task ~/DoRobot/model "Pick the apple"
#
# Device Configuration:
#   Uses the same config file as run_so101.sh for port consistency.
#   Create config with: python scripts/detect_usb_ports.py --save
#   Config locations (checked in order):
#     1. ~/.dorobot_device.conf
#     2. /etc/dorobot/device.conf
#     3. $PROJECT_ROOT/.device.conf
#
# Environment Variables (override config file):
#   REPO_ID           - Dataset repo ID (default: so101-test)
#   SINGLE_TASK       - Task description
#   CAMERA_TOP_PATH   - Camera top path/index
#   CAMERA_WRIST_PATH - Camera wrist path/index
#   ARM_FOLLOWER_PORT - Follower arm port
# =============================================================================

set -e

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DORA_DIR="$PROJECT_ROOT/operating_platform/robot/robots/so101_v1"
DORA_GRAPH="dora_control_dataflow.yml"

# =============================================================================
# LOAD CONFIG FILE (same as run_so101.sh for consistency)
# =============================================================================
DEVICE_CONFIG_FILES=(
    "$HOME/.dorobot_device.conf"
    "/etc/dorobot/device.conf"
    "$PROJECT_ROOT/.device.conf"
)

# Load device config if available (BEFORE setting defaults)
LOADED_DEVICE_CONFIG=""
for config_file in "${DEVICE_CONFIG_FILES[@]}"; do
    if [ -f "$config_file" ]; then
        source "$config_file"
        LOADED_DEVICE_CONFIG="$config_file"
        break
    fi
done

# =============================================================================
# DEFAULT VALUES (only used if not set by config file or environment)
# =============================================================================
CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-2}"
ARM_FOLLOWER_PORT="${ARM_FOLLOWER_PORT:-/dev/ttyACM0}"

# Export for DORA dataflow
export CAMERA_TOP_PATH
export CAMERA_WRIST_PATH
export ARM_FOLLOWER_PORT

# Script arguments
REPO_ID="${REPO_ID:-so101-test}"
DATASET_PATH="${1:-$HOME/DoRobot/dataset/$REPO_ID}"
MODEL_PATH="${2:-$HOME/DoRobot/model}"
SINGLE_TASK="${3:-${SINGLE_TASK:-Perform the trained task.}}"

echo "=================================================="
echo "SO101 Inference Launcher"
echo "=================================================="
echo "Dataset:    $DATASET_PATH"
echo "Model:      $MODEL_PATH"
echo "Task:       $SINGLE_TASK"
echo "--------------------------------------------------"
if [ -n "$LOADED_DEVICE_CONFIG" ]; then
    echo "Config:     $LOADED_DEVICE_CONFIG"
else
    echo "Config:     (using defaults)"
fi
echo "Cameras:    top=$CAMERA_TOP_PATH, wrist=$CAMERA_WRIST_PATH"
echo "Arm:        follower=$ARM_FOLLOWER_PORT"
echo "=================================================="

# Cleanup function - proper device release order
cleanup() {
    echo ""
    echo "[INFO] Stopping DORA gracefully..."

    # Step 1: Stop DORA dataflow - sends STOP events to nodes
    cd "$DORA_DIR" && dora stop "$DORA_GRAPH" 2>/dev/null || true

    # Step 2: Send SIGTERM to camera/arm processes FIRST to release devices
    echo "[INFO] Signaling camera processes to release video devices..."
    pkill -SIGTERM -f "camera_opencv/main.py" 2>/dev/null || true

    echo "[INFO] Signaling arm processes to release serial ports..."
    pkill -SIGTERM -f "arm_normal_so101_v1/main.py" 2>/dev/null || true

    # Wait for processes to handle SIGTERM and release devices
    echo "[INFO] Waiting for device release (2s)..."
    sleep 2

    # Step 3: Destroy DORA graph
    dora destroy "$DORA_GRAPH" 2>/dev/null || true
    sleep 1

    # Step 4: Kill DORA process if still running
    if [ -n "$DORA_PID" ] && kill -0 $DORA_PID 2>/dev/null; then
        echo "[INFO] Stopping DORA process..."
        kill -TERM $DORA_PID 2>/dev/null || true
        sleep 1
        kill -9 $DORA_PID 2>/dev/null || true
    fi

    # Step 5: Force kill any remaining camera/arm processes
    pkill -9 -f "camera_opencv/main.py" 2>/dev/null || true
    pkill -9 -f "arm_normal_so101_v1/main.py" 2>/dev/null || true

    # Step 6: Clean up IPC files
    rm -f /tmp/dora-zeromq-so101-* 2>/dev/null || true

    echo "[INFO] Cleanup complete"
}
trap cleanup EXIT INT TERM

# Stop any existing DORA instance
echo "[INFO] Cleaning up previous DORA instances..."
cd "$DORA_DIR"
dora stop "$DORA_GRAPH" 2>/dev/null || true
rm -f /tmp/dora-zeromq-so101-* 2>/dev/null || true

# Start DORA in background
echo "[INFO] Starting DORA: $DORA_GRAPH"
dora run "$DORA_GRAPH" &
DORA_PID=$!

# Wait for DORA to initialize
echo "[INFO] Waiting 5s for DORA nodes to initialize..."
sleep 5

# Check if DORA is still running
if ! kill -0 $DORA_PID 2>/dev/null; then
    echo "[ERROR] DORA failed to start. Check device connections."
    exit 1
fi

# Run inference
cd "$PROJECT_ROOT"
echo "[INFO] Starting inference..."
echo ""

python operating_platform/core/inference.py \
    --robot.type=so101 \
    --robot.leader_arms="{}" \
    --inference.single_task="$SINGLE_TASK" \
    --inference.dataset.repo_id="$DATASET_PATH" \
    --policy.path="$MODEL_PATH"
