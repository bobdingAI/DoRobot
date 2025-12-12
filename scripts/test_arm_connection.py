#!/usr/bin/env python3
import sys
import os
import time
from pathlib import Path

# Add the component directory to sys.path to import motors
project_root = Path(__file__).resolve().parent.parent
component_dir = project_root / "operating_platform/robot/components/arm_normal_so101_v1"
sys.path.append(str(component_dir))

try:
    from motors.feetech import FeetechMotorsBus, OperatingMode
    from motors import Motor, MotorCalibration, MotorNormMode
    import draccus
except ImportError as e:
    print(f"Error importing modules: {e}")
    print(f"sys.path: {sys.path}")
    sys.exit(1)

# Default configuration matching main.py
PORT = os.getenv("PORT", "/dev/ttyACM0")
ARM_NAME = "SO101-follower"
CALIBRATION_DIR = component_dir / ".calibration"

def test_connection():
    print(f"Testing connection to arm at {PORT}...")
    
    # Load calibration
    calibration_fpath = CALIBRATION_DIR / f"{ARM_NAME}.json"
    if not calibration_fpath.exists():
        print(f"Calibration file not found at {calibration_fpath}")
        return

    try:
        with open(calibration_fpath) as f, draccus.config_type("json"):
            arm_calibration = draccus.load(dict[str, MotorCalibration], f)
    except Exception as e:
        print(f"Error loading calibration: {e}")
        return

    # Initialize bus
    try:
        arm_bus = FeetechMotorsBus(
            port=PORT,
            motors={
                "shoulder_pan": Motor(1, "sts3215", MotorNormMode.DEGREES),
                "shoulder_lift": Motor(2, "sts3215", MotorNormMode.DEGREES),
                "elbow_flex": Motor(3, "sts3215", MotorNormMode.DEGREES),
                "wrist_flex": Motor(4, "sts3215", MotorNormMode.DEGREES),
                "wrist_roll": Motor(5, "sts3215", MotorNormMode.DEGREES),
                "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
            },
            calibration=arm_calibration,
        )
        
        print("Connecting to bus...")
        arm_bus.connect()
        print("Successfully connected!")
        
        # Try to read positions
        print("Reading positions...")
        present_pos = arm_bus.sync_read("Present_Position")
        print(f"Positions: {present_pos}")
        
        arm_bus.disconnect()
        print("Disconnected.")
        
    except Exception as e:
        print(f"Connection failed: {e}")
        print("\nPossible causes:")
        print("1. Wrong port (check /dev/ttyACM* or /dev/ttyUSB*)")
        print("2. Permission denied (try 'sudo chmod 666 /dev/ttyACM0')")
        print("3. Device not powered or connected")

if __name__ == "__main__":
    test_connection()

