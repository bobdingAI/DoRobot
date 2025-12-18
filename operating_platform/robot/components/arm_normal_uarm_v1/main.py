"""TODO: Add docstring."""

import os
import time
import atexit
import signal

import numpy as np
import pyarrow as pa
import draccus
from dora import Node
from pathlib import Path

from motors.feetech import FeetechMotorsBus, OperatingMode
from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorCalibration, MotorNormMode


# Global reference for cleanup
_arm_bus = None


def cleanup_arm_bus():
    """Release arm bus (serial port) on exit."""
    global _arm_bus
    if _arm_bus is not None:
        try:
            _arm_bus.disconnect(disable_torque=True)
            print(f"[{ARM_NAME}] Serial port released")
        except Exception as e:
            print(f"[{ARM_NAME}] Error releasing serial port: {e}")
        _arm_bus = None


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM to ensure cleanup."""
    print(f"[{ARM_NAME}] Received signal {signum}, cleaning up...")
    cleanup_arm_bus()
    exit(0)


GET_DEVICE_FROM = os.getenv("GET_DEVICE_FROM", "PORT") # SN or INDEX
PORT = os.getenv("PORT", "/dev/ttyUSB0")
ARM_NAME = os.getenv("ARM_NAME", "UArm-Leader")
CALIBRATION_DIR = os.getenv("CALIBRATION_DIR", "./.calibration/")
USE_DEGRESS = os.getenv("USE_DEGRESS", "True")
ARM_ROLE = os.getenv("ARM_ROLE", "leader")
SERVO_TYPE = os.getenv("SERVO_TYPE", "zhonglin")  # feetech or zhonglin


def env_to_bool(env_value: str, default: bool = True) -> bool:
    """将环境变量字符串转换为布尔值"""
    if env_value is None:
        return default
    
    true_values = {'True', 'true', '1', 'yes', 'on', 't', 'y'}
    false_values = {'False', 'false', '0', 'no', 'off', 'f', 'n'}
    
    value_lower = env_value.strip().lower()
    
    if value_lower in true_values:
        return True
    elif value_lower in false_values:
        return False
    else:
        raise ValueError(f"无效的布尔值: {env_value}")
    
def configure_leader(bus: FeetechMotorsBus) -> None:
    bus.disable_torque()
    bus.configure_motors()
    for motor in bus.motors:
        bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)


def main():
    global _arm_bus

    # Register cleanup handlers
    atexit.register(cleanup_arm_bus)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    node = Node()

    use_degrees = env_to_bool(USE_DEGRESS)
    calibration_dir = Path(CALIBRATION_DIR).resolve()
    # Ensure calibration directory exists
    calibration_dir.mkdir(parents=True, exist_ok=True)
    
    calibration_fpath = calibration_dir / f"{ARM_NAME}.json"
    name = ARM_NAME

    try:
        with open(calibration_fpath) as f, draccus.config_type("json"):
            arm_calibration = draccus.load(dict[str, MotorCalibration], f)
    except FileNotFoundError:
        print(f"[{ARM_NAME}] Calibration file not found at: {calibration_fpath}. Using default calibration (0-4095).")
        # Create default calibration for all joints
        arm_calibration = {}
        for motor_name in ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6", "gripper"]:
            arm_calibration[motor_name] = MotorCalibration(
                id=0, # placeholder, will be filled if used
                drive_mode=0,
                homing_offset=0,
                range_min=0,
                range_max=4095 if SERVO_TYPE == "feetech" else 270 # Zhonglin uses degrees internally in my driver
            )
    except IsADirectoryError:
        raise ValueError(f"路径是目录而不是文件: {calibration_fpath}")

    norm_mode_body = MotorNormMode.DEGREES if use_degrees else MotorNormMode.RANGE_M100_100

    if SERVO_TYPE == "feetech":
        motors_config = {
            "joint_1": Motor(1, "sts3215", norm_mode_body),
            "joint_2": Motor(2, "sts3215", norm_mode_body),
            "joint_3": Motor(3, "sts3215", norm_mode_body),
            "joint_4": Motor(4, "sts3215", norm_mode_body),
            "joint_5": Motor(5, "sts3215", norm_mode_body),
            "joint_6": Motor(6, "sts3215", norm_mode_body),
            "gripper": Motor(7, "sts3215", MotorNormMode.RANGE_0_100),
        }
    else:
        motors_config = {
            "joint_1": Motor(0, "zhonglin", norm_mode_body),
            "joint_2": Motor(1, "zhonglin", norm_mode_body),
            "joint_3": Motor(2, "zhonglin", norm_mode_body),
            "joint_4": Motor(3, "zhonglin", norm_mode_body),
            "joint_5": Motor(4, "zhonglin", norm_mode_body),
            "joint_6": Motor(5, "zhonglin", norm_mode_body),
            "gripper": Motor(6, "zhonglin", MotorNormMode.RANGE_0_100),
        }

    # Ensure calibration IDs match motor config IDs if default was used
    for name, motor in motors_config.items():
        if arm_calibration[name].id == 0:
            arm_calibration[name].id = motor.id

    if SERVO_TYPE == "feetech":
        arm_bus = FeetechMotorsBus(
            port=PORT,
            motors=motors_config,
            calibration=arm_calibration,
        )
    else:
        arm_bus = ZhonglinMotorsBus(
            port=PORT,
            motors=motors_config,
            calibration=arm_calibration,
        )

    arm_bus.connect()
    _arm_bus = arm_bus  # Store globally for cleanup

    # UArm component is used as a leader arm, so we always configure it as such
    if SERVO_TYPE == "feetech":
        configure_leader(arm_bus)
    
    # For Zhonglin, initialization (unlocking) is handled in the driver's connect()

    # Software-based zeroing for leader arms
    start_pos = None
    if ARM_ROLE == "leader":
        print(f"[{ARM_NAME}] Recording start position for software zeroing... (DON'T MOVE THE ARM)")
        # Give it a moment to stabilize
        time.sleep(1.0)
        start_pos = arm_bus.sync_read("Present_Position")
        print(f"[{ARM_NAME}] Start positions (zero reference): {start_pos}")

    for event in node:
        if event["type"] == "INPUT":
            if event["id"] == "get_joint":
                joint_value = []
                present_pos = arm_bus.sync_read("Present_Position")
                # present_pos is a dict {motor_name: value}
                # Order matters: joint_1, joint_2, ..., joint_6, gripper
                for motor_name in ["joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6", "gripper"]:
                    val = present_pos[motor_name]
                    
                    # Apply software zeroing if leader
                    if start_pos and motor_name in start_pos:
                        val = val - start_pos[motor_name]

                    if motor_name == "gripper":
                        # Map gripper value to meters (e.g. 0 to 0.05)
                        # The Piper gripper range is approx 0 to 0.05m
                        if SERVO_TYPE == "feetech":
                            # Feetech range 0-100 (MotorNormMode.RANGE_0_100)
                            # However, if we zeroed it, val is relative to start.
                            # If start was "opened" (e.g. 100), then current 100 -> 0.
                            # Usually for leader we want 0 to be "as is" and positive to be "closing".
                            # Let's just normalize to 0.05m based on range.
                            val = (val / 100.0) * 0.05
                        else:
                            # Zhonglin degrees (approx 0-270)
                            # Let's map 0-180 degrees to 0-0.05m
                            val = np.clip(val, 0, 180) / 180.0 * 0.05
                    else:
                        # Convert degrees to radians
                        if use_degrees or (SERVO_TYPE == "feetech" and norm_mode_body == MotorNormMode.DEGREES):
                            val = np.deg2rad(val)
                        else:
                            # If not using degrees, assume -100 to 100 range and map to -pi/2 to pi/2
                            val = (val / 100.0) * (np.pi / 2.0)
                    
                    joint_value.append(val)

                node.send_output("joint", pa.array(joint_value, type=pa.float32()))

        elif event["type"] == "STOP":
            print(f"[{ARM_NAME}] Received STOP event, cleaning up...")
            cleanup_arm_bus()
            break

    # Final cleanup (in case loop exits without STOP event)
    cleanup_arm_bus()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[{ARM_NAME}] Error in main: {e}")
        cleanup_arm_bus()
    finally:
        cleanup_arm_bus()

