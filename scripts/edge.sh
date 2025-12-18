#!/bin/bash
#
# Edge Upload Wrapper Script (Multi-User)
#
# Full workflow: Upload -> Encode -> Train -> Download Model
# This script will NOT exit until training completes and model is downloaded.
#
# Designed for shared edge servers where multiple users run this script.
# Each user must provide their own API credentials for path isolation.
#
# Wrapper for: python scripts/edge_encode.py
#
# Usage:
#   scripts/edge.sh -u <username> -p <password> -d <dataset_path> [options]
#
# Required:
#   -u, --username      API username (for authentication and path isolation)
#   -p, --password      API password
#   -d, --dataset       Path to dataset directory with raw images
#
# Optional:
#   --skip-training     Skip training (just upload + encode)
#   --skip-upload       Skip upload and encoding (trigger training + download)
#   --download-only     Skip upload and training (just wait + download)
#   --repo-id NAME      Custom repo ID (default: folder name)
#   --model-output PATH Custom model output path (default: dataset/model/)
#   --timeout MINUTES   Training timeout in minutes (default: 120)
#   --test-connection   Only test SSH and API connections
#
# Output:
#   Default model output: {dataset_path}/model/
#
# Notes:
#   - Script waits until training completes and model is downloaded
#   - Multiple users can run in parallel (isolated by username)
#   - Use --skip-training for upload+encode only
#
# Examples:
#   scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my_data
#   scripts/edge.sh -u bob -p bob456 -d ~/dataset/test --skip-training
#   scripts/edge.sh -u alice -p alice123 -d ~/data --timeout 180
#   scripts/edge.sh -u alice -p alice123 --test-connection

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Initialize variables
USERNAME=""
PASSWORD=""
DATASET_PATH=""
EXTRA_ARGS=""
TEST_CONNECTION=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--username)
            USERNAME="$2"
            shift 2
            ;;
        -p|--password)
            PASSWORD="$2"
            shift 2
            ;;
        -d|--dataset)
            DATASET_PATH="$2"
            shift 2
            ;;
        --test-connection)
            TEST_CONNECTION=true
            EXTRA_ARGS="$EXTRA_ARGS --test-connection"
            shift
            ;;
        --skip-training)
            EXTRA_ARGS="$EXTRA_ARGS --skip-training"
            shift
            ;;
        --skip-upload)
            EXTRA_ARGS="$EXTRA_ARGS --skip-upload"
            shift
            ;;
        --download-only)
            EXTRA_ARGS="$EXTRA_ARGS --download-only"
            shift
            ;;
        --repo-id)
            EXTRA_ARGS="$EXTRA_ARGS --repo-id $2"
            shift 2
            ;;
        --model-output)
            EXTRA_ARGS="$EXTRA_ARGS --model-output $2"
            shift 2
            ;;
        --timeout)
            EXTRA_ARGS="$EXTRA_ARGS --timeout $2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 -u <username> -p <password> -d <dataset_path> [options]"
            echo ""
            echo "Full workflow: Upload -> Encode -> Train -> Download Model"
            echo ""
            echo "Required:"
            echo "  -u, --username      API username (for authentication and path isolation)"
            echo "  -p, --password      API password"
            echo "  -d, --dataset       Path to dataset directory with raw images"
            echo ""
            echo "Optional:"
            echo "  --skip-training     Skip training (just upload + encode)"
            echo "  --skip-upload       Skip upload and encoding (trigger training + download)"
            echo "  --download-only     Skip upload and training (just wait + download)"
            echo "  --repo-id NAME      Custom repo ID (default: folder name)"
            echo "  --model-output PATH Custom model output path (default: dataset/model/)"
            echo "  --timeout MINUTES   Training timeout in minutes (default: 120)"
            echo "  --test-connection   Only test SSH and API connections"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 -u alice -p alice123 -d ~/DoRobot/dataset/my_data"
            echo "  $0 -u bob -p bob456 -d ~/dataset/test --skip-training"
            echo "  $0 -u alice -p alice123 -d ~/data --model-output /custom/path"
            echo "  $0 -u alice -p alice123 -d ~/data --timeout 180"
            echo "  $0 -u alice -p alice123 --test-connection"
            echo ""
            echo "Output:"
            echo "  Default model path: {dataset_path}/model/"
            echo "  Upload path: /uploaded_data/{username}/{repo_id}/"
            echo ""
            echo "Notes:"
            echo "  - Script will NOT exit until training completes and model downloads"
            echo "  - Multiple users can run in parallel (isolated by username)"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Handle --test-connection (requires username and password)
if [[ "$TEST_CONNECTION" == true ]]; then
    if [[ -z "$USERNAME" ]] || [[ -z "$PASSWORD" ]]; then
        echo -e "${RED}Error: -u username and -p password are required${NC}"
        echo "Usage: $0 -u <username> -p <password> --test-connection"
        exit 1
    fi

    echo -e "${GREEN}Testing edge server connection...${NC}"
    echo "  Username: $USERNAME"
    echo ""

    API_USERNAME="$USERNAME" API_PASSWORD="$PASSWORD" \
        python "$PROJECT_ROOT/scripts/edge_encode.py" --test-connection
    exit $?
fi

# Validate required arguments
if [[ -z "$USERNAME" ]]; then
    echo -e "${RED}Error: -u username is required${NC}"
    echo "Usage: $0 -u <username> -p <password> -d <dataset_path>"
    exit 1
fi

if [[ -z "$PASSWORD" ]]; then
    echo -e "${RED}Error: -p password is required${NC}"
    echo "Usage: $0 -u <username> -p <password> -d <dataset_path>"
    exit 1
fi

if [[ -z "$DATASET_PATH" ]]; then
    echo -e "${RED}Error: -d dataset_path is required${NC}"
    echo "Usage: $0 -u <username> -p <password> -d <dataset_path>"
    exit 1
fi

# Check if dataset path exists
if [[ ! -d "$DATASET_PATH" ]]; then
    echo -e "${RED}Error: Dataset path not found: $DATASET_PATH${NC}"
    exit 1
fi

# Calculate default model output
DATASET_NAME=$(basename "$DATASET_PATH")
DEFAULT_MODEL_PATH="${DATASET_PATH}/model"

# Run edge_encode.py with credentials and options
echo -e "${GREEN}Starting edge workflow...${NC}"
echo "  Username:      $USERNAME"
echo "  Dataset:       $DATASET_PATH"
echo "  Default model: $DEFAULT_MODEL_PATH"
echo "  Upload path:   /uploaded_data/$USERNAME/$DATASET_NAME/"
echo ""
echo -e "${YELLOW}Note: Script will wait for training completion and model download${NC}"
echo ""

API_USERNAME="$USERNAME" API_PASSWORD="$PASSWORD" \
    python "$PROJECT_ROOT/scripts/edge_encode.py" --dataset "$DATASET_PATH" $EXTRA_ARGS
