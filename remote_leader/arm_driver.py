"""
Arm Driver for SO101 Leader Arm

This module provides a simplified interface for reading joint positions
from the Feetech servo motors on the leader arm.
"""

import os
import json
from pathlib import Path
from typing import Optional
from dataclasses import asdict

import draccus

from motors import Motor, MotorCalibration, MotorNormMode
from motors.feetech import FeetechMotorsBus, OperatingMode


# Default motor configuration for SO101
DEFAULT_MOTORS = {
    "shoulder_pan": Motor(1, "sts3215", MotorNormMode.DEGREES),
    "shoulder_lift": Motor(2, "sts3215", MotorNormMode.DEGREES),
    "elbow_flex": Motor(3, "sts3215", MotorNormMode.DEGREES),
    "wrist_flex": Motor(4, "sts3215", MotorNormMode.DEGREES),
    "wrist_roll": Motor(5, "sts3215", MotorNormMode.DEGREES),
    "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
}

MOTOR_NAMES = list(DEFAULT_MOTORS.keys())


class LeaderArmDriver:
    """
    Driver for SO101 leader arm.

    Provides a simple interface for:
    - Connecting to the arm
    - Reading normalized joint positions
    - Accessing calibration data
    """

    def __init__(
        self,
        port: str,
        calibration_path: Optional[str] = None,
        motors: Optional[dict[str, Motor]] = None
    ):
        """
        Initialize the leader arm driver.

        Args:
            port: Serial port for the arm (e.g., "/dev/ttyACM0")
            calibration_path: Path to calibration JSON file
            motors: Motor configuration (uses default if None)
        """
        self.port = port
        self.calibration_path = calibration_path
        self.motors = motors or DEFAULT_MOTORS.copy()

        self._bus: Optional[FeetechMotorsBus] = None
        self._calibration: Optional[dict[str, MotorCalibration]] = None
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to the arm and load calibration.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            # Load calibration if path provided
            if self.calibration_path:
                self._calibration = self._load_calibration(self.calibration_path)
                print(f"[Arm] Loaded calibration from {self.calibration_path}")

            # Create motor bus
            self._bus = FeetechMotorsBus(
                port=self.port,
                motors=self.motors,
                calibration=self._calibration
            )

            # Connect to motors
            self._bus.connect()
            print(f"[Arm] Connected to {len(self.motors)} motors on {self.port}")

            # Disable torque (leader is passive)
            self._bus.disable_torque()
            print("[Arm] Torque disabled (passive mode)")

            self._connected = True
            return True

        except Exception as e:
            print(f"[Arm] Failed to connect: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the arm."""
        if self._bus is not None:
            try:
                self._bus.disconnect(disable_torque=True)
                print("[Arm] Disconnected")
            except Exception as e:
                print(f"[Arm] Error during disconnect: {e}")
            self._bus = None
        self._connected = False

    def read_normalized_positions(self) -> list[float]:
        """
        Read and return normalized joint positions.

        Returns:
            List of 6 normalized values:
            - Joints 0-4: degrees
            - Gripper (5): percentage (0-100)
        """
        if not self._connected or self._bus is None:
            raise RuntimeError("Arm not connected")

        # Read positions from all motors
        positions = self._bus.sync_read("Present_Position")

        # Return in motor order
        return [positions[name] for name in MOTOR_NAMES]

    def get_calibration(self) -> Optional[dict[str, MotorCalibration]]:
        """Get the current calibration."""
        return self._calibration

    def get_calibration_dict(self) -> dict:
        """
        Return calibration as dictionary for Zenoh transmission.

        Returns:
            Dictionary with motor calibration data
        """
        if self._calibration is None:
            return {}

        result = {}
        for name, cal in self._calibration.items():
            result[name] = {
                "id": cal.id,
                "drive_mode": cal.drive_mode,
                "homing_offset": cal.homing_offset,
                "range_min": cal.range_min,
                "range_max": cal.range_max
            }
        return result

    @property
    def is_connected(self) -> bool:
        """Check if the arm is connected."""
        return self._connected

    @staticmethod
    def _load_calibration(path: str) -> dict[str, MotorCalibration]:
        """Load calibration from JSON file."""
        calibration_path = Path(path)
        if not calibration_path.exists():
            raise FileNotFoundError(f"Calibration file not found: {path}")

        with open(calibration_path) as f:
            with draccus.config_type("json"):
                return draccus.load(dict[str, MotorCalibration], f)


def find_arm_port() -> Optional[str]:
    """
    Try to find the arm serial port.

    Returns:
        Port path if found, None otherwise.
    """
    # Check environment variable first
    env_port = os.getenv("ARM_LEADER_PORT")
    if env_port:
        return env_port

    # Try common ports
    common_ports = [
        "/dev/ttyACM0",
        "/dev/ttyACM1",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
    ]

    for port in common_ports:
        if Path(port).exists():
            return port

    return None


def find_calibration_file(arm_name: str = "SO101-leader") -> Optional[str]:
    """
    Try to find the calibration file.

    Args:
        arm_name: Name of the arm

    Returns:
        Path to calibration file if found, None otherwise.
    """
    # Check environment variable first
    env_dir = os.getenv("CALIBRATION_DIR", "./.calibration")
    cal_path = Path(env_dir) / f"{arm_name}.json"

    if cal_path.exists():
        return str(cal_path)

    # Try relative paths
    for base in [".", "..", os.path.dirname(__file__)]:
        cal_path = Path(base) / ".calibration" / f"{arm_name}.json"
        if cal_path.exists():
            return str(cal_path)

    return None
