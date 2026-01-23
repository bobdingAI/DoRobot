#!/usr/bin/env python3
"""测试主臂夹爪到从臂夹爪的映射"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'operating_platform', 'robot', 'components', 'arm_normal_so101_v1'))

# 模拟映射计算
leader_min, leader_max = 2125, 2522
follower_min, follower_max = 2046, 3510
follower_offset = 485

print("=" * 80)
print("主臂夹爪 → 从臂夹爪映射测试")
print("=" * 80)
print()
print(f"主臂范围: {leader_min} - {leader_max} ({leader_max - leader_min} 步)")
print(f"从臂范围: {follower_min} - {follower_max} ({follower_max - follower_min} 步)")
print(f"从臂 homing_offset: {follower_offset}")
print()
print("=" * 80)
print("映射计算")
print("=" * 80)
print()
print("主臂PWM | 归一化(%) | 从臂Goal_Position | 从臂实际物理位置 | 状态")
print("-" * 80)

test_positions = [
    2125,  # 最小值
    2200,
    2300,
    2400,
    2500,
    2522,  # 最大值
]

for leader_pwm in test_positions:
    # 步骤1: 主臂归一化
    norm = ((leader_pwm - leader_min) / (leader_max - leader_min)) * 100

    # 步骤2: 从臂反归一化
    follower_goal = int((norm / 100) * (follower_max - follower_min) + follower_min)

    # 步骤3: 从臂实际物理位置 (舵机硬件会加上 homing_offset)
    follower_actual = follower_goal + follower_offset

    # 检查是否溢出
    if follower_actual > 4095:
        status = f"❌ 溢出! ({follower_actual} > 4095)"
    else:
        status = "✓"

    print(f"{leader_pwm:4d}    | {norm:6.2f}%   | {follower_goal:4d}            | {follower_actual:4d}               | {status}")

print("-" * 80)
print()

# 检查您描述的问题
print("=" * 80)
print("问题诊断")
print("=" * 80)
print()
print("您描述的现象:")
print("  1. 主臂最小值 (2125) → 从臂张开 ✓")
print("  2. 主臂闭合到某点 → 从臂完全闭合 ✓")
print("  3. 主臂继续移动 → 从臂突然张开 ❌")
print()

# 找出从臂完全闭合的点
print("分析:")
print()
print("从上表可以看出:")
print(f"  - 主臂在 {leader_max} (最大值) 时，从臂 Goal_Position = {follower_max}")
print(f"  - 从臂实际物理位置 = {follower_max} + {follower_offset} = {follower_max + follower_offset}")
print()

if follower_max + follower_offset <= 4095:
    print("✓ 从臂不会溢出，理论上应该正常工作")
    print()
    print("如果仍然出现问题，可能的原因:")
    print("  1. 从臂舵机硬件的 homing_offset 还是旧值 (1516)")
    print("     → 需要运行脚本将新的 offset 写入硬件")
    print()
    print("  2. 主臂的实际 PWM 值超出了标定范围")
    print("     → 需要重新标定主臂，确保范围正确")
    print()
    print("  3. 从臂的 range_max (3510) 设置过大")
    print("     → 可以尝试减小 range_max")
else:
    print(f"❌ 从臂会溢出! {follower_max + follower_offset} > 4095")
    print()
    print("解决方案:")
    safe_offset = 4095 - follower_max - 100
    print(f"  将从臂 homing_offset 改为 {safe_offset} 或更小")

print()
print("=" * 80)
print("建议的调试步骤")
print("=" * 80)
print()
print("1. 检查从臂舵机硬件的 homing_offset:")
print("   python3 scripts/check_follower_hardware.py")
print()
print("2. 如果硬件 offset 不是 485，写入新值:")
print("   python3 scripts/write_follower_calibration.py")
print()
print("3. 实时监控主臂和从臂的 PWM 值:")
print("   python3 scripts/diagnose_gripper_issue.py")
print()
print("4. 如果问题仍然存在，尝试减小从臂 range_max:")
print("   将 SO101-follower.json 中 gripper 的 range_max 从 3510 改为 3000")
