#!/usr/bin/env python3
"""重新计算 gripper 的 homing_offset (RADIANS 模式)"""

import sys
import os
import json
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode
import re

# 从臂的安全初始位置（度）
FOLLOWER_GRIPPER_POS_DEGREES = 40.109

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    print("=" * 70)
    print("重新计算 gripper 标定参数 (RADIANS 模式)")
    print("=" * 70)
    print(f"从臂 gripper 位置: {FOLLOWER_GRIPPER_POS_DEGREES}°")
    print("=" * 70)
    print()

    # 读取当前标定文件
    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 创建舵机总线
    motors = {
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        # 读取 gripper PWM
        motor = bus.motors["gripper"]
        response = bus.send_command(f'#{motor.id:03d}PRAD!')
        match = re.search(r'P(\d{4})', response.strip())
        if match:
            pwm_val = int(match.group(1))
            range_min = calib_data["gripper"]['range_min']
            range_max = calib_data["gripper"]['range_max']

            # 目标值：从臂的 gripper 位置（度 → 弧度）
            target_radians = np.deg2rad(FOLLOWER_GRIPPER_POS_DEGREES)

            # 计算 homing_offset
            # radians = np.deg2rad(((pwm - homing_offset - range_min) / (range_max - range_min)) * 270.0)
            # 反推：
            target_degrees = FOLLOWER_GRIPPER_POS_DEGREES
            calibrated_pwm = (target_degrees / 270.0) * (range_max - range_min) + range_min
            new_homing_offset = pwm_val - calibrated_pwm

            print(f"当前 PWM: {pwm_val}")
            print(f"目标值: {target_radians:.4f} rad ({FOLLOWER_GRIPPER_POS_DEGREES}°)")
            print(f"新 homing_offset: {int(round(new_homing_offset))}")
            print()

            # 更新标定文件
            calib_data["gripper"]["homing_offset"] = int(round(new_homing_offset))

            with open(calib_file, 'w') as f:
                json.dump(calib_data, f, indent=4)
            print(f"✓ 已保存到: {calib_file}")

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
