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
PORT = os.getenv("PORT")
ARM_NAME = os.getenv("ARM_NAME", "SO101-Arm")
CALIBRATION_DIR = os.getenv("CALIBRATION_DIR", "./.calibration/")
USE_DEGRESS = os.getenv("USE_DEGRESS", "True")
ARM_ROLE = os.getenv("ARM_ROLE", "follower")
MOTOR_PROTOCOL = os.getenv("MOTOR_PROTOCOL", "auto")  # auto, feetech, zhonglin


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
    
def configure_follower(bus: FeetechMotorsBus) -> None:
    with bus.torque_disabled():
        bus.configure_motors()
        for motor_name, motor in bus.motors.items():
            bus.write("Operating_Mode", motor, OperatingMode.POSITION.value)
            bus.write("P_Coefficient", motor, 16)
            bus.write("I_Coefficient", motor, 0)
            bus.write("D_Coefficient", motor, 32)
            bus.write("CW_Dead_Zone", motor, 4)
            bus.write("CCW_Dead_Zone", motor, 4)

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
    calibration_fpath = calibration_dir / f"{ARM_NAME}.json"
    name = ARM_NAME

    try:
        with open(calibration_fpath) as f, draccus.config_type("json"):
            arm_calibration = draccus.load(dict[str, MotorCalibration], f)
    except FileNotFoundError:
        raise FileNotFoundError(f"校准文件路径不存在: {calibration_fpath}")
    except IsADirectoryError:
        raise ValueError(f"路径是目录而不是文件: {calibration_fpath}")

    norm_mode_body = MotorNormMode.DEGREES if use_degrees else MotorNormMode.RANGE_M100_100

    # Determine protocol: auto-detect based on ARM_ROLE, or use explicit MOTOR_PROTOCOL
    use_protocol = MOTOR_PROTOCOL
    if use_protocol == "auto":
        use_protocol = "zhonglin" if ARM_ROLE == "leader" else "feetech"

    # Choose motor bus based on protocol
    if use_protocol == "zhonglin":
        # Zhonglin ASCII protocol (ZP10D controller) - original SO101 leader arm
        arm_bus = ZhonglinMotorsBus(
            port=PORT,
            motors={
                "joint_0": Motor(0, "zhonglin", MotorNormMode.RADIANS),
                "joint_1": Motor(1, "zhonglin", MotorNormMode.RADIANS),
                "joint_2": Motor(2, "zhonglin", MotorNormMode.RADIANS),
                "joint_3": Motor(3, "zhonglin", MotorNormMode.RADIANS),
                "joint_4": Motor(4, "zhonglin", MotorNormMode.RADIANS),
                "joint_5": Motor(5, "zhonglin", MotorNormMode.RADIANS),
                "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
            },
            calibration=arm_calibration,
            baudrate=115200,
        )
    elif use_protocol == "feetech":
        if ARM_ROLE == "leader":
            # Feetech protocol leader arm (new configuration)
            # Leader arm outputs radians for Piper follower arm compatibility
            arm_bus = FeetechMotorsBus(
                port=PORT,
                motors={
                    "joint_0": Motor(0, "sts3215", MotorNormMode.RADIANS),
                    "joint_1": Motor(1, "sts3215", MotorNormMode.RADIANS),
                    "joint_2": Motor(2, "sts3215", MotorNormMode.RADIANS),
                    "joint_3": Motor(3, "sts3215", MotorNormMode.RADIANS),
                    "joint_4": Motor(4, "sts3215", MotorNormMode.RADIANS),
                    "joint_5": Motor(5, "sts3215", MotorNormMode.RADIANS),
                    "gripper": Motor(6, "sts3215", MotorNormMode.RADIANS),
                },
                calibration=arm_calibration,
            )
        else:
            # Feetech protocol follower arm (original configuration)
            arm_bus = FeetechMotorsBus(
                port=PORT,
                motors={
                    "joint_0": Motor(0, "sts3215", norm_mode_body),
                    "joint_1": Motor(1, "sts3215", norm_mode_body),
                    "joint_2": Motor(2, "sts3215", norm_mode_body),
                    "joint_3": Motor(3, "sts3215", norm_mode_body),
                    "joint_4": Motor(4, "sts3215", norm_mode_body),
                    "joint_5": Motor(5, "sts3215", norm_mode_body),
                    "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
                },
                calibration=arm_calibration,
            )
    else:
        raise ValueError(f"Unknown MOTOR_PROTOCOL: {use_protocol}. Use 'auto', 'feetech', or 'zhonglin'")

    arm_bus.connect()
    _arm_bus = arm_bus  # Store globally for cleanup

    if ARM_ROLE == "follower":
        configure_follower(arm_bus)
    elif ARM_ROLE == "leader" and isinstance(arm_bus, FeetechMotorsBus):
        configure_leader(arm_bus)
    # Zhonglin leader arms don't need configuration

    ctrl_frame = 0

    # Low-pass filter state for leader arm (smooths sensor noise)
    filtered_positions = None
    filter_alpha = 0.2  # Stronger filtering (was 0.3)

    # Flag to print joint data only once
    joint_data_printed = False

    for event in node:
        if event["type"] == "INPUT":
            if "action" in event["id"]:
                pass

            if event["id"] == "action_joint":
                position = event["value"].to_numpy()

                if ctrl_frame > 0:
                    continue

                goal_pos = {key: position[motor.id] for key, motor in arm_bus.motors.items()}
                arm_bus.sync_write("Goal_Position", goal_pos)

            if event["id"] == "action_joint_ctrl":
                position = event["value"].to_numpy()

                ctrl_frame = 200

                goal_pos = {key: position[motor.id] for key, motor in arm_bus.motors.items()}
                arm_bus.sync_write("Goal_Position", goal_pos)

            elif event["id"] == "get_joint":
                present_pos = arm_bus.sync_read("Present_Position")
                # SO101 now has 7 motors: joint_6 (ID 0) + 5 joints (ID 1-5) + gripper (ID 6)
                joint_value = [val for _motor, val in present_pos.items()]

                # Apply low-pass filter for leader arm to smooth sensor noise
                if ARM_ROLE == "leader":
                    joint_array = np.array(joint_value)
                    if filtered_positions is None:
                        filtered_positions = joint_array
                    else:
                        filtered_positions = filter_alpha * joint_array + (1 - filter_alpha) * filtered_positions
                    joint_value = filtered_positions.tolist()

                # Debug: print what we're sending (only once)
                if not joint_data_printed:
                    print(f"[{ARM_NAME}] 发送关节数据: 长度={len(joint_value)}, 值={[f'{v:.3f}' for v in joint_value]}")
                    joint_data_printed = True

                node.send_output("joint", pa.array(joint_value, type=pa.float32()))

            ctrl_frame -= 1

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
