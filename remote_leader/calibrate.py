#!/usr/bin/env python3
"""
Calibration Script for SO101 Leader Arm (Remote)

This script calibrates the leader arm without DORA dependency.
Run this on the MacBook or any PC with the leader arm connected.

Usage:
    python calibrate.py
    ARM_LEADER_PORT=/dev/tty.usbmodem14101 python calibrate.py
"""

import os
import sys
import time
import threading
from pathlib import Path

import draccus

from motors.feetech import FeetechMotorsBus, OperatingMode
from motors import Motor, MotorCalibration, MotorNormMode


# Configuration
ARM_NAME = os.getenv("ARM_NAME", "SO101-leader")
CALIBRATION_DIR = os.getenv("CALIBRATION_DIR", "./.calibration/")


def find_arm_port():
    """Try to find the arm serial port."""
    # Check environment variable first
    env_port = os.getenv("ARM_LEADER_PORT")
    if env_port:
        return env_port

    # Try common ports (Linux)
    linux_ports = ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0", "/dev/ttyUSB1"]

    # Try macOS ports
    macos_ports = []
    dev_path = Path("/dev")
    if dev_path.exists():
        macos_ports = sorted([
            str(p) for p in dev_path.glob("tty.usbmodem*")
        ])

    for port in macos_ports + linux_ports:
        if Path(port).exists():
            return port

    return None


def save_calibration(calibration: dict, fpath: Path) -> None:
    """Save calibration data to JSON file."""
    with open(fpath, "w") as f, draccus.config_type("json"):
        draccus.dump(calibration, f, indent=4)


def record_ranges_of_motion(bus: FeetechMotorsBus, stop_event: threading.Event):
    """Record min/max positions for all motors."""
    range_mins = {motor: float('inf') for motor in bus.motors}
    range_maxes = {motor: float('-inf') for motor in bus.motors}

    print("\nRecording... Move all joints through their full range.")
    print("Press Enter when done.\n")

    while not stop_event.is_set():
        try:
            positions = bus.sync_read("Present_Position")
            for motor, pos in positions.items():
                range_mins[motor] = min(range_mins[motor], pos)
                range_maxes[motor] = max(range_maxes[motor], pos)
            time.sleep(0.02)  # 50Hz sampling
        except Exception as e:
            print(f"Read error: {e}")
            time.sleep(0.1)

    return range_mins, range_maxes


def main():
    print("=" * 60)
    print("  SO101 Leader Arm Calibration")
    print("=" * 60)
    print()

    # Find port
    port = find_arm_port()
    if not port:
        print("ERROR: Could not find arm port.")
        print("Please set ARM_LEADER_PORT environment variable.")
        print("Example: ARM_LEADER_PORT=/dev/tty.usbmodem14101 python calibrate.py")
        sys.exit(1)

    print(f"Using port: {port}")
    print(f"Arm name: {ARM_NAME}")
    print()

    # Setup calibration directory
    calibration_dir = Path(CALIBRATION_DIR)
    calibration_dir.mkdir(parents=True, exist_ok=True)
    calibration_fpath = calibration_dir / f"{ARM_NAME}.json"

    # Motor configuration
    arm_bus = FeetechMotorsBus(
        port=port,
        motors={
            "shoulder_pan": Motor(1, "sts3215", MotorNormMode.DEGREES),
            "shoulder_lift": Motor(2, "sts3215", MotorNormMode.DEGREES),
            "elbow_flex": Motor(3, "sts3215", MotorNormMode.DEGREES),
            "wrist_flex": Motor(4, "sts3215", MotorNormMode.DEGREES),
            "wrist_roll": Motor(5, "sts3215", MotorNormMode.DEGREES),
            "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
        },
    )

    try:
        # Connect
        print("Connecting to arm...")
        arm_bus.connect()
        arm_bus.disable_torque()
        print("Connected! Torque disabled (arm is passive).\n")

        # Step 1: Set homing position
        print("-" * 60)
        print("STEP 1: Set Homing Position")
        print("-" * 60)
        print()
        print("Move the arm to the MIDDLE of its range of motion:")
        print("  - All joints at ~50% of their travel")
        print("  - Gripper half open")
        print()
        input("Press ENTER when arm is in the middle position...")

        homing_offsets = arm_bus.set_half_turn_homings()
        print("Homing offsets recorded.")
        print()

        # Step 2: Record range of motion
        print("-" * 60)
        print("STEP 2: Record Range of Motion")
        print("-" * 60)
        print()
        print("Now move each joint through its FULL range of motion:")
        print("  - Move each joint from minimum to maximum position")
        print("  - Include gripper open/close")
        print()
        input("Press ENTER to start recording...")

        stop_event = threading.Event()

        # Start recording in background thread
        result = [None, None]
        def record_thread():
            result[0], result[1] = record_ranges_of_motion(arm_bus, stop_event)

        thread = threading.Thread(target=record_thread)
        thread.start()

        # Wait for user to finish
        input("Press ENTER when done moving joints...")
        stop_event.set()
        thread.join()

        range_mins, range_maxes = result

        # Step 3: Save calibration
        print()
        print("-" * 60)
        print("STEP 3: Save Calibration")
        print("-" * 60)
        print()

        calibration = {}
        for motor, m in arm_bus.motors.items():
            calibration[motor] = MotorCalibration(
                id=m.id,
                drive_mode=0,
                homing_offset=homing_offsets[motor],
                range_min=range_mins[motor],
                range_max=range_maxes[motor],
            )

        # Write to motors
        arm_bus.write_calibration(calibration)

        # Save to file
        save_calibration(calibration, calibration_fpath)

        print(f"Calibration saved to: {calibration_fpath}")
        print()
        print("Calibration data:")
        for motor, cal in calibration.items():
            print(f"  {motor}:")
            print(f"    homing_offset: {cal.homing_offset}")
            print(f"    range: [{cal.range_min}, {cal.range_max}]")
        print()
        print("=" * 60)
        print("  Calibration Complete!")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\nCalibration cancelled.")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            arm_bus.disconnect(disable_torque=True)
        except:
            pass


if __name__ == "__main__":
    main()
