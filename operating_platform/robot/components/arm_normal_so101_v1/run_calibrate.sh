#!/bin/bash
# SO101 Leader Arm Calibration Launcher
# This script handles serial port permissions and launches the calibration program

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}SO101 Leader Arm Calibration${NC}"
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

# Set serial port path
if [ -z "$ARM_LEADER_PORT" ]; then
    # Try to find the serial port automatically
    if [ -e "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0" ]; then
        export ARM_LEADER_PORT="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
    elif [ -e "/dev/ttyUSB1" ]; then
        export ARM_LEADER_PORT="/dev/ttyUSB1"
    elif [ -e "/dev/ttyUSB0" ]; then
        export ARM_LEADER_PORT="/dev/ttyUSB0"
    else
        echo -e "${RED}Error: Cannot find serial port device${NC}"
        echo "Available devices:"
        ls -l /dev/ttyUSB* 2>/dev/null || echo "  No /dev/ttyUSB* devices found"
        ls -l /dev/serial/by-id/ 2>/dev/null || echo "  No /dev/serial/by-id/ devices found"
        exit 1
    fi
fi

echo -e "${GREEN}Using serial port: $ARM_LEADER_PORT${NC}"

# Check if device exists
if [ ! -e "$ARM_LEADER_PORT" ]; then
    echo -e "${RED}Error: Serial port device not found: $ARM_LEADER_PORT${NC}"
    exit 1
fi

# Check and fix permissions
echo -e "${YELLOW}Checking serial port permissions...${NC}"
if [ ! -r "$ARM_LEADER_PORT" ] || [ ! -w "$ARM_LEADER_PORT" ]; then
    echo -e "${YELLOW}Serial port requires permission adjustment${NC}"
    echo "Attempting to fix permissions (may require password)..."

    # Try to fix permissions with sudo
    if sudo chmod 666 "$ARM_LEADER_PORT"; then
        echo -e "${GREEN}Permissions fixed successfully${NC}"
    else
        echo -e "${RED}Failed to fix permissions${NC}"
        echo ""
        echo "Please run manually:"
        echo "  sudo chmod 666 $ARM_LEADER_PORT"
        echo ""
        echo "Or add your user to dialout group (permanent solution):"
        echo "  sudo usermod -a -G dialout \$USER"
        echo "  (requires logout/login to take effect)"
        exit 1
    fi
else
    echo -e "${GREEN}Permissions OK${NC}"
fi

# Display current permissions
ls -l "$ARM_LEADER_PORT"
echo ""

# Launch calibration program
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Starting Calibration Program${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Instructions:"
echo "  1. Move the arm to middle position, press 'm'"
echo "  2. Move each joint through full range"
echo "  3. Press 'e' to finish"
echo "  4. Press Ctrl+C to exit"
echo ""

# Change to component directory
cd "$(dirname "$0")"

# Run calibration
exec dora run dora_calibrate_leader.yml
