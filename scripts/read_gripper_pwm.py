#!/usr/bin/env python3
"""读取夹爪当前的原始PWM值"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode

def main():
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")

    motors = {
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    try:
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
        bus.connect()

        motor = bus.motors["gripper"]
        response = bus.send_command(f'#{motor.id:03d}PRAD!')
        match = re.search(r'P(\d{4})', response.strip())

        if match:
            pwm_val = int(match.group(1))
            print(f"\n夹爪当前 PWM 值: {pwm_val}\n")
        else:
            print(f"\n无法解析响应: {response}\n")

        bus.disconnect()

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
