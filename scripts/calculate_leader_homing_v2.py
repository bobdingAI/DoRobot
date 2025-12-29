#!/usr/bin/env python3
"""计算主臂 homing_offset 以匹配从臂初始位置"""

import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode
import re

# 从臂的安全初始位置（度）- 从 arm_normal_piper_v2/main.py 第63行
# safe_home_position = [5370, -2113, 3941, 3046, 18644, 24400] millidegrees
# 这是 Piper 能够达到的最接近零点的位置（2025-12-29 更新）
FOLLOWER_INIT_POS_DEGREES = {
    "shoulder_pan": 5.370,
    "shoulder_lift": -2.113,
    "elbow_flex": 3.941,
    "wrist_flex": 3.046,
    "wrist_roll": 18.644,
    "gripper": 24.400
}

def calculate_homing_offset(pwm_val, target_value, range_min, range_max, norm_mode, drive_mode=0):
    """
    计算 homing_offset 使得当前 PWM 读数产生目标值

    Args:
        pwm_val: 当前 PWM 值
        target_value: 目标读数（弧度或 RANGE_0_100）
        range_min, range_max: PWM 范围
        norm_mode: 归一化模式
        drive_mode: 驱动模式（0 或 1）

    Returns:
        (homing_offset, drive_mode)
    """
    if norm_mode == MotorNormMode.RADIANS:
        # 转换目标弧度为度
        target_degrees = np.rad2deg(target_value)

        # 检查是否需要负角度
        if target_degrees < 0:
            # 使用 drive_mode=1 来产生负角度
            target_degrees = abs(target_degrees)
            drive_mode = 1

        # 计算需要的 calibrated_pwm
        # degrees = ((calibrated_pwm - range_min) / (range_max - range_min)) * 270.0
        calibrated_pwm = (target_degrees / 270.0) * (range_max - range_min) + range_min

    elif norm_mode == MotorNormMode.RANGE_0_100:
        # gripper 使用 RANGE_0_100
        # norm = ((calibrated_pwm - range_min) / (range_max - range_min)) * 100.0
        calibrated_pwm = (target_value / 100.0) * (range_max - range_min) + range_min

    # 计算 homing_offset
    homing_offset = pwm_val - calibrated_pwm

    return int(round(homing_offset)), drive_mode

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    print("=" * 70)
    print("主臂标定计算工具 - 匹配从臂初始位置")
    print("=" * 70)
    print(f"端口: {port}")
    print()
    print("从臂安全初始位置（度）:")
    for name, val in FOLLOWER_INIT_POS_DEGREES.items():
        print(f"  {name:<18}: {val:7.3f}°")
    print("=" * 70)
    print()

    # 读取当前标定文件
    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 创建舵机总线
    motors = {
        "shoulder_pan": Motor(1, "zhonglin", MotorNormMode.RADIANS),
        "shoulder_lift": Motor(2, "zhonglin", MotorNormMode.RADIANS),
        "elbow_flex": Motor(3, "zhonglin", MotorNormMode.RADIANS),
        "wrist_flex": Motor(4, "zhonglin", MotorNormMode.RADIANS),
        "wrist_roll": Motor(5, "zhonglin", MotorNormMode.RADIANS),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        print("【计算新的标定参数】")
        print("-" * 70)
        print(f"{'关节':<15} {'PWM':<6} {'目标值':<12} {'新offset':<10} {'drive_mode':<10}")
        print("-" * 70)

        new_calib = {}

        for name, motor in bus.motors.items():
            response = bus.send_command(f'#{motor.id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())
            if match:
                pwm_val = int(match.group(1))
                range_min = calib_data[name]['range_min']
                range_max = calib_data[name]['range_max']

                # 获取目标值
                target_degrees = FOLLOWER_INIT_POS_DEGREES[name]

                if motor.norm_mode == MotorNormMode.RADIANS:
                    target_value = np.deg2rad(target_degrees)
                    target_str = f"{target_value:.4f}rad"
                else:  # RANGE_0_100
                    target_value = target_degrees
                    target_str = f"{target_value:.2f}"

                # 计算新的 homing_offset 和 drive_mode
                new_homing_offset, new_drive_mode = calculate_homing_offset(
                    pwm_val, target_value, range_min, range_max,
                    motor.norm_mode, calib_data[name]['drive_mode']
                )

                print(f"{name:<15} {pwm_val:<6} {target_str:<12} {new_homing_offset:<10} {new_drive_mode:<10}")

                # 保存新标定数据
                new_calib[name] = {
                    "id": calib_data[name]['id'],
                    "drive_mode": new_drive_mode,
                    "homing_offset": new_homing_offset,
                    "range_min": range_min,
                    "range_max": range_max
                }

        print("-" * 70)
        print()

        # 保存
        with open(calib_file, 'w') as f:
            json.dump(new_calib, f, indent=4)
        print(f"✓ 已保存到: {calib_file}")

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
