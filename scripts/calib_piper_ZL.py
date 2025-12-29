#!/usr/bin/env python3
"""Piper-ZL主从臂标定对比工具"""

import sys
import os
import json
import numpy as np
import re
import argparse
from piper_sdk import C_PiperInterface

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

from motors.zhonglin import ZhonglinMotorsBus
from motors import Motor, MotorNormMode


def calculate_calibrated_angle(pwm_val, calib_data, norm_mode):
    """根据标定数据计算校准后的角度"""
    homing_offset = calib_data['homing_offset']
    range_min = calib_data['range_min']
    range_max = calib_data['range_max']
    drive_mode = calib_data['drive_mode']

    calibrated_pwm = pwm_val - homing_offset

    if norm_mode == MotorNormMode.RADIANS:
        degrees = ((calibrated_pwm - range_min) / (range_max - range_min)) * 270.0
        if drive_mode == 1:
            degrees = -degrees
        return degrees
    elif norm_mode == MotorNormMode.RANGE_0_100:
        value = ((calibrated_pwm - range_min) / (range_max - range_min)) * 100.0
        return value

    return None


def calculate_homing_offset(pwm_val, target_millidegrees, range_min, range_max, norm_mode, drive_mode=0):
    """
    计算 homing_offset 使得当前 PWM 读数产生目标值

    Args:
        pwm_val: 当前 PWM 值
        target_millidegrees: 目标读数（毫度）
        range_min, range_max: PWM 范围
        norm_mode: 归一化模式
        drive_mode: 驱动模式（0 或 1）

    Returns:
        (homing_offset, drive_mode)
    """
    target_degrees = target_millidegrees / 1000.0

    if norm_mode == MotorNormMode.RADIANS:
        # 检查是否需要负角度
        if target_degrees < 0:
            # 使用 drive_mode=1 来产生负角度
            target_degrees = abs(target_degrees)
            drive_mode = 1
        else:
            drive_mode = 0

        # 计算需要的 calibrated_pwm
        # degrees = ((calibrated_pwm - range_min) / (range_max - range_min)) * 270.0
        calibrated_pwm = (target_degrees / 270.0) * (range_max - range_min) + range_min

    elif norm_mode == MotorNormMode.RANGE_0_100:
        # gripper 使用 RANGE_0_100
        # norm = ((calibrated_pwm - range_min) / (range_max - range_min)) * 100.0
        calibrated_pwm = (target_degrees / 100.0) * (range_max - range_min) + range_min

    # 计算 homing_offset
    homing_offset = pwm_val - calibrated_pwm

    return int(round(homing_offset)), drive_mode


