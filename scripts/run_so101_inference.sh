#!/bin/bash
# =============================================================================
# SO101 Robot Inference Script (Python Only)
# =============================================================================
#
# PREREQUISITE: Start DORA dataflow in another terminal FIRST:
#
#   # For inference (follower arm only - RECOMMENDED):
#   cd operating_platform/robot/robots/so101_v1
#   dora run dora_control_dataflow.yml
#
#   # OR for teleoperation mode (needs BOTH leader + follower arms):
#   cd operating_platform/robot/robots/so101_v1
#   dora run dora_teleoperate_dataflow.yml
#
# Usage:
#   bash scripts/run_so101_inference.sh [DATASET_PATH] [MODEL_PATH] [SINGLE_TASK]
#
# Examples:
#   bash scripts/run_so101_inference.sh
#   bash scripts/run_so101_inference.sh ~/DoRobot/dataset/my-task ~/DoRobot/model "Pick the apple"
#
# Environment Variables:
#   REPO_ID     - Dataset repo ID (default: so101-test)
#   SINGLE_TASK - Task description (default: "Perform the trained task.")
# =============================================================================

# Configuration
REPO_ID="${REPO_ID:-so101-test}"
DATASET_PATH="${1:-$HOME/DoRobot/dataset/$REPO_ID}"
MODEL_PATH="${2:-$HOME/DoRobot/model}"
SINGLE_TASK="${3:-${SINGLE_TASK:-Perform the trained task.}}"

# Get project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=================================================="
echo "SO101 Inference"
echo "=================================================="
echo "Dataset:    $DATASET_PATH"
echo "Model:      $MODEL_PATH"
echo "Task:       $SINGLE_TASK"
echo "=================================================="
echo ""
echo "NOTE: Make sure DORA is running in another terminal:"
echo "  cd operating_platform/robot/robots/so101_v1"
echo "  dora run dora_control_dataflow.yml"
echo ""
echo "=================================================="

# Run inference
python operating_platform/core/inference.py \
    --robot.type=so101 \
    --inference.single_task="$SINGLE_TASK" \
    --inference.dataset.repo_id="$DATASET_PATH" \
    --policy.path="$MODEL_PATH"
