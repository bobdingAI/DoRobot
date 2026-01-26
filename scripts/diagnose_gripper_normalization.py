#!/usr/bin/env python3
"""
诊断主臂夹爪归一化值问题
检查 homing_offset 是否导致负值
"""

import json
from pathlib import Path

# 读取主臂标定文件
calib_file = Path("operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json")
with open(calib_file) as f:
    calib = json.load(f)

gripper = calib['gripper']
print("=" * 70)
print("主臂夹爪标定参数")
print("=" * 70)
print(f"homing_offset: {gripper['homing_offset']}")
print(f"range_min:     {gripper['range_min']}")
print(f"range_max:     {gripper['range_max']}")
print(f"运动范围:      {gripper['range_max'] - gripper['range_min']} 步")
print()

# 模拟归一化计算
def normalize_pwm(pwm, calib):
    """模拟 Feetech 电机的归一化计算"""
    homing_offset = calib['homing_offset']
    range_min = calib['range_min']
    range_max = calib['range_max']

    # 实际 PWM 值（考虑 homing_offset）
    actual_pwm = pwm + homing_offset

    # 归一化到 0-100 范围
    if range_max == range_min:
        return 0.0
    normalized = ((actual_pwm - range_min) / (range_max - range_min)) * 100.0

    return normalized, actual_pwm

print("=" * 70)
print("PWM 值归一化测试")
print("=" * 70)
print(f"{'PWM':<8} {'实际PWM':<10} {'归一化%':<12} {'Piper值':<12} {'状态'}")
print("-" * 70)

# 测试不同的 PWM 值
test_pwms = [
    gripper['range_min'],
    gripper['range_min'] + 100,
    gripper['range_min'] + 200,
    (gripper['range_min'] + gripper['range_max']) // 2,  # 中点
    gripper['range_max'] - 100,
    gripper['range_max'],
]

for pwm in test_pwms:
    norm, actual = normalize_pwm(pwm, gripper)
    piper_value = int(abs(norm / 100.0 * 1000 * 1000))

    # 判断状态
    if norm < 0:
        status = "❌ 负值！"
    elif norm > 100:
        status = "⚠️  超过100%"
    elif 45 <= norm <= 55:
        status = "🔵 中点附近"
    else:
        status = "✓"

    print(f"{pwm:<8} {actual:<10} {norm:<12.2f} {piper_value:<12} {status}")

print()
print("=" * 70)
print("问题分析")
print("=" * 70)

# 检查是否会产生负值
min_norm, min_actual = normalize_pwm(gripper['range_min'], gripper)
if min_norm < 0:
    print("⚠️  警告：range_min 位置产生负值归一化！")
    print(f"   PWM {gripper['range_min']} + offset {gripper['homing_offset']} = {min_actual}")
    print(f"   归一化值: {min_norm:.2f}%")
    print()
    print("   这会导致 abs() 函数将负值变成正值，")
    print("   使得夹爪在应该松开时反而闭合！")
else:
    print("✓ range_min 位置归一化值正常")

print()
print("=" * 70)
print("建议")
print("=" * 70)
print("1. 检查 homing_offset = -192 是否正确")
print("2. 移除 Piper 夹爪控制中的 abs() 函数")
print("3. 确保归一化值在 0-100% 范围内")
print("4. 如果归一化值为负，应该钳制到 0 而不是取绝对值")
