#!/usr/bin/env python3
"""实时监控主臂和从臂夹爪的 PWM 值和映射关系"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode
import scservo_sdk as scs


def read_gripper_pwm(bus, motor_id=6):
    """读取夹爪的原始 PWM 值"""
    pwm_val, result, error = bus.packet_handler.read2ByteTxRx(
        bus.port_handler, motor_id, 56  # Present_Position 地址
    )
    if result == scs.COMM_SUCCESS:
        return pwm_val
    return None


def calculate_normalized_value(pwm, range_min, range_max):
    """计算归一化值 (0-100%)"""
    bounded_val = min(range_max, max(range_min, pwm))
    norm = ((bounded_val - range_min) / (range_max - range_min)) * 100
    return norm


def calculate_follower_pwm(norm_value, range_min, range_max):
    """根据归一化值计算从臂 PWM"""
    bounded_val = min(100.0, max(0.0, norm_value))
    follower_pwm = int((bounded_val / 100) * (range_max - range_min) + range_min)
    return follower_pwm


def main():
    # 主臂配置
    leader_port = '/dev/ttyACM0'
    leader_min, leader_max = 2125, 2522

    # 从臂配置
    follower_port = '/dev/ttyUSB0'
    follower_min, follower_max = 2046, 3510

    print("=" * 80)
    print("主臂和从臂夹爪实时监控")
    print("=" * 80)
    print(f"主臂范围: {leader_min}-{leader_max} ({leader_max-leader_min} 步)")
    print(f"从臂范围: {follower_min}-{follower_max} ({follower_max-follower_min} 步)")
    print("=" * 80)
    print()

    try:
        # 连接主臂
        print("正在连接主臂...")
        leader_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
        leader_bus = FeetechMotorsBus(port=leader_port, motors=leader_motors, calibration={})
        leader_bus.connect()
        print("✓ 主臂连接成功")

        # 连接从臂
        print("正在连接从臂...")
        follower_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
        follower_bus = FeetechMotorsBus(port=follower_port, motors=follower_motors, calibration={})
        follower_bus.connect()
        print("✓ 从臂连接成功")
        print()

        print("开始监控... (按 Ctrl+C 退出)")
        print()
        print("主臂PWM | 归一化(%) | 理论从臂PWM | 实际从臂PWM | 差值")
        print("-" * 80)

        while True:
            # 读取主臂夹爪位置
            leader_pwm = read_gripper_pwm(leader_bus, motor_id=6)
            if leader_pwm is None:
                print("读取主臂失败")
                time.sleep(0.1)
                continue

            # 读取从臂夹爪位置
            follower_pwm = read_gripper_pwm(follower_bus, motor_id=6)
            if follower_pwm is None:
                print("读取从臂失败")
                time.sleep(0.1)
                continue

            # 计算归一化值
            norm_value = calculate_normalized_value(leader_pwm, leader_min, leader_max)

            # 计算理论从臂位置
            expected_follower = calculate_follower_pwm(norm_value, follower_min, follower_max)

            # 计算差值
            diff = follower_pwm - expected_follower

            # 显示
            print(f"\r{leader_pwm:4d}    | {norm_value:6.2f}%   | {expected_follower:4d}         | {follower_pwm:4d}          | {diff:+4d}   ", end='', flush=True)

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
