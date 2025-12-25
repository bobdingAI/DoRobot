#!/usr/bin/env python3
"""计算主臂正确的 homing_offset"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode
import re

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    print("=" * 70)
    print("主臂 Homing Offset 计算工具")
    print("=" * 70)
    print(f"端口: {port}")
    print()
    print("请确保主臂和从臂已经摆放到相同的物理位置（初始位置）")
    print("=" * 70)
    print()

    # 读取当前标定文件
    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 创建舵机总线（不使用标定）
    motors = {
        "shoulder_pan": Motor(1, "zhonglin", MotorNormMode.DEGREES),
        "shoulder_lift": Motor(2, "zhonglin", MotorNormMode.DEGREES),
        "elbow_flex": Motor(3, "zhonglin", MotorNormMode.DEGREES),
        "wrist_flex": Motor(4, "zhonglin", MotorNormMode.DEGREES),
        "wrist_roll": Motor(5, "zhonglin", MotorNormMode.DEGREES),
        "gripper": Motor(6, "zhonglin", MotorNormMode.DEGREES),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        print("【当前 PWM 读数】")
        print("-" * 70)
        print(f"{'关节':<18} {'PWM':<8} {'range_min':<12} {'新 homing_offset':<18}")
        print("-" * 70)

        new_calib = {}

        for name, motor in bus.motors.items():
            response = bus.send_command(f'#{motor.id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())
            if match:
                pwm_val = int(match.group(1))
                range_min = calib_data[name]['range_min']
                range_max = calib_data[name]['range_max']

                # 计算新的 homing_offset，使当前位置读取为 0°
                # 0° 对应 calibrated_pwm = range_min
                # calibrated_pwm = pwm - homing_offset = range_min
                # homing_offset = pwm - range_min
                new_homing_offset = pwm_val - range_min

                print(f"{name:<18} {pwm_val:<8} {range_min:<12} {new_homing_offset:<18}")

                # 保存新标定数据
                new_calib[name] = {
                    "id": calib_data[name]['id'],
                    "drive_mode": calib_data[name]['drive_mode'],
                    "homing_offset": new_homing_offset,
                    "range_min": range_min,
                    "range_max": range_max
                }

        print("-" * 70)
        print()

        # 询问是否保存
        save = input("是否保存新的标定数据到文件？(y/n): ").strip().lower()
        if save == 'y':
            with open(calib_file, 'w') as f:
                json.dump(new_calib, f, indent=4)
            print(f"\n✓ 已保存到: {calib_file}")
        else:
            print("\n未保存，你可以手动更新标定文件")
            print("\n新的标定数据：")
            print(json.dumps(new_calib, indent=4))

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
