#!/usr/bin/env python3
"""
监控 SO101 主臂（串口）和 Piper 从臂（CAN）夹爪状态
用于诊断夹爪在运动范围过半时松开的问题
"""

import sys
import os
import time
import json
import csv
from datetime import datetime
from pathlib import Path

# SO101 leader arm (serial)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))
from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode, MotorCalibration
import scservo_sdk as scs

# Piper follower arm (CAN)
from piper_sdk import C_PiperInterface


def read_motor_value(bus, motor_id, address):
    """读取舵机寄存器值"""
    val, result, error = bus.packet_handler.read2ByteTxRx(
        bus.port_handler, motor_id, address
    )
    if result == scs.COMM_SUCCESS:
        return val
    return None


class SO101PiperGripperMonitor:
    def __init__(self, leader_port, can_bus, log_file=None):
        self.leader_port = leader_port
        self.can_bus = can_bus
        self.log_file = log_file

        # 读取 SO101 主臂标定文件
        base_path = Path(__file__).parent.parent
        leader_calib_file = base_path / 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json'

        with open(leader_calib_file, 'r') as f:
            leader_calib_data = json.load(f)

        self.leader_gripper_calib = leader_calib_data['gripper']

        # 连接 SO101 主臂
        print("正在连接 SO101 主臂...")
        leader_motors = {"gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100)}
        leader_calib = {"gripper": MotorCalibration(**self.leader_gripper_calib)}
        self.leader_bus = FeetechMotorsBus(port=leader_port, motors=leader_motors, calibration=leader_calib)
        self.leader_bus.connect()
        print("✓ SO101 主臂连接成功")

        # 连接 Piper 从臂
        print(f"正在连接 Piper 从臂 (CAN: {can_bus})...")
        self.piper = C_PiperInterface(can_bus)
        self.piper.ConnectPort()
        print("✓ Piper 从臂连接成功")

        # 获取 Piper 夹爪范围（通常是 0-1000，表示 0-100%）
        self.piper_gripper_min = 0
        self.piper_gripper_max = 1000

        # CSV日志文件
        self.csv_writer = None
        self.csv_file = None
        if log_file:
            self.csv_file = open(log_file, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            self.csv_writer.writerow([
                'timestamp',
                'leader_pwm', 'leader_norm', 'leader_range_pct',
                'piper_gripper_pos', 'piper_gripper_norm',
                'norm_diff',
                'event'
            ])

        # 用于检测异常事件
        self.prev_piper_norm = None
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
        print("\n" + "=" * 120)
        print("开始实时监控 SO101 主臂和 Piper 从臂夹爪状态 (按 Ctrl+C 退出)")
        print("=" * 120)
        print()
        print("时间戳    | 主臂PWM | 主臂% | 主臂范围% | Piper夹爪位置 | Piper% | 归一化差 | 事件")
        print("-" * 120)

        try:
            while True:
                timestamp = time.time()

                # 读取 SO101 主臂夹爪位置
                leader_pwm = read_motor_value(self.leader_bus, 6, 56)  # Present_Position
                if leader_pwm is None:
                    time.sleep(0.05)
                    continue

                # 计算主臂归一化值 (0-100)
                leader_norm = self.leader_bus._normalize({6: leader_pwm})[6]

                # 计算主臂范围百分比
                leader_range_pct = self.calculate_range_percentage(leader_pwm, self.leader_gripper_calib)

                # 读取 Piper 从臂夹爪位置
                try:
                    gripper_state = self.piper.GetArmGripperMsgs()
                    piper_gripper_pos = gripper_state.gripper_state.grippers_angle  # 原始值

                    # 计算 Piper 归一化值 (0-100)
                    # Piper 夹爪: 原始值需要除以 1000000 得到 0-1 范围，再乘以 100 得到百分比
                    piper_gripper_norm = (piper_gripper_pos / 10000.0)  # 除以 10000 = 除以 1000000 再乘以 100

                except Exception as e:
                    print(f"\n读取 Piper 夹爪失败: {e}")
                    time.sleep(0.05)
                    continue

                # 计算差异
                norm_diff = abs(piper_gripper_norm - leader_norm)

                # 检测异常事件
                event = ""

                # 检测范围过半
                if leader_range_pct > 50 and (self.prev_leader_norm is None or self.prev_leader_norm <= 50):
                    event += "[主臂过半] "
                if piper_gripper_norm > 50 and (self.prev_piper_norm is None or self.prev_piper_norm <= 50):
                    event += "[从臂过半] "

                # 检测突然松开（归一化值突然减小）
                if self.prev_piper_norm is not None:
                    piper_change = piper_gripper_norm - self.prev_piper_norm
                    if piper_change < -self.anomaly_threshold:
                        event += f"[从臂突然松开 {piper_change:.1f}%] "

                if self.prev_leader_norm is not None:
                    leader_change = leader_norm - self.prev_leader_norm
                    if leader_change < -self.anomaly_threshold:
                        event += f"[主臂突然松开 {leader_change:.1f}%] "

                # 检测大偏差
                if norm_diff > 15:
                    event += f"[大偏差 {norm_diff:.1f}%] "

                # 打印到控制台
                time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                print(f"{time_str} | {leader_pwm:4d}    | {leader_norm:5.1f} | {leader_range_pct:6.1f}%   | "
                      f"{piper_gripper_pos:4d}          | {piper_gripper_norm:6.1f} | {norm_diff:6.1f}%   | {event}")

                # 写入CSV
                if self.csv_writer:
                    self.csv_writer.writerow([
                        timestamp,
                        leader_pwm, leader_norm, leader_range_pct,
                        piper_gripper_pos, piper_gripper_norm,
                        norm_diff,
                        event.strip()
                    ])
                    self.csv_file.flush()

                # 更新前一次的值
                self.prev_leader_norm = leader_norm
                self.prev_piper_norm = piper_gripper_norm

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
            # Piper SDK 可能没有显式的 disconnect 方法
            if self.csv_file:
                self.csv_file.close()
                print(f"\n日志已保存到: {self.log_file}")
        except Exception as e:
            print(f"清理时出错: {e}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='监控 SO101 主臂和 Piper 从臂夹爪状态')
    parser.add_argument('--leader-port', default='/dev/ttyACM0', help='SO101 主臂串口 (默认: /dev/ttyACM0)')
    parser.add_argument('--can-bus', default='can_left', help='Piper 从臂 CAN 总线 (默认: can_left)')
    parser.add_argument('--log', default=None, help='CSV日志文件路径 (可选)')

    args = parser.parse_args()

    # 如果没有指定日志文件，自动生成一个
    if args.log is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.log = f'so101_piper_gripper_{timestamp}.csv'

    print("=" * 120)
    print("SO101-Piper 夹爪状态监控工具")
    print("=" * 120)
    print(f"SO101 主臂串口: {args.leader_port}")
    print(f"Piper 从臂 CAN: {args.can_bus}")
    print(f"日志文件: {args.log}")
    print()

    monitor = SO101PiperGripperMonitor(args.leader_port, args.can_bus, args.log)
    monitor.monitor_loop()


if __name__ == "__main__":
    main()
