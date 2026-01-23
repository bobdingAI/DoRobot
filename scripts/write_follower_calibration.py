#!/usr/bin/env python3
"""将标定文件写入从臂舵机硬件"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.feetech import FeetechMotorsBus
from motors import Motor, MotorNormMode, MotorCalibration


def main():
    # 读取从臂标定文件
    calib_file = 'operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-follower.json'

    print("=" * 80)
    print("将标定写入从臂舵机硬件")
    print("=" * 80)
    print()

    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    print("标定文件内容:")
    print(json.dumps(calib_data, indent=2, ensure_ascii=False))
    print()

    # 从臂串口
    port = input("请输入从臂串口 (默认 /dev/ttyUSB0，如果是 CAN 请输入对应设备): ").strip() or '/dev/ttyUSB0'

    print()
    print(f"正在连接从臂 ({port})...")

    # 创建电机配置
    motors = {}
    for joint_name, joint_data in calib_data.items():
        motor_id = joint_data['id']
        # 夹爪使用 RANGE_0_100，其他关节使用 RADIANS
        norm_mode = MotorNormMode.RANGE_0_100 if joint_name == 'gripper' else MotorNormMode.RADIANS
        motors[joint_name] = Motor(motor_id, "sts3215", norm_mode)

    # 创建标定对象
    calibration = {}
    for joint_name, joint_data in calib_data.items():
        calibration[joint_name] = MotorCalibration(
            id=joint_data['id'],
            drive_mode=joint_data['drive_mode'],
            homing_offset=joint_data['homing_offset'],
            range_min=joint_data['range_min'],
            range_max=joint_data['range_max']
        )

    # 连接总线
    bus = FeetechMotorsBus(port=port, motors=motors, calibration={})
    bus.connect()
    print("✓ 连接成功")
    print()

    # 读取当前硬件配置
    print("读取当前硬件配置...")
    print("-" * 80)
    print(f"{'关节':<12} {'ID':<4} {'硬件Offset':<12} {'文件Offset':<12} {'状态'}")
    print("-" * 80)

    import scservo_sdk as scs
    needs_update = []

    for joint_name, joint_data in calib_data.items():
        motor_id = joint_data['id']
        file_offset = joint_data['homing_offset']

        # 读取硬件 homing_offset (地址 31)
        hw_offset, result, error = bus.packet_handler.read2ByteTxRx(
            bus.port_handler, motor_id, 31
        )

        if result == scs.COMM_SUCCESS:
            # 处理有符号数
            if hw_offset > 32767:
                hw_offset = hw_offset - 65536

            status = "✓ 一致" if hw_offset == file_offset else "❌ 不一致"
            if hw_offset != file_offset:
                needs_update.append(joint_name)

            print(f"{joint_name:<12} {motor_id:<4} {hw_offset:<12} {file_offset:<12} {status}")
        else:
            print(f"{joint_name:<12} {motor_id:<4} {'读取失败':<12} {file_offset:<12} ❌")
            needs_update.append(joint_name)

    print("-" * 80)
    print()

    if not needs_update:
        print("✓ 所有舵机的硬件配置已是最新，无需更新")
        bus.disconnect()
        return

    print(f"需要更新的关节: {', '.join(needs_update)}")
    print()

    response = input("是否将标定文件写入舵机硬件? (y/n): ").strip().lower()
    if response != 'y':
        print("取消操作")
        bus.disconnect()
        return

    print()
    print("正在写入标定到舵机硬件...")
    print("-" * 80)

    # 禁用扭矩
    print("1. 禁用扭矩...")
    bus.disable_torque()

    # 写入标定
    print("2. 写入标定参数...")
    bus.write_calibration(calibration, cache=True)

    print("3. 启用扭矩...")
    bus.enable_torque()

    print("-" * 80)
    print()

    # 验证写入
    print("验证写入结果...")
    print("-" * 80)
    print(f"{'关节':<12} {'ID':<4} {'硬件Offset':<12} {'文件Offset':<12} {'状态'}")
    print("-" * 80)

    all_success = True
    for joint_name, joint_data in calib_data.items():
        motor_id = joint_data['id']
        file_offset = joint_data['homing_offset']

        hw_offset, result, error = bus.packet_handler.read2ByteTxRx(
            bus.port_handler, motor_id, 31
        )

        if result == scs.COMM_SUCCESS:
            if hw_offset > 32767:
                hw_offset = hw_offset - 65536

            status = "✓ 成功" if hw_offset == file_offset else "❌ 失败"
            if hw_offset != file_offset:
                all_success = False

            print(f"{joint_name:<12} {motor_id:<4} {hw_offset:<12} {file_offset:<12} {status}")
        else:
            print(f"{joint_name:<12} {motor_id:<4} {'读取失败':<12} {file_offset:<12} ❌")
            all_success = False

    print("-" * 80)
    print()

    if all_success:
        print("✓ 标定写入成功！")
        print()
        print("重要提示:")
        print("  1. 标定已写入舵机 EEPROM，断电后仍然保留")
        print("  2. 请重启遥操作程序以使新标定生效")
        print("  3. 如果问题仍然存在，请运行诊断脚本检查")
    else:
        print("❌ 部分标定写入失败，请检查连接和舵机状态")

    bus.disconnect()


if __name__ == "__main__":
    main()
