#!/usr/bin/env python3
"""
Test script to identify which CAN bus controls which physical arm.
This script will move each arm slightly to help identify them.
"""

import time
import sys
from piper_sdk import C_PiperInterface


def test_can_bus(can_bus_name):
    """Test a specific CAN bus by reading current position."""
    print(f"\n{'='*60}")
    print(f"测试 CAN 接口: {can_bus_name}")
    print(f"{'='*60}")

    try:
        # Connect to the CAN bus
        piper = C_PiperInterface(can_bus_name)
        piper.ConnectPort()
        print(f"[{can_bus_name}] 已连接到 CAN 接口")

        # Try to enable the arm
        print(f"[{can_bus_name}] 尝试使能机械臂...")
        enable_flag = piper.EnablePiper()

        if not enable_flag:
            print(f"[{can_bus_name}] ⚠️  机械臂使能失败")
            print(f"[{can_bus_name}] 可能原因：")
            print(f"  1. 该 CAN 接口没有连接机械臂")
            print(f"  2. 机械臂电源未开启")
            print(f"  3. 急停按钮被按下")
            return False

        print(f"[{can_bus_name}] ✓ 机械臂使能成功")

        # Read current joint positions
        current_joint = piper.GetArmJointMsgs()
        positions = [
            current_joint.joint_state.joint_1.real / 1000.0,
            current_joint.joint_state.joint_2.real / 1000.0,
            current_joint.joint_state.joint_3.real / 1000.0,
            current_joint.joint_state.joint_4.real / 1000.0,
            current_joint.joint_state.joint_5.real / 1000.0,
            current_joint.joint_state.joint_6.real / 1000.0,
        ]

        print(f"[{can_bus_name}] 当前关节位置（度）:")
        for i, pos in enumerate(positions, 1):
            print(f"  Joint {i}: {pos:7.2f}°")

        # Read gripper position
        gripper_pos = piper.GetArmGripperMsgs()
        print(f"[{can_bus_name}] 夹爪位置: {gripper_pos.gripper_state.grippers_angle / 1000.0:.2f}°")

        # Disable the arm
        piper.DisablePiper()
        print(f"[{can_bus_name}] 机械臂已禁用")

        return True

    except Exception as e:
        print(f"[{can_bus_name}] ❌ 错误: {e}")
        return False


def main():
    print("\n" + "="*60)
    print("CAN 总线测试工具")
    print("="*60)
    print("\n此脚本将测试 can_left 和 can_right 两个 CAN 接口")
    print("并显示连接到每个接口的机械臂的当前位置。")
    print("\n请确保：")
    print("  1. 两个机械臂的电源都已开启")
    print("  2. 急停按钮未被按下")
    print("  3. 没有其他程序正在使用这些 CAN 接口")

    print("\n开始测试...")

    # Test can_left
    can_left_ok = test_can_bus("can_left")
    time.sleep(1)

    # Test can_right
    can_right_ok = test_can_bus("can_right")

    # Summary
    print(f"\n{'='*60}")
    print("测试结果总结")
    print(f"{'='*60}")
    print(f"can_left:  {'✓ 可用' if can_left_ok else '✗ 不可用或无连接'}")
    print(f"can_right: {'✓ 可用' if can_right_ok else '✗ 不可用或无连接'}")
    print(f"{'='*60}\n")

    if can_left_ok and can_right_ok:
        print("✓ 两个 CAN 接口都可用")
        print("\n请观察上面显示的关节位置，对比实际机械臂的位置，")
        print("以确定哪个 CAN 接口控制哪个物理机械臂。")
    elif can_left_ok or can_right_ok:
        print("⚠️  只有一个 CAN 接口可用")
    else:
        print("❌ 两个 CAN 接口都不可用")
        print("\n请检查：")
        print("  1. CAN 接口是否已启动 (ip link show type can)")
        print("  2. 机械臂电源是否开启")
        print("  3. 是否有其他程序正在使用 CAN 接口")


if __name__ == "__main__":
    main()
