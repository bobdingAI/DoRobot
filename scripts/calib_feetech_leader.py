#!/usr/bin/env python3
"""飞特协议主臂标定工具 - 实时显示并自动记录运动范围"""

import sys
import os
import json
import argparse
import time
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode


# 全局变量用于优雅退出
running = True


def signal_handler(sig, frame):
    """处理 Ctrl+C 信号"""
    global running
    running = False


def calculate_homing_offset(pwm_val, range_min, range_max, norm_mode):
    """计算 homing_offset 使当前位置映射到范围中点"""
    if norm_mode == MotorNormMode.RADIANS:
        target_degrees = 135.0
        calibrated_pwm = (target_degrees / 270.0) * (range_max - range_min) + range_min
    elif norm_mode == MotorNormMode.RANGE_0_100:
        target_value = 50.0
        calibrated_pwm = (target_value / 100.0) * (range_max - range_min) + range_min
    else:
        raise ValueError(f"Unsupported norm_mode: {norm_mode}")

    homing_offset = pwm_val - calibrated_pwm
    return int(round(homing_offset))


def read_all_positions(bus):
    """读取所有舵机的当前位置"""
    import scservo_sdk as scs
    positions = {}
    for motor_id in range(7):
        pwm_val, result, error = bus.packet_handler.read2ByteTxRx(
            bus.port_handler, motor_id, 56
        )
        if result == scs.COMM_SUCCESS:
            positions[motor_id] = pwm_val
    return positions


def clear_screen():
    """清屏"""
    print("\033[2J\033[H", end='')


def display_positions(positions, ranges):
    """显示所有舵机的当前位置和记录的范围"""
    clear_screen()

    print("="*70)
    print("飞特主臂标定 - 实时位置监控")
    print("="*70)
    print()
    print("请手动移动各个关节到极限位置，系统会自动记录最大和最小值")
    print("按 Ctrl+C 完成测量并继续标定")
    print()
    print("-"*70)

    joint_names = ["joint_0", "joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "gripper"]

    for motor_id in range(7):
        joint_name = joint_names[motor_id]
        current = positions.get(motor_id, 0)
        min_val, max_val = ranges.get(motor_id, (None, None))

        # 显示当前位置
        print(f"[{motor_id}] {joint_name:10s}  当前: {current:4d} PWM", end='')

        # 显示记录的范围
        if min_val is not None and max_val is not None:
            range_size = max_val - min_val
            print(f"  |  范围: {min_val:4d} - {max_val:4d} ({range_size:4d} 单位)", end='')

            # 显示进度条
            if range_size > 0:
                progress = (current - min_val) / range_size
                bar_width = 20
                filled = int(progress * bar_width)
                bar = '█' * filled + '░' * (bar_width - filled)
                print(f"  [{bar}]", end='')
        else:
            print(f"  |  范围: 未记录", end='')

        print()

    print("-"*70)
    print()


def monitor_and_record_ranges(bus):
    """实时监控并记录运动范围"""
    global running

    # 初始化范围记录
    ranges = {i: (None, None) for i in range(7)}

    print("开始监控舵机位置...")
    print("请移动各个关节到极限位置...")
    time.sleep(1)

    try:
        while running:
            # 读取当前位置
            positions = read_all_positions(bus)

            # 更新范围记录
            for motor_id, current_pos in positions.items():
                min_val, max_val = ranges[motor_id]

                if min_val is None or current_pos < min_val:
                    min_val = current_pos

                if max_val is None or current_pos > max_val:
                    max_val = current_pos

                ranges[motor_id] = (min_val, max_val)

            # 显示当前状态
            display_positions(positions, ranges)

            # 短暂延迟
            time.sleep(0.1)

    except KeyboardInterrupt:
        pass

    print("\n测量完成！")
    return ranges


def main():
    global running

    parser = argparse.ArgumentParser(description='飞特协议主臂标定工具 - 实时监控')
    parser.add_argument('--port', default='/dev/ttyACM0', help='串口设备路径')
    parser.add_argument('--model', default='sts3215', help='舵机型号')
    parser.add_argument('--output', default='operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json',
                        help='输出标定文件路径')
    args = parser.parse_args()

    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)

    calib_file = args.output

    print("="*70)
    print("飞特协议主臂标定工具 - 实时监控模式")
    print("="*70)
    print(f"主臂端口: {args.port}")
    print(f"舵机型号: {args.model}")
    print("="*70)
    print()

    try:
        # 连接主臂
        print("正在连接主臂...")
        motors = {f"motor_{i}": Motor(i, args.model, MotorNormMode.RADIANS)
                  for i in range(7)}
        bus = FeetechMotorsBus(port=args.port, motors=motors, calibration={})
        bus.connect()
        print("✓ 连接成功\n")

        # 步骤 1: 实时监控并记录运动范围
        print("【步骤 1: 测量运动范围】")
        print()
        ranges = monitor_and_record_ranges(bus)

        # 检查是否所有关节都有有效范围
        joint_names = ["joint_0", "joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "gripper"]
        print("\n记录的运动范围:")
        print("-"*70)
        for motor_id in range(7):
            joint_name = joint_names[motor_id]
            min_val, max_val = ranges[motor_id]
            if min_val is not None and max_val is not None:
                range_size = max_val - min_val
                print(f"[{motor_id}] {joint_name:10s}: {min_val:4d} - {max_val:4d} ({range_size:4d} 单位)")
            else:
                print(f"[{motor_id}] {joint_name:10s}: 未记录")

        print()

        # 步骤 2: 设置初始位置
        print("\n【步骤 2: 设置初始位置】")
        print("请将主臂移动到舒适的初始位置（将被映射为 135°）")
        input("准备好后按 Enter...")

        print("\n正在读取当前位置...")
        current_positions = read_all_positions(bus)

        bus.disconnect()

        # 生成标定数据
        print(f"\n{'='*70}")
        print("【标定结果】")
        print(f"{'='*70}")
        print()
        print("标定策略说明:")
        print("  - 将主臂当前位置映射到物理范围的中点（135°）")
        print("  - 确保两个方向都有对称的运动空间")
        print()

        calibration = {}
        for motor_id in range(7):
            joint_name = joint_names[motor_id]
            min_val, max_val = ranges[motor_id]
            current_pos = current_positions[motor_id]

            norm_mode = MotorNormMode.RANGE_0_100 if joint_name == "gripper" else MotorNormMode.RADIANS
            homing_offset = calculate_homing_offset(current_pos, min_val, max_val, norm_mode)

            calibration[joint_name] = {
                "id": motor_id,
                "drive_mode": 0,
                "homing_offset": homing_offset,
                "range_min": min_val,
                "range_max": max_val
            }

            range_size = max_val - min_val
            middle_angle = 135.0 if norm_mode == MotorNormMode.RADIANS else 50.0

            print(f"[{motor_id}] {joint_name}: PWM={current_pos} 范围={min_val}-{max_val}({range_size}单位)")
            print(f"    映射: 当前位置 → {middle_angle:.0f}° | offset={homing_offset}")

        # 保存标定文件
        os.makedirs(os.path.dirname(calib_file), exist_ok=True)
        with open(calib_file, 'w') as f:
            json.dump(calibration, f, indent=4)

        print()
        print(f"{'='*70}")
        print(f"✓ 标定完成！")
        print(f"标定文件已保存到: {calib_file}")
        print(f"{'='*70}")
        print()

        return 0

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
