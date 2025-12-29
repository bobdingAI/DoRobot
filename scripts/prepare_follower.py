#!/usr/bin/env python3
"""准备从臂：检查并移动到安全初始位置"""

import os
import sys
from piper_sdk import C_PiperInterface
import time

# 安全初始位置（参考位置）
SAFE_HOME_POSITION = [5370, -2113, 3941, 3046, 18644, 24400]
POSITION_TOLERANCE = 500  # 0.5度的容差（500 millidegrees）


def enable_arm(piper: C_PiperInterface, timeout: float = 5.0) -> bool:
    """使能机械臂"""
    enable_flag = all(piper.GetArmEnableStatus())
    start_time = time.time()
    retry_count = 0

    while not enable_flag:
        enable_flag = piper.EnablePiper()
        retry_count += 1
        if retry_count % 10 == 1:
            print(f"[Follower Prepare] 使能中... (尝试 {retry_count})")
        time.sleep(0.1)
        if time.time() - start_time > timeout:
            print(f"[Follower Prepare] ❌ 使能超时 ({timeout}秒)")
            return False

    print(f"[Follower Prepare] ✓ 使能成功 ({time.time() - start_time:.2f}秒)")
    return True


def get_current_position(piper: C_PiperInterface) -> list[int]:
    """读取当前关节位置"""
    joint = piper.GetArmJointMsgs()
    return [
        joint.joint_state.joint_1.real,
        joint.joint_state.joint_2.real,
        joint.joint_state.joint_3.real,
        joint.joint_state.joint_4.real,
        joint.joint_state.joint_5.real,
        joint.joint_state.joint_6.real,
    ]


def check_position_difference(current: list[int], target: list[int]) -> tuple[bool, float, list[float]]:
    """检查位置差异"""
    diffs = [abs(c - t) for c, t in zip(current, target)]
    max_diff = max(diffs)
    diffs_degrees = [d / 1000 for d in diffs]
    is_close = max_diff < POSITION_TOLERANCE
    return is_close, max_diff / 1000, diffs_degrees


def main():
    can_bus = os.getenv("CAN_BUS", "can_left")

    print("=" * 70)
    print("[Follower Prepare] Piper 从臂准备工具")
    print("=" * 70)
    print(f"CAN 总线: {can_bus}")
    print(f"参考位置: {SAFE_HOME_POSITION}")
    print(f"参考位置（度）: {[p/1000 for p in SAFE_HOME_POSITION]}")
    print(f"位置容差: {POSITION_TOLERANCE/1000}度")
    print("=" * 70)
    print()

    # 连接机械臂
    piper = C_PiperInterface(can_bus)
    piper.ConnectPort()

    # 使能机械臂
    if not enable_arm(piper):
        sys.exit(1)

    # 读取当前位置
    print("[Follower Prepare] 读取当前位置...")
    current_pos = get_current_position(piper)
    print(f"当前位置: {current_pos}")
    print(f"当前位置（度）: {[p/1000 for p in current_pos]}")
    print()

    # 检查位置差异
    is_close, max_diff, diffs = check_position_difference(current_pos, SAFE_HOME_POSITION)

    print(f"位置差异（度）: {diffs}")
    print(f"最大差异: {max_diff:.3f}度")
    print()

    if is_close:
        print("[Follower Prepare] ✓ 从臂已在参考位置附近，无需移动")
        print("[Follower Prepare] ✓ 准备完成，可以开始遥操作")
    else:
        print(f"[Follower Prepare] ⚠️  从臂位置偏离参考位置 {max_diff:.3f}度")
        print("[Follower Prepare] 正在移动到参考位置...")

        # 设置运动速度
        piper.MotionCtrl_2(0x01, 0x01, 30, 0x00)

        # 移动到参考位置
        piper.JointCtrl(
            SAFE_HOME_POSITION[0],
            SAFE_HOME_POSITION[1],
            SAFE_HOME_POSITION[2],
            SAFE_HOME_POSITION[3],
            SAFE_HOME_POSITION[4],
            SAFE_HOME_POSITION[5]
        )

        print("[Follower Prepare] 等待到达参考位置...")
        time.sleep(3)

        # 验证位置
        final_pos = get_current_position(piper)
        is_close, max_diff, diffs = check_position_difference(final_pos, SAFE_HOME_POSITION)

        if is_close:
            print("[Follower Prepare] ✓ 已到达参考位置")
            print("[Follower Prepare] ✓ 准备完成，可以开始遥操作")
        else:
            print(f"[Follower Prepare] ⚠️  位置仍有偏差 {max_diff:.3f}度")
            print("[Follower Prepare] ⚠️  建议检查机械臂状态")

    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
