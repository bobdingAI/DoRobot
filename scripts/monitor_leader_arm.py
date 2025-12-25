#!/usr/bin/env python3
"""实时监控主臂舵机信息"""

import sys
import os
import time
import signal
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode

# 全局标志
should_exit = False

def signal_handler(signum, frame):
    """处理Ctrl+C信号"""
    global should_exit
    should_exit = True

def main():
    global should_exit

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)

    # Use persistent path to avoid device number changes
    port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    baudrate = 115200
    duration = 20  # 运行20秒
    start_time = None  # Initialize to avoid UnboundLocalError

    print("="*60)
    print("主臂舵机实时监控")
    print("="*60)
    print(f"端口: {port}")
    print(f"波特率: {baudrate}")
    print(f"运行时长: {duration}秒")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    print()

    # 创建舵机总线
    motors = {
        "shoulder_pan": Motor(1, "zhonglin", MotorNormMode.DEGREES),
        "shoulder_lift": Motor(2, "zhonglin", MotorNormMode.DEGREES),
        "elbow_flex": Motor(3, "zhonglin", MotorNormMode.DEGREES),
        "wrist_flex": Motor(4, "zhonglin", MotorNormMode.DEGREES),
        "wrist_roll": Motor(5, "zhonglin", MotorNormMode.DEGREES),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RANGE_0_100),
    }

    try:
        # 连接舵机
        bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=baudrate)
        bus.connect()
        print(f"✓ 已连接到主臂\n")

        start_time = time.time()

        # 主循环
        while not should_exit:
            current_time = time.time()
            elapsed = current_time - start_time

            # 检查是否超时
            if elapsed >= duration:
                break

            # 读取舵机位置
            positions = bus.sync_read("Present_Position")

            # 获取时间戳
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

            # 打印信息
            print(f"[{timestamp}] 运行时间: {elapsed:.2f}s")
            for name, angle in positions.items():
                print(f"  {name:15s}: {angle:7.2f}°")
            print()

            # 控制刷新频率（10Hz）
            time.sleep(0.1)

        # 断开连接
        bus.disconnect()

    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 输出终止信息
        end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print()
        print("="*60)
        print("程序终止")
        print(f"结束时间: {end_time}")
        if start_time is not None:
            print(f"总运行时长: {time.time() - start_time:.2f}秒")
        print("="*60)

if __name__ == "__main__":
    main()
