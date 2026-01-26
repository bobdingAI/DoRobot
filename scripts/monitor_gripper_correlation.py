#!/usr/bin/env python3
"""
监控主臂和从臂夹爪状态的相关性脚本
用于诊断夹爪在运动范围过半时松开的问题
"""

import sys
import os
import time
import json
import csv
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode, MotorCalibration
import scservo_sdk as scs


def read_motor_value(bus, motor_id, address):
    """读取舵机寄存器值"""
    val, result, error = bus.packet_handler.read2ByteTxRx(
        bus.port_handler, motor_id, address
    )
    if result == scs.COMM_SUCCESS:
        return val
    return None


class GripperMonitor:
    def __init__(self, leader_port, follower_port, log_file=None):
        self.leader_port = leader_port
        self.follower_port = follower_port
        self.log_file = log_file

        # 读取标定文件
        base_path = Path(__file__).parent.parent
        leader_calib_file = base_path / 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json'
        follower_calib_file = base_path / 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-follower.json'

        with open(leader_calib_file, 'r') as f:
            leader_calib_data = json.load(f)

        with open(follower_calib_file, 'r') as f:
            follower_calib_data = json.load(f)

        self.leader_gripper_calib = leader_calib_data['gripper']
        self.follower_gripper_calib = follower_calib_data['gripper']

        # 连接主臂
        print("正在连接主臂...")
        leader_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
        leader_calib = {"gripper": MotorCalibration(**self.leader_gripper_calib)}
        self.leader_bus = FeetechMotorsBus(port=leader_port, motors=leader_motors, calibration=leader_calib)
        self.leader_bus.connect()
        print("✓ 主臂连接成功")

        # 连接从臂
        print("正在连接从臂...")
        follower_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
        follower_calib = {"gripper": MotorCalibration(**self.follower_gripper_calib)}
        self.follower_bus = FeetechMotorsBus(port=follower_port, motors=follower_motors, calibration=follower_calib)
        self.follower_bus.connect()
        print("✓ 从臂连接成功")

        # CSV日志文件
        self.csv_writer = None
        self.csv_file = None
        if log_file:
            self.csv_file = open(log_file, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                'timestamp',
                'leader_pwm', 'leader_norm', 'leader_range_pct',
                'follower_target_pwm', 'follower_actual_pwm', 'follower_norm', 'follower_range_pct',
                'pwm_diff', 'norm_diff',
                'leader_velocity', 'follower_velocity',
                'leader_load', 'follower_load',
                'event'
            ])

        # 用于检测异常事件
        self.prev_follower_norm = None
        self.prev_leader_norm = None
        self.anomaly_threshold = 10.0  # 归一化值突变阈值（百分比）

    def calculate_range_percentage(self, pwm, calib):
        """计算PWM值在标定范围内的百分比位置"""
        range_min = calib['range_min']
        range_max = calib['range_max']
        if range_max == range_min:
            return 0.0
        return ((pwm - range_min) / (range_max - range_min)) * 100.0

    def monitor_loop(self):
        """主监控循环"""
        print("\n" + "=" * 100)
        print("开始实时监控夹爪状态 (按 Ctrl+C 退出)")
        print("=" * 100)
        print()
        print("时间戳    | 主臂PWM | 主臂% | 主臂范围% | 从臂目标 | 从臂实际 | 从臂% | 从臂范围% | PWM差 | 归一化差 | 事件")
        print("-" * 100)

        try:
            while True:
                timestamp = time.time()

                # 读取主臂位置
                leader_pwm = read_motor_value(self.leader_bus, 6, 56)  # Present_Position
                if leader_pwm is None:
                    continue

                # 读取从臂位置
                follower_pwm = read_motor_value(self.follower_bus, 6, 56)  # Present_Position
                if follower_pwm is None:
                    continue

                # 读取速度和负载
                leader_velocity = read_motor_value(self.leader_bus, 6, 58)  # Present_Velocity
                follower_velocity = read_motor_value(self.follower_bus, 6, 58)
                leader_load = read_motor_value(self.leader_bus, 6, 60)  # Present_Load
                follower_load = read_motor_value(self.follower_bus, 6, 60)

                # 计算主臂归一化值 (0-100)
                leader_norm = self.leader_bus._normalize({6: leader_pwm})[6]

                # 计算从臂目标PWM值
                follower_target_pwm = self.follower_bus._unnormalize({6: leader_norm})[6]

                # 计算从臂归一化值
                follower_norm = self.follower_bus._normalize({6: follower_pwm})[6]

                # 计算范围百分比
                leader_range_pct = self.calculate_range_percentage(leader_pwm, self.leader_gripper_calib)
                follower_range_pct = self.calculate_range_percentage(follower_pwm, self.follower_gripper_calib)

                # 计算差异
                pwm_diff = abs(follower_pwm - follower_target_pwm)
                norm_diff = abs(follower_norm - leader_norm)

                # 检测异常事件
                event = ""

                # 检测范围过半
                if leader_range_pct > 50 and (self.prev_leader_norm is None or self.prev_leader_norm <= 50):
                    event += "[主臂过半] "
                if follower_range_pct > 50 and (self.prev_follower_norm is None or self.prev_follower_norm <= 50):
                    event += "[从臂过半] "

                # 检测突然松开（归一化值突然减小）
                if self.prev_follower_norm is not None:
                    follower_change = follower_norm - self.prev_follower_norm
                    if follower_change < -self.anomaly_threshold:
                        event += f"[从臂突然松开 {follower_change:.1f}%] "

                if self.prev_leader_norm is not None:
                    leader_change = leader_norm - self.prev_leader_norm
                    if leader_change < -self.anomaly_threshold:
                        event += f"[主臂突然松开 {leader_change:.1f}%] "

                # 检测大偏差
                if pwm_diff > 100:
                    event += f"[大偏差 {pwm_diff}] "

                # 检测溢出风险
                if follower_target_pwm > 4095:
                    event += f"[溢出风险 目标={follower_target_pwm}] "

                # 打印到控制台
                time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                print(f"{time_str} | {leader_pwm:4d}    | {leader_norm:5.1f} | {leader_range_pct:6.1f}%   | "
                      f"{follower_target_pwm:4d}     | {follower_pwm:4d}     | {follower_norm:5.1f} | "
                      f"{follower_range_pct:6.1f}%   | {pwm_diff:3d}   | {norm_diff:5.1f}%   | {event}")

                # 写入CSV
                if self.csv_writer:
                    self.csv_writer.writerow([
                        timestamp,
                        leader_pwm, leader_norm, leader_range_pct,
                        follower_target_pwm, follower_pwm, follower_norm, follower_range_pct,
                        pwm_diff, norm_diff,
                        leader_velocity or 0, follower_velocity or 0,
                        leader_load or 0, follower_load or 0,
                        event.strip()
                    ])
                    self.csv_file.flush()

                # 更新前一次的值
                self.prev_leader_norm = leader_norm
                self.prev_follower_norm = follower_norm

                time.sleep(0.05)  # 20Hz采样率

        except KeyboardInterrupt:
            print("\n\n监控结束")
        except Exception as e:
            print(f"\n错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.cleanup()

    def cleanup(self):
        """清理资源"""
        try:
            self.leader_bus.disconnect()
            self.follower_bus.disconnect()
            if self.csv_file:
                self.csv_file.close()
                print(f"\n日志已保存到: {self.log_file}")
        except:
            pass


def main():
    import argparse

    parser = argparse.ArgumentParser(description='监控主臂和从臂夹爪状态的相关性')
    parser.add_argument('--leader-port', default='/dev/ttyACM0', help='主臂串口 (默认: /dev/ttyACM0)')
    parser.add_argument('--follower-port', default='/dev/ttyUSB0', help='从臂串口 (默认: /dev/ttyUSB0)')
    parser.add_argument('--log', default=None, help='CSV日志文件路径 (可选)')

    args = parser.parse_args()

    # 如果没有指定日志文件，自动生成一个
    if args.log is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.log = f'gripper_monitor_{timestamp}.csv'

    print("=" * 100)
    print("夹爪状态监控工具")
    print("=" * 100)
    print(f"主臂串口: {args.leader_port}")
    print(f"从臂串口: {args.follower_port}")
    print(f"日志文件: {args.log}")
    print()

    monitor = GripperMonitor(args.leader_port, args.follower_port, args.log)
    monitor.monitor_loop()


if __name__ == "__main__":
    main()
