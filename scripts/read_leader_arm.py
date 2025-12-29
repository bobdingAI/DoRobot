#!/usr/bin/env python3
"""读取主臂（SO101 Leader Arm）当前关节位置"""

import sys
import os
import json
import numpy as np
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode


def calculate_calibrated_angle(pwm_val, calib_data, norm_mode):
    """根据标定数据计算校准后的角度"""
    homing_offset = calib_data['homing_offset']
    range_min = calib_data['range_min']
    range_max = calib_data['range_max']
    drive_mode = calib_data['drive_mode']

    # 应用 homing_offset
    calibrated_pwm = pwm_val - homing_offset

    if norm_mode == MotorNormMode.RADIANS:
        # 转换为度数
        degrees = ((calibrated_pwm - range_min) / (range_max - range_min)) * 270.0

        # 应用 drive_mode（反转）
        if drive_mode == 1:
            degrees = -degrees

        # 转换为弧度
        radians = np.deg2rad(degrees)
        return radians, degrees

    elif norm_mode == MotorNormMode.RANGE_0_100:
        # gripper 使用 0-100 范围
        value = ((calibrated_pwm - range_min) / (range_max - range_min)) * 100.0
        return value, value

    return None, None


def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    print("=" * 70)
    print("主臂（SO101 Leader Arm）关节位置读取")
    print("=" * 70)
    print(f"端口: {port}")
    print(f"标定文件: {calib_file}")
    print("=" * 70)
    print()

    # 读取标定文件
    if not os.path.exists(calib_file):
        print(f"错误：标定文件不存在: {calib_file}")
        print("请先运行标定脚本")
        sys.exit(1)

    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 创建舵机总线（使用 joint_N 命名以匹配标定文件）
    motors = {
        "joint_1": Motor(1, "zhonglin", MotorNormMode.RADIANS),
        "joint_2": Motor(2, "zhonglin", MotorNormMode.RADIANS),
        "joint_3": Motor(3, "zhonglin", MotorNormMode.RADIANS),
        "joint_4": Motor(4, "zhonglin", MotorNormMode.RADIANS),
        "joint_5": Motor(5, "zhonglin", MotorNormMode.RADIANS),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        print("【当前关节位置】")
        print("-" * 70)
        print(f"{'关节':<15} {'PWM':<6} {'弧度':<12} {'角度':<12}")
        print("-" * 70)

        joint_positions = []

        for name, motor in bus.motors.items():
            response = bus.send_command(f'#{motor.id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())

            if match:
                pwm_val = int(match.group(1))
                radians, degrees = calculate_calibrated_angle(
                    pwm_val, calib_data[name], motor.norm_mode
                )

                if motor.norm_mode == MotorNormMode.RADIANS:
                    print(f"{name:<15} {pwm_val:<6} {radians:>11.4f} {degrees:>11.3f}°")
                    joint_positions.append(radians)
                else:  # RANGE_0_100
                    print(f"{name:<15} {pwm_val:<6} {radians:>11.2f} {degrees:>11.2f}")
                    joint_positions.append(radians)
            else:
                print(f"{name:<15} ERROR - 无法读取")
                joint_positions.append(0.0)

        print("-" * 70)
        print()

        # 输出数组格式（用于代码）
        print("【数组格式（弧度）】")
        print(f"joint_positions = {joint_positions}")
        print()

        print("【数组格式（度）】")
        degrees_list = [np.rad2deg(pos) if i < 6 else pos for i, pos in enumerate(joint_positions)]
        print(f"joint_positions_degrees = {[round(d, 3) for d in degrees_list]}")
        print()

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
