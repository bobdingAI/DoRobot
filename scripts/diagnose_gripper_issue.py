#!/usr/bin/env python3
"""诊断主臂和从臂夹爪映射问题"""

import sys
import os
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode, MotorCalibration
import scservo_sdk as scs


def read_motor_value(bus, motor_id, address):
    """读取舵机寄存器值"""
    val, result, error = bus.packet_handler.read2ByteTxRx(
        bus.port_handler, motor_id, address
    )
    if result == scs.COMM_SUCCESS:
        return val
    return None


def main():
    # 读取标定文件
    leader_calib_file = 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json'
    follower_calib_file = 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-follower.json'

    with open(leader_calib_file, 'r') as f:
        leader_calib_data = json.load(f)

    with open(follower_calib_file, 'r') as f:
        follower_calib_data = json.load(f)

    leader_gripper = leader_calib_data['gripper']
    follower_gripper = follower_calib_data['gripper']

    print("=" * 80)
    print("夹爪映射诊断工具")
    print("=" * 80)
    print()
    print("主臂夹爪标定:")
    print(f"  range: {leader_gripper['range_min']} - {leader_gripper['range_max']} ({leader_gripper['range_max'] - leader_gripper['range_min']} 步)")
    print(f"  homing_offset: {leader_gripper['homing_offset']}")
    print(f"  drive_mode: {leader_gripper['drive_mode']}")
    print()
    print("从臂夹爪标定:")
    print(f"  range: {follower_gripper['range_min']} - {follower_gripper['range_max']} ({follower_gripper['range_max'] - follower_gripper['range_min']} 步)")
    print(f"  homing_offset: {follower_gripper['homing_offset']}")
    print(f"  drive_mode: {follower_gripper['drive_mode']}")
    print()

    # 检查溢出风险
    max_actual = follower_gripper['range_max'] + follower_gripper['homing_offset']
    if max_actual > 4095:
        print(f"⚠️  警告: 从臂最大实际位置 {max_actual} 超过 4095，会溢出!")
    else:
        print(f"✓ 从臂最大实际位置 {max_actual} < 4095，无溢出风险")
    print()

    # 连接主臂
    leader_port = input("请输入主臂串口 (默认 /dev/ttyACM0): ").strip() or '/dev/ttyACM0'
    follower_port = input("请输入从臂串口 (默认 /dev/ttyUSB0): ").strip() or '/dev/ttyUSB0'

    print()
    print("正在连接主臂...")
    leader_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
    leader_calib = {"gripper": MotorCalibration(**leader_gripper)}
    leader_bus = FeetechMotorsBus(port=leader_port, motors=leader_motors, calibration=leader_calib)
    leader_bus.connect()
    print("✓ 主臂连接成功")

    print("正在连接从臂...")
    follower_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
    follower_calib = {"gripper": MotorCalibration(**follower_gripper)}
    follower_bus = FeetechMotorsBus(port=follower_port, motors=follower_motors, calibration=follower_calib)
    follower_bus.connect()
    print("✓ 从臂连接成功")
    print()

    # 检查从臂舵机的 homing_offset 是否已写入
    print("检查从臂舵机硬件配置...")
    hw_homing_offset = read_motor_value(follower_bus, 6, 31)  # Homing_Offset 地址
    hw_min_limit = read_motor_value(follower_bus, 6, 9)       # Min_Position_Limit 地址
    hw_max_limit = read_motor_value(follower_bus, 6, 11)      # Max_Position_Limit 地址

    print(f"  硬件 Homing_Offset: {hw_homing_offset} (标定文件: {follower_gripper['homing_offset']})")
    print(f"  硬件 Min_Limit: {hw_min_limit} (标定文件: {follower_gripper['range_min']})")
    print(f"  硬件 Max_Limit: {hw_max_limit} (标定文件: {follower_gripper['range_max']})")

    if hw_homing_offset != follower_gripper['homing_offset']:
        print()
        print("⚠️  警告: 硬件 homing_offset 与标定文件不一致!")
        print("   需要将标定写入舵机硬件。")
        response = input("   是否现在写入? (y/n): ").strip().lower()
        if response == 'y':
            print("   正在写入标定到舵机...")
            follower_bus.write_calibration(follower_calib)
            time.sleep(0.5)
            hw_homing_offset = read_motor_value(follower_bus, 6, 31)
            print(f"   ✓ 写入完成，当前硬件 homing_offset: {hw_homing_offset}")
    print()

    print("=" * 80)
    print("开始实时监控 (按 Ctrl+C 退出)")
    print("=" * 80)
    print()
    print("主臂PWM | 主臂归一化 | 从臂目标PWM | 从臂实际PWM | 从臂归一化 | 状态")
    print("-" * 80)

    try:
        while True:
            # 读取主臂位置
            leader_pwm = read_motor_value(leader_bus, 6, 56)  # Present_Position
            if leader_pwm is None:
                continue

            # 读取从臂位置
            follower_pwm = read_motor_value(follower_bus, 6, 56)  # Present_Position
            if follower_pwm is None:
                continue

            # 计算主臂归一化值
            leader_norm = leader_bus._normalize({6: leader_pwm})[6]

            # 计算从臂目标值
            follower_target_pwm = follower_bus._unnormalize({6: leader_norm})[6]

            # 计算从臂归一化值
            follower_norm = follower_bus._normalize({6: follower_pwm})[6]

            # 判断状态
            diff = abs(follower_pwm - follower_target_pwm)
            if diff > 50:
                status = f"❌ 偏差 {diff}"
            else:
                status = "✓"

            print(f"\r{leader_pwm:4d}    | {leader_norm:6.1f}%     | {follower_target_pwm:4d}        | {follower_pwm:4d}         | {follower_norm:6.1f}%     | {status}   ", end='', flush=True)

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n\n监控结束")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            leader_bus.disconnect()
            follower_bus.disconnect()
        except:
            pass


if __name__ == "__main__":
    main()
