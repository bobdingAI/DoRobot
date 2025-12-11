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
# Environment Variables:
#   REPO_ID           - Dataset repo ID (default: so101-test)
#   SINGLE_TASK       - Task description
#   CAMERA_TOP_PATH   - Camera top path/index (default: 0)
#   CAMERA_WRIST_PATH - Camera wrist path/index (default: 2)
#   ARM_FOLLOWER_PORT - Follower arm port (default: /dev/ttyACM0)
# =============================================================================

set -e

# Configuration
REPO_ID="${REPO_ID:-so101-test}"
DATASET_PATH="${1:-$HOME/DoRobot/dataset/$REPO_ID}"
MODEL_PATH="${2:-$HOME/DoRobot/model}"
SINGLE_TASK="${3:-${SINGLE_TASK:-Perform the trained task.}}"

# Device ports
export CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
export CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-2}"
export ARM_FOLLOWER_PORT="${ARM_FOLLOWER_PORT:-/dev/ttyACM0}"

# Paths
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DORA_DIR="$PROJECT_ROOT/operating_platform/robot/robots/so101_v1"
DORA_GRAPH="dora_control_dataflow.yml"

echo "=================================================="
echo "SO101 Inference Launcher"
echo "=================================================="
echo "Dataset:    $DATASET_PATH"
echo "Model:      $MODEL_PATH"
echo "Task:       $SINGLE_TASK"
echo "--------------------------------------------------"
echo "Cameras:    top=$CAMERA_TOP_PATH, wrist=$CAMERA_WRIST_PATH"
echo "Arm:        follower=$ARM_FOLLOWER_PORT"
echo "=================================================="

# Cleanup function
cleanup() {
    echo ""
    echo "[INFO] Stopping DORA..."
    cd "$DORA_DIR" && dora stop "$DORA_GRAPH" 2>/dev/null || true
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
    --inference.single_task="$SINGLE_TASK" \
    --inference.dataset.repo_id="$DATASET_PATH" \
    --policy.path="$MODEL_PATH"
