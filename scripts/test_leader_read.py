#!/usr/bin/env python3
"""测试主臂读取所有 6 个关节"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode, MotorCalibration
import json

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    # 读取标定文件
    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 转换为 MotorCalibration 对象
    calibration = {}
    for name, data in calib_data.items():
        calibration[name] = MotorCalibration(
            id=data['id'],
            homing_offset=data['homing_offset'],
            drive_mode=data['drive_mode'],
            range_min=data['range_min'],
            range_max=data['range_max']
        )

    # 创建舵机总线（使用标定）
    motors = {
        "shoulder_pan": Motor(1, "zhonglin", MotorNormMode.RADIANS),
        "shoulder_lift": Motor(2, "zhonglin", MotorNormMode.RADIANS),
        "elbow_flex": Motor(3, "zhonglin", MotorNormMode.RADIANS),
        "wrist_flex": Motor(4, "zhonglin", MotorNormMode.RADIANS),
        "wrist_roll": Motor(5, "zhonglin", MotorNormMode.RADIANS),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, calibration=calibration, baudrate=115200)
        bus.connect()
        print("✓ 已连接到主臂\n")

        print("读取所有关节（带标定）：")
        print("-" * 70)
        for i in range(5):
            present_pos = bus.sync_read("Present_Position")
            joint_value = [val for _motor, val in present_pos.items()]
            print(f"读取 {i+1}: {joint_value}")
            print(f"  长度: {len(joint_value)}")
            print()

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
