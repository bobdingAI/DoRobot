#!/usr/bin/env python3
"""扫描主臂（SO101 Leader Arm）上所有有响应的舵机"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode


def scan_servos(port, id_range=(0, 15)):
    """扫描指定范围内的舵机ID

    Args:
        port: 串口路径
        id_range: 扫描的ID范围 (start, end)，包含start和end

    Returns:
        list: 检测到的舵机ID列表
    """
    # 创建一个临时电机字典用于扫描
    motors = {f"motor_{i}": Motor(i, "zhonglin", MotorNormMode.RADIANS)
              for i in range(id_range[0], id_range[1] + 1)}

    bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
    bus.connect()

    detected = []

    print(f"正在扫描舵机 ID {id_range[0]} 到 {id_range[1]}...")
    print("-" * 60)

    for motor_id in range(id_range[0], id_range[1] + 1):
        try:
            # 发送读取位置命令
            response = bus.send_command(f'#{motor_id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())

            if match:
                pwm_val = int(match.group(1))
                detected.append(motor_id)
                print(f"✓ ID {motor_id:2d}: 检测到 (PWM: {pwm_val})")
            else:
                print(f"✗ ID {motor_id:2d}: 无响应")
        except Exception as e:
            print(f"✗ ID {motor_id:2d}: 错误 ({str(e)[:30]})")

    bus.disconnect()
    return detected


def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")

    print("=" * 60)
    print("主臂舵机扫描工具")
    print("=" * 60)
    print(f"端口: {port}")
    print("=" * 60)
    print()

    try:
        # 扫描ID 0-15
        detected = scan_servos(port, id_range=(0, 15))

        print()
        print("=" * 60)
        print("扫描结果")
        print("=" * 60)
        print(f"检测到舵机数量: {len(detected)}")
        print(f"舵机ID列表: {detected}")
        print()

        if detected:
            print("详细信息:")
            for motor_id in detected:
                print(f"  - ID {motor_id}")
        else:
            print("未检测到任何舵机")

        print("=" * 60)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
