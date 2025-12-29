#!/usr/bin/env python3
"""Test script to move Piper arm to a target joint position."""

import os
import sys
import time
import argparse
from piper_sdk import C_PiperInterface


def enable_arm(piper: C_PiperInterface, timeout: float = 5.0) -> bool:
    """Enable the arm with timeout."""
    enable_flag = all(piper.GetArmEnableStatus())

    if not enable_flag:
        piper.EnablePiper()
        time.sleep(0.5)

    print("Arm enabled successfully")
    return True


def move_to_position(piper: C_PiperInterface, target: list[int], speed: int = 30):
    """Move arm to target joint position."""
    if len(target) != 6:
        raise ValueError("Target must have 6 joint values")

    # Set motion speed (30% for safe slow movement)
    piper.MotionCtrl_2(0x01, 0x01, speed, 0x00)

    # Send joint command
    piper.JointCtrl(target[0], target[1], target[2], target[3], target[4], target[5])
    print(f"Moving to: {target}")


def get_current_position(piper: C_PiperInterface) -> list[int]:
    """Read current joint positions from arm."""
    joint = piper.GetArmJointMsgs()
    current = [
        joint.joint_state.joint_1.real,
        joint.joint_state.joint_2.real,
        joint.joint_state.joint_3.real,
        joint.joint_state.joint_4.real,
        joint.joint_state.joint_5.real,
        joint.joint_state.joint_6.real,
    ]
    return current


def main():
    parser = argparse.ArgumentParser(description="Move Piper arm to target position")
    parser.add_argument(
        "--target",
        type=int,
        nargs=6,
        help="Target joint positions (6 values in 0.001 degree units)",
    )
    parser.add_argument(
        "--speed",
        type=int,
        default=30,
        help="Motion speed percentage (default: 30)",
    )
    parser.add_argument(
        "--can-bus",
        type=str,
        default="",
        help="CAN bus interface (default: from CAN_BUS env var)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Only read and display current position, don't move",
    )

    args = parser.parse_args()

    can_bus = args.can_bus or os.getenv("CAN_BUS", "")

    print(f"Initializing Piper arm on CAN bus: {can_bus or 'default'}")
    piper = C_PiperInterface(can_bus)
    piper.ConnectPort()

    if not enable_arm(piper):
        sys.exit(1)

    # Read current position
    print("\n读取当前关节位置...")
    current_pos = get_current_position(piper)
    print(f"当前位置: {current_pos}")
    print(f"当前位置（度）: {[p/1000 for p in current_pos]}")

    # If read-only mode, exit here
    if args.read_only:
        print("\n提示：将此位置用作起始位置，请复制上面的数组到代码中")
        return

    # Test: Only move joint_5 (index 4) to 5 degrees
    # Keep all other joints at current position
    target = current_pos.copy()
    target[4] = 5000  # Move joint_5 to 5 degrees (5000 millidegrees)

    print(f"\n测试移动 joint_5 (速度: {args.speed}%)...")
    print(f"当前位置: {current_pos}")
    print(f"目标位置: {target}")
    print(f"变化: joint_5 从 {current_pos[4]/1000:.2f}° 到 {target[4]/1000:.2f}°")
    move_to_position(piper, target, args.speed)

    print("运动命令已发送，等待3秒...")
    time.sleep(3)

    # Read position again to verify movement
    final_pos = get_current_position(piper)
    print(f"\n最终位置: {final_pos}")
    print(f"最终位置（度）: {[p/1000 for p in final_pos]}")
    print(f"\njoint_5 变化: {current_pos[4]/1000:.2f}° → {final_pos[4]/1000:.2f}° (目标: {target[4]/1000:.2f}°)")

    if abs(final_pos[4] - target[4]) < 100:
        print("✓ joint_5 移动成功")
    else:
        print(f"✗ joint_5 未到达目标位置 (差异: {abs(final_pos[4] - target[4])/1000:.2f}°)")


if __name__ == "__main__":
    main()
