#!/bin/bash
# SO101 Teleoperation Launcher
# This script handles serial port permissions and launches the teleoperation program

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}SO101 Teleoperation System${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if conda environment exists
if ! conda env list | grep -q "dorobot"; then
    echo -e "${RED}Error: conda environment 'dorobot' not found${NC}"
    echo "Please create the environment first"
    exit 1
fi

# Activate conda environment
echo -e "${YELLOW}Activating conda environment...${NC}"
source ~/miniconda3/etc/profile.d/conda.sh
conda activate dorobot

# Set serial port path for leader arm
if [ -z "$ARM_LEADER_PORT" ]; then
    if [ -e "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" ]; then
        export ARM_LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    elif [ -e "/dev/ttyUSB1" ]; then
        export ARM_LEADER_PORT="/dev/ttyUSB1"
    elif [ -e "/dev/ttyUSB0" ]; then
        export ARM_LEADER_PORT="/dev/ttyUSB0"
    else
        echo -e "${RED}Error: Cannot find leader arm serial port${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}Leader arm port: $ARM_LEADER_PORT${NC}"

# Check and fix leader arm permissions
if [ -e "$ARM_LEADER_PORT" ]; then
    echo -e "${YELLOW}Checking leader arm permissions...${NC}"
    if [ ! -r "$ARM_LEADER_PORT" ] || [ ! -w "$ARM_LEADER_PORT" ]; then
        echo "Fixing permissions (may require password)..."
        if sudo chmod 666 "$ARM_LEADER_PORT"; then
            echo -e "${GREEN}Leader arm permissions fixed${NC}"
        else
            echo -e "${RED}Failed to fix leader arm permissions${NC}"
            exit 1
        fi
    else
        echo -e "${GREEN}Leader arm permissions OK${NC}"
    fi
fi

# Set CAN bus for follower arm
if [ -z "$ARM_FOLLOWER_PORT" ]; then
    export ARM_FOLLOWER_PORT="can0"
fi

echo -e "${GREEN}Follower arm CAN: $ARM_FOLLOWER_PORT${NC}"

# Check CAN interface
if ip link show "$ARM_FOLLOWER_PORT" &>/dev/null; then
    echo -e "${GREEN}CAN interface $ARM_FOLLOWER_PORT found${NC}"
else
    echo -e "${YELLOW}Warning: CAN interface $ARM_FOLLOWER_PORT not found${NC}"
    echo "If using Piper follower arm, make sure CAN is configured"
fi

# Set camera paths (optional)
export CAMERA_TOP_PATH="${CAMERA_TOP_PATH:-0}"
export CAMERA_WRIST_PATH="${CAMERA_WRIST_PATH:-2}"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Starting Teleoperation${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Move the leader arm, and the follower arm will follow"
echo "Press Ctrl+C to stop"
echo ""

# Change to robot directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROBOT_DIR="$SCRIPT_DIR/../../../robots/so101_v1"

if [ ! -d "$ROBOT_DIR" ]; then
    echo -e "${RED}Error: Robot directory not found: $ROBOT_DIR${NC}"
    exit 1
fi

cd "$ROBOT_DIR"

# Run teleoperation
exec dora run dora_teleoperate_dataflow.yml
