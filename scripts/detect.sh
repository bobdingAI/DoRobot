#!/bin/bash
#
# Quick device detection and permission setup
#
# This script detects USB devices (cameras, robot arms) and:
# 1. Saves their persistent paths to ~/.dorobot_device.conf
# 2. Sets chmod 777 permissions on all detected devices
#
# Usage:
#   bash scripts/detect.sh
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=========================================="
echo "  DoRobot Device Detection & Setup"
echo "=========================================="
echo ""

python "$SCRIPT_DIR/detect_usb_ports.py" --save --chmod
