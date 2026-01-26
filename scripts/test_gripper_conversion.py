#!/usr/bin/env python3
"""
测试夹爪值转换逻辑
"""

import numpy as np

def old_conversion(position_value):
    """旧的转换逻辑（使用 abs）"""
    return int(abs(position_value * 1000 * 1000))

def new_conversion(position_value):
    """新的转换逻辑（钳制 + 反转）"""
    gripper_value = max(0.0, min(1.0, position_value))
    gripper_value = 1.0 - gripper_value  # Invert direction
    return int(gripper_value * 1000 * 1000)

print("=" * 80)
print("夹爪值转换测试")
print("=" * 80)
print()

# 测试不同的输入值
test_cases = [
    ("完全松开", 0.0),
    ("1/4 闭合", 0.25),
    ("半闭合", 0.5),
    ("3/4 闭合", 0.75),
    ("完全闭合", 1.0),
    ("负值（异常）", -0.5),
    ("超过1（异常）", 1.5),
    ("NaN", np.nan),
]

print(f"{'状态':<15} {'输入值':<10} {'旧逻辑(abs)':<15} {'新逻辑(反转)':<15} {'差异'}")
print("-" * 80)

for name, value in test_cases:
    if np.isnan(value):
        print(f"{name:<15} {str(value):<10} {'跳过':<15} {'跳过':<15} N/A")
        continue

    old_val = old_conversion(value)
    new_val = new_conversion(value)
    diff = new_val - old_val

    print(f"{name:<15} {value:<10.2f} {old_val:<15} {new_val:<15} {diff:+d}")

print()
print("=" * 80)
print("分析")
print("=" * 80)
print()
print("旧逻辑（abs）：")
print("  - 0.0 → 0 (松开)")
print("  - 1.0 → 1000000 (闭合)")
print("  - 负值会被转成正值（错误！）")
print()
print("新逻辑（反转）：")
print("  - 0.0 → 1000000 (松开)")
print("  - 1.0 → 0 (闭合)")
print("  - 负值被钳制到 0，然后反转成 1000000")
print()
print("问题诊断：")
print("  如果 Piper 夹爪的定义是：")
print("    - 0 = 闭合")
print("    - 1000000 = 松开")
print("  那么新逻辑是正确的。")
print()
print("  如果 Piper 夹爪的定义是：")
print("    - 0 = 松开")
print("    - 1000000 = 闭合")
print("  那么不需要反转，应该直接映射。")
