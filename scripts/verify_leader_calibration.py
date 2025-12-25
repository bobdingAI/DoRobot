#!/usr/bin/env python3
"""验证主臂标定准确性的测试脚本"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")

    print("=" * 70)
    print("主臂标定验证工具")
    print("=" * 70)
    print(f"端口: {port}")
    print()
    print("请按照提示手动移动主臂到指定位置，验证读数是否合理")
    print("=" * 70)
    print()

    # 创建舵机总线（不使用标定）
    motors_no_calib = {
        "shoulder_pan": Motor(1, "zhonglin", MotorNormMode.DEGREES),
        "shoulder_lift": Motor(2, "zhonglin", MotorNormMode.DEGREES),
        "elbow_flex": Motor(3, "zhonglin", MotorNormMode.DEGREES),
        "wrist_flex": Motor(4, "zhonglin", MotorNormMode.DEGREES),
        "wrist_roll": Motor(5, "zhonglin", MotorNormMode.DEGREES),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RANGE_0_100),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors_no_calib, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        # 测试1：读取当前位置（无标定）
        print("【测试1】当前位置（无标定，原始PWM转角度）")
        print("-" * 70)
        positions = bus.sync_read("Present_Position")
        for name, angle in positions.items():
            print(f"  {name:15s}: {angle:7.2f}°")
        print()

        # 测试2：读取PWM原始值
        print("【测试2】PWM原始值")
        print("-" * 70)
        for name, motor in bus.motors.items():
            response = bus.send_command(f'#{motor.id:03d}PRAD!')
            angle, pwm_val = bus.pwm_to_angle(response.strip())
            if pwm_val:
                print(f"  {name:15s}: PWM={pwm_val:4d}  →  {angle:7.2f}° (原始)")
        print()

        # 测试3：交互式验证
        print("【测试3】交互式验证")
        print("-" * 70)
        print("请手动移动主臂到以下位置，观察读数是否合理：")
        print()

        test_positions = [
            ("水平伸直", "所有关节应该接近0°或180°"),
            ("垂直向上", "shoulder_lift应该接近90°"),
            ("完全收缩", "elbow_flex应该接近最小值"),
            ("完全伸展", "elbow_flex应该接近最大值"),
        ]

        for i, (pos_name, expected) in enumerate(test_positions, 1):
            input(f"\n按Enter键继续测试 {i}/{len(test_positions)}: {pos_name}...")
            print(f"\n位置: {pos_name}")
            print(f"预期: {expected}")
            print("当前读数:")

            positions = bus.sync_read("Present_Position")
            for name, angle in positions.items():
                print(f"  {name:15s}: {angle:7.2f}°")

            is_correct = input("\n读数是否符合预期？(y/n): ").strip().lower()
            if is_correct != 'y':
                print("⚠️  标定可能不准确！")

        print("\n" + "=" * 70)
        print("测试完成")
        print("=" * 70)
        print("\n如果多个位置的读数都不符合预期，建议重新标定主臂")
        print("重新标定命令: dora run dora_calibrate_leader.yml")

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
