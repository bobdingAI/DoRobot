#!/bin/bash
#
# Edge Upload Wrapper Script
#
# Uploads raw image datasets to edge server for encoding and training.
# Wrapper for: python scripts/edge_encode.py
#
# Usage:
#   scripts/edge.sh <dataset_path> [options]
#
# Examples:
#   scripts/edge.sh ~/DoRobot/dataset/my_repo_id
#   scripts/edge.sh /home/dora/Public/uploaded_data/gpua/so101_data
#   scripts/edge.sh ~/dataset/my_data --skip-training
#   scripts/edge.sh ~/dataset/my_data --repo-id custom_name
#
# Options:
#   --skip-training    Skip training trigger (just upload + encode)
#   --repo-id NAME     Custom repo ID (default: folder name)
#   --test-connection  Only test SSH and API connections
#
# Environment variables (from ~/.dorobot_device.conf):
#   EDGE_SERVER_HOST, EDGE_SERVER_USER, EDGE_SERVER_PASSWORD
#   EDGE_SERVER_PORT, EDGE_SERVER_PATH
#   API_BASE_URL, API_USERNAME

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# Help message
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]] || [[ -z "$1" && "$1" != "--test-connection" ]]; then
    echo "Usage: $0 <dataset_path> [options]"
    echo ""
    echo "Upload raw image datasets to edge server for encoding and training."
    echo ""
    echo "Arguments:"
    echo "  dataset_path      Path to dataset directory with raw images"
    echo ""
    echo "Options:"
    echo "  --skip-training   Skip training trigger (just upload + encode)"
    echo "  --repo-id NAME    Custom repo ID (default: folder name)"
    echo "  --test-connection Only test SSH and API connections"
    echo "  -h, --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 ~/DoRobot/dataset/my_repo_id"
    echo "  $0 /home/dora/Public/uploaded_data/gpua/so101_data"
    echo "  $0 ~/dataset/my_data --skip-training"
    echo "  $0 --test-connection"
    echo ""
    echo "Upload path: {EDGE_SERVER_PATH}/{API_USERNAME}/{REPO_ID}/"
    exit 0
fi

# Handle --test-connection as first argument
if [[ "$1" == "--test-connection" ]]; then
    echo -e "${GREEN}Testing edge server connection...${NC}"
    python "$PROJECT_ROOT/scripts/edge_encode.py" --test-connection
    exit $?
fi

# First argument is dataset path
DATASET_PATH="$1"
shift

# Check if dataset path exists
if [[ ! -d "$DATASET_PATH" ]]; then
    echo -e "${RED}Error: Dataset path not found: $DATASET_PATH${NC}"
    exit 1
fi

# Run edge_encode.py with the dataset and any additional options
echo -e "${GREEN}Starting edge upload...${NC}"
echo "  Dataset: $DATASET_PATH"
echo ""

python "$PROJECT_ROOT/scripts/edge_encode.py" --dataset "$DATASET_PATH" "$@"