def scan_leader_servos(port, id_range=(0, 6)):
    """扫描主臂舵机（复用scan_leader_servos.py逻辑）"""
    motors = {f"motor_{i}": Motor(i, "zhonglin", MotorNormMode.RADIANS)
              for i in range(id_range[0], id_range[1] + 1)}

    bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
    bus.connect()

    detected = []
    for motor_id in range(id_range[0], id_range[1] + 1):
        try:
            response = bus.send_command(f'#{motor_id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())
            if match:
                detected.append(motor_id)
        except:
            pass

    bus.disconnect()
    return detected


def read_leader_arm(port, calib_file):
    """读取主臂位置（返回PWM和度数）- 7个关节（ID 0-6 → joint_1-6 + gripper）"""
    with open(calib_file, 'r') as f:
        calib_data = json.load(f)

    # 新命名：ID 0→joint_1, ID 1→joint_2, ..., ID 5→joint_6, ID 6→gripper
    motors = {
        "joint_1": Motor(0, "zhonglin", MotorNormMode.RADIANS),
        "joint_2": Motor(1, "zhonglin", MotorNormMode.RADIANS),
        "joint_3": Motor(2, "zhonglin", MotorNormMode.RADIANS),
        "joint_4": Motor(3, "zhonglin", MotorNormMode.RADIANS),
        "joint_5": Motor(4, "zhonglin", MotorNormMode.RADIANS),
        "joint_6": Motor(5, "zhonglin", MotorNormMode.RADIANS),
        "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
    }

    # 映射新名称到旧标定文件键名
    calib_key_map = {
        "joint_1": "joint_1",  # ID 0 → 使用joint_1的标定（如果存在）
        "joint_2": "joint_1",  # ID 1 → 使用旧joint_1的标定
        "joint_3": "joint_2",  # ID 2 → 使用旧joint_2的标定
        "joint_4": "joint_3",  # ID 3 → 使用旧joint_3的标定
        "joint_5": "joint_4",  # ID 4 → 使用旧joint_4的标定
        "joint_6": "joint_5",  # ID 5 → 使用旧joint_5的标定
        "gripper": "gripper",  # ID 6 → 使用gripper的标定
    }

    bus = ZhonglinMotorsBus(port=port, motors=motors, baudrate=115200)
    bus.connect()

    results = []
    for name, motor in motors.items():
        try:
            response = bus.send_command(f'#{motor.id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())
            if match:
                pwm_val = int(match.group(1))
                calib_key = calib_key_map[name]
                if calib_key in calib_data:
                    degrees = calculate_calibrated_angle(pwm_val, calib_data[calib_key], motor.norm_mode)
                    millidegrees = int(round(degrees * 1000))
                else:
                    degrees = None
                    millidegrees = None
                results.append({
                    'name': name,
                    'pwm': pwm_val,
                    'degrees': degrees,
                    'millidegrees': millidegrees
                })
            else:
                results.append({
                    'name': name,
                    'pwm': None,
                    'degrees': None,
                    'millidegrees': None
                })
        except:
            results.append({
                'name': name,
                'pwm': None,
                'degrees': None,
                'millidegrees': None
            })

    bus.disconnect()
    return results


def read_follower_arm(can_bus):
    """读取从臂位置（返回毫度）- 6个关节 + 1个夹爪 = 7个"""
    import time

    piper = C_PiperInterface(can_bus)
    piper.ConnectPort()

    # 使能机械臂
    enable_flag = all(piper.GetArmEnableStatus())
    if not enable_flag:
        piper.EnablePiper()
        time.sleep(0.5)

    # 读取6个关节
    joint = piper.GetArmJointMsgs()
    # 读取夹爪（单独API）
    gripper = piper.GetArmGripperMsgs()

    positions = [
        joint.joint_state.joint_1.real,
        joint.joint_state.joint_2.real,
        joint.joint_state.joint_3.real,
        joint.joint_state.joint_4.real,
        joint.joint_state.joint_5.real,
        joint.joint_state.joint_6.real,
        gripper.gripper_state.grippers_angle,  # 夹爪角度（已经是毫度单位）
    ]

    return positions


def main():
    parser = argparse.ArgumentParser(description='Piper-ZL主从臂标定对比工具')
    parser.add_argument('--calibrate', action='store_true', help='自动进行标定（不询问）')
    args = parser.parse_args()

    leader_port = os.getenv("ARM_LEADER_PORT", "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0")
    follower_can = os.getenv("CAN_BUS", "can_left")
    calib_file = os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1', '.calibration', 'SO101-leader.json')

    # 参考位置（毫度）- 6个关节 + 夹爪
    reference_pos = [5370, -2113, 3941, 3046, 18644, 0, 24400]

    print("=" * 60)
    print("Piper-ZL 主从臂标定对比工具")
    print("=" * 60)
    print(f"主臂端口: {leader_port}")
    print(f"从臂CAN: {follower_can}")
    print("=" * 60)
    print()

    try:
        print("正在扫描主臂舵机...")
        detected_ids = scan_leader_servos(leader_port)
        print(f"✓ 检测到 {len(detected_ids)} 个舵机\n")

        print("正在读取主臂位置...")
        leader_data = read_leader_arm(leader_port, calib_file)
        print(f"✓ 主臂读取完成\n")

        print("正在读取从臂位置...")
        follower_pos = read_follower_arm(follower_can)
        print(f"✓ 从臂读取完成\n")

        print("【舵机检测】")
        print()
        print(f"主臂检测到: 6个关节 + 1个夹爪 (共{len(detected_ids)}个舵机)")
        print(f"从臂检测到: 6个关节 + 1个夹爪 (共{len(follower_pos)}个)")
        print()

        print("【主从臂对比】")
        print()

        max_diff = 0
        max_diff_joints_only = 0  # 仅关节的最大差异（不含夹爪）
        leader_dict = {item['name']: item for item in leader_data}

        for i in range(7):
            if i < 6:
                joint_name = f"joint_{i+1}"
            else:
                joint_name = "gripper"

            follower = follower_pos[i]
            leader = leader_dict.get(joint_name)

            print(f"[{i}] {joint_name}")

            if leader and leader['pwm'] is not None and leader['millidegrees'] is not None:
                leader_deg = leader['millidegrees'] / 1000.0
                follower_deg = follower / 1000.0
                diff_millideg = leader['millidegrees'] - follower
                diff_deg = diff_millideg / 1000.0
                max_diff = max(max_diff, abs(diff_millideg))

                # 仅统计关节的差异（不含夹爪）
                if i < 6:
                    max_diff_joints_only = max(max_diff_joints_only, abs(diff_millideg))

                print(f"    主臂: PWM={leader['pwm']} 度={leader_deg:.2f} 毫度={leader['millidegrees']}")
                print(f"    从臂: 度={follower_deg:.2f} 毫度={follower:.0f}")
                print(f"    差异: 度={diff_deg:.2f} 毫度={diff_millideg:.0f}")
            elif leader and leader['pwm'] is not None:
                print(f"    主臂: PWM={leader['pwm']} (无标定数据)")
                follower_deg = follower / 1000.0
                print(f"    从臂: 度={follower_deg:.2f} 毫度={follower:.0f}")
            else:
                status = "未检测到" if leader is None or leader['pwm'] is None else "读取失败"
                print(f"    主臂: {status}")
                follower_deg = follower / 1000.0
                print(f"    从臂: 度={follower_deg:.2f} 毫度={follower:.0f}")
            print()

        print()

        print(f"主从臂最大差异: {max_diff} 毫度 ({max_diff/1000:.3f} 度)")
        print(f"关节最大差异（不含夹爪）: {max_diff_joints_only} 毫度 ({max_diff_joints_only/1000:.3f} 度)")
        print()

        if max_diff_joints_only < 1000:
            print("✓ 主从臂关节位置对齐良好（差异 < 1度）")
        elif max_diff_joints_only < 5000:
            print("⚠️  主从臂关节位置有一定差异（1-5度），建议调整后再标定")
        else:
            print("❌ 主从臂关节位置差异较大（> 5度），请先调整主臂位置")
            print("   提示：手动移动主臂关节，使其与从臂当前位置对齐")

        print()

        # 询问是否进行标定
        if args.calibrate:
            response = 'y'
            print("自动标定模式")
        else:
            try:
                response = input("是否进行标定？(y/n): ").strip().lower()
            except EOFError:
                response = 'n'
                print("n")

        if response == 'y':
            print()
            print("【开始标定】")
            print()

            # 读取当前标定文件
            with open(calib_file, 'r') as f:
                old_calib_data = json.load(f)

            # 计算新的标定参数
            new_calib = {}

            # 映射新名称到旧标定文件键名（用于读取range_min/max）
            calib_key_map = {
                "joint_1": "joint_1",
                "joint_2": "joint_1",
                "joint_3": "joint_2",
                "joint_4": "joint_3",
                "joint_5": "joint_4",
                "joint_6": "joint_5",
                "gripper": "gripper",
            }

            for i in range(7):
                if i < 6:
                    joint_name = f"joint_{i+1}"
                else:
                    joint_name = "gripper"

                follower = follower_pos[i]
                leader = leader_dict.get(joint_name)

                if leader and leader['pwm'] is not None:
                    pwm_val = leader['pwm']
                    target_millidegrees = follower

                    # 获取range参数
                    old_key = calib_key_map[joint_name]
                    if old_key in old_calib_data:
                        range_min = old_calib_data[old_key]['range_min']
                        range_max = old_calib_data[old_key]['range_max']
                        old_drive_mode = old_calib_data[old_key].get('drive_mode', 0)
                    else:
                        # 使用默认值
                        range_min = 500
                        range_max = 2500
                        old_drive_mode = 0

                    # 使用实际的物理ID（0-6）
                    motor_id = i

                    # 计算新的homing_offset
                    new_homing_offset, new_drive_mode = calculate_homing_offset(
                        pwm_val, target_millidegrees, range_min, range_max,
                        MotorNormMode.RADIANS, old_drive_mode
                    )

                    new_calib[joint_name] = {
                        "id": motor_id,
                        "drive_mode": new_drive_mode,
                        "homing_offset": new_homing_offset,
                        "range_min": range_min,
                        "range_max": range_max
                    }

                    print(f"[{i}] {joint_name}: ID={motor_id} PWM={pwm_val} 目标={follower:.0f}毫度 新offset={new_homing_offset} drive_mode={new_drive_mode}")

            # 保存新标定文件
            with open(calib_file, 'w') as f:
                json.dump(new_calib, f, indent=4)

            print()
            print(f"✓ 标定完成！已保存到: {calib_file}")
            print()

        print()
        print("=" * 60)

    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
