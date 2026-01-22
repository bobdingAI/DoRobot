"""TODO: Add docstring."""

import os
import time

import numpy as np
import pyarrow as pa
from dora import Node
from piper_sdk import C_PiperInterface


def enable_fun(piper: C_PiperInterface):
    """使能机械臂并检测使能状态,尝试5秒,如果使能超时则退出程序."""
    enable_flag = all(piper.GetArmEnableStatus())

    timeout = 5.0  # 超时时间（秒）- 增加到5秒以确保机械臂有足够时间使能
    interval = 0.1  # 每次轮询间隔（秒）

    start_time = time.time()
    retry_count = 0

    while not enable_flag:
        enable_flag = piper.EnablePiper()
        retry_count += 1

        # Only print every 10 retries to reduce log spam
        if retry_count % 10 == 1:
            print(f"[Piper] 使能状态: {enable_flag} (尝试 {retry_count})")

        time.sleep(interval)
        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
            print(f"[Piper] 机械臂自动使能超时 ({timeout}秒后)")
            print("[Piper] 请检查: 1) CAN总线连接 2) 机械臂电源 3) 急停按钮")
            break

    elapsed_time = time.time() - start_time
    if enable_flag:
        print(f"[Piper] 机械臂使能成功 (耗时 {elapsed_time:.2f}秒)")


def main():
    """TODO: Add docstring."""
    elapsed_time = time.time()
    can_bus = os.getenv("CAN_BUS", "")
    piper = C_PiperInterface(can_bus)
    piper.ConnectPort()
    enable_fun(piper)
    # piper.GripperCtrl(0, 3000, 0x01, 0)

    factor = 1000 * 180 / np.pi  # Convert rad to 0.001 degrees
    node = Node()

    # Initialize motion control once with a safe speed (e.g. 80%)
    # Sending this in every loop can cause jerky motion as it resets the planner.
    piper.MotionCtrl_2(0x01, 0x01, 80, 0x00)

    # Pose mapping: Read current follower position as baseline (safe position)
    # This allows teleoperation even when leader/follower calibrations differ
    print("[Piper] 读取当前从臂位置作为安全基准...")
    current_joint = piper.GetArmJointMsgs()
    follower_baseline = [
        current_joint.joint_state.joint_1.real,
        current_joint.joint_state.joint_2.real,
        current_joint.joint_state.joint_3.real,
        current_joint.joint_state.joint_4.real,
        current_joint.joint_state.joint_5.real,
        current_joint.joint_state.joint_6.real,
    ]
    print(f"[Piper] 从臂安全位置（度）: {[f'{p/1000:.1f}' for p in follower_baseline]}")
    print("[Piper] 等待首次主臂命令以建立映射...")

    ctrl_frame = 0
    first_command_received = False
    leader_baseline = None  # Will be set on first command

    # Safety monitoring configuration
    POSITION_DIFF_WARNING = 30000  # 30 degrees - print warning during operation
    POSITION_DIFF_EMERGENCY = 60000  # 60 degrees - emergency stop during operation
    monitor_interval = 0.5
    last_monitor_time = time.time()
    emergency_stop = False

    for event in node:
        if event["type"] == "INPUT":
            # Only enable if not already enabled to save CAN bandwidth
            if "action" in event["id"]:
                enable_flag = all(piper.GetArmEnableStatus())
                if not enable_flag:
                    enable_fun(piper)
                    piper.MotionCtrl_2(0x01, 0x01, 80, 0x00)

            if event["id"] == "action_joint":
                if ctrl_frame > 0:
                    continue

                if emergency_stop:
                    print("[Piper] 紧急停止状态，拒绝执行命令")
                    continue

                if time.time() - elapsed_time > 0.03:
                    elapsed_time = time.time()
                else:
                    continue

                position = event["value"].to_numpy().copy()

                # Invert joints for direction compensation
                position[0] = -position[0]  # joint_0
                position[1] = -position[1]  # joint_1
                position[2] = -position[2]  # joint_2
                position[3] = -position[3]  # joint_3
                position[5] = -position[5]  # joint_5

                # Get current follower arm position
                current_joint = piper.GetArmJointMsgs()
                current_positions = [
                    current_joint.joint_state.joint_1.real,
                    current_joint.joint_state.joint_2.real,
                    current_joint.joint_state.joint_3.real,
                    current_joint.joint_state.joint_4.real,
                    current_joint.joint_state.joint_5.real,
                    current_joint.joint_state.joint_6.real,
                ]

                # On first command: record leader baseline position
                if not first_command_received:
                    leader_baseline = [position[i] * factor for i in range(6)]
                    first_command_received = True
                    print("[Piper] 姿态映射基准已建立")
                    print(f"  主臂基准（度）: {[f'{p/1000:.1f}' for p in leader_baseline]}")
                    print(f"  从臂基准（度）: {[f'{p/1000:.1f}' for p in follower_baseline]}")
                    print("[Piper] 开始遥操作控制")

                # Apply pose mapping: target = follower_baseline + (leader_current - leader_baseline)
                leader_current = [position[i] * factor for i in range(6)]
                leader_offset = [leader_current[i] - leader_baseline[i] for i in range(6)]
                target_positions = [follower_baseline[i] + leader_offset[i] for i in range(6)]

                # Safety check: monitor movement speed (difference from current position)
                position_diffs = [abs(target_positions[i] - current_positions[i]) for i in range(6)]
                max_diff = max(position_diffs)
                max_diff_joint = position_diffs.index(max_diff)

                if max_diff > POSITION_DIFF_EMERGENCY:
                    emergency_stop = True
                    print("\n" + "="*70)
                    print("[Piper] ⚠️  紧急停止！移动速度过快！")
                    print("="*70)
                    print(f"关节 {max_diff_joint + 1} 差异: {max_diff/1000:.1f}度 (阈值: {POSITION_DIFF_EMERGENCY/1000}度)")
                    print(f"当前位置: {[p/1000 for p in current_positions]}")
                    print(f"目标位置: {[p/1000 for p in target_positions]}")
                    print("="*70)
                    break

                if time.time() - last_monitor_time > monitor_interval:
                    last_monitor_time = time.time()
                    if max_diff > POSITION_DIFF_WARNING:
                        print(f"[Piper] ⚠️  警告：关节{max_diff_joint + 1}差异 {max_diff/1000:.1f}度")

                piper.JointCtrl(
                    round(target_positions[0]),
                    round(target_positions[1]),
                    round(target_positions[2]),
                    round(target_positions[3]),
                    round(target_positions[4]),
                    round(target_positions[5])
                )
                if len(position) > 6 and not np.isnan(position[6]):
                    piper.GripperCtrl(int(abs(position[6] * 1000 * 1000)), 1000, 0x01, 0)

            elif event["id"] == "action_joint_ctrl":
                
                ctrl_frame = 200
                position = event["value"].to_numpy()
                joint_0 = round(position[0] * factor)
                joint_1 = round(position[1] * factor)
                joint_2 = round(position[2] * factor)
                joint_3 = round(position[3] * factor)
                joint_4 = round(position[4] * factor)
                joint_5 = round(position[5] * factor)

                # For manual control, we might want higher speed
                piper.MotionCtrl_2(0x01, 0x01, 100, 0x00)
                piper.JointCtrl(joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
                if len(position) > 6 and not np.isnan(position[6]):
                    piper.GripperCtrl(int(abs(position[6] * 1000 * 1000)), 1000, 0x01, 0)

            elif event["id"] == "action_endpose":
                
                # Do not push to many commands to fast. Limiting it to 30Hz
                if time.time() - elapsed_time > 0.03:
                    elapsed_time = time.time()
                else:
                    continue

                position = event["value"].to_numpy()
                piper.EndPoseCtrl(
                    position[0] * 1000 * 1000,
                    position[1] * 1000 * 1000,
                    position[2] * 1000 * 1000,
                    position[3] * 1000 / (2 * np.pi) * 360,
                    position[4] * 1000 / (2 * np.pi) * 360,
                    position[5] * 1000 / (2 * np.pi) * 360,
                )
            
            elif event["id"] == "action_gripper":
                # Do not push to many commands to fast. Limiting it to 30Hz
                if time.time() - elapsed_time > 0.03:
                    elapsed_time = time.time()
                else:
                    continue

                position = event["value"].to_numpy()
                piper.GripperCtrl(int(abs(position[0] * 1000 * 1000)), 1000, 0x01, 0)

            elif event["id"] == "tick":
                # Slave Arm
                joint = piper.GetArmJointMsgs()

                joint_value = []
                joint_value += [joint.joint_state.joint_1.real / factor]
                joint_value += [joint.joint_state.joint_2.real / factor]
                joint_value += [joint.joint_state.joint_3.real / factor]
                joint_value += [joint.joint_state.joint_4.real / factor]
                joint_value += [joint.joint_state.joint_5.real / factor]
                joint_value += [joint.joint_state.joint_6.real / factor]

                gripper = piper.GetArmGripperMsgs()
                joint_value += [gripper.gripper_state.grippers_angle / 1000 / 1000]

                node.send_output("slave_jointstate", pa.array(joint_value, type=pa.float32()))
                node.send_output("joint", pa.array(joint_value, type=pa.float32()))  # For SO101 compatibility

                position = piper.GetArmEndPoseMsgs()
                position_value = []
                position_value += [position.end_pose.X_axis * 0.001 * 0.001]
                position_value += [position.end_pose.Y_axis * 0.001 * 0.001]
                position_value += [position.end_pose.Z_axis * 0.001 * 0.001]
                position_value += [position.end_pose.RX_axis * 0.001 / 360 * 2 * np.pi]
                position_value += [position.end_pose.RY_axis * 0.001 / 360 * 2 * np.pi]
                position_value += [position.end_pose.RZ_axis * 0.001 / 360 * 2 * np.pi]

                node.send_output("slave_endpose", pa.array(position_value, type=pa.float32()))
                # node.send_output(
                #     "slave_gripper",
                #     pa.array(
                #         [gripper.gripper_state.grippers_angle / 1000 / 100],
                #         type=pa.float32(),
                #     ),
                # )

                # Master Arm
                joint = piper.GetArmJointCtrl()

                joint_value = []
                joint_value += [joint.joint_ctrl.joint_1.real / factor]
                joint_value += [joint.joint_ctrl.joint_2.real / factor]
                joint_value += [joint.joint_ctrl.joint_3.real / factor]
                joint_value += [joint.joint_ctrl.joint_4.real / factor]
                joint_value += [joint.joint_ctrl.joint_5.real / factor]
                joint_value += [joint.joint_ctrl.joint_6.real / factor]

                gripper = piper.GetArmGripperCtrl()
                joint_value += [gripper.gripper_ctrl.grippers_angle / 1000 / 1000]

                node.send_output("master_jointstate", pa.array(joint_value, type=pa.float32()))

                # position = piper.GetFK(mode="control")
                # position_value = []
                # position_value += [position[5][0] * 0.001]
                # position_value += [position[5][1] * 0.001]
                # position_value += [position[5][2] * 0.001]
                # position_value += [position[5][3] / 360 * 2 * np.pi]
                # position_value += [position[5][4] / 360 * 2 * np.pi]
                # position_value += [position[5][5] / 360 * 2 * np.pi]

                # node.send_output("master_endpose", pa.array(position_value, type=pa.float32()))


                # node.send_output(
                #     "master_gripper",
                #     pa.array(
                #         [gripper.gripper_ctrl.grippers_angle / 1000 / 100],
                #         type=pa.float32(),
                #     ),
                # )
            
            ctrl_frame -= 1

        elif event["type"] == "STOP":
            # if not TEACH_MODE:
            #     piper.MotionCtrl_2(0x01, 0x01, 50, 0x00)
            #     piper.JointCtrl(0, 0, 0, 0, 0, 0)
            #     piper.GripperCtrl(abs(0), 1000, 0x01, 0)
            #     piper.MotionCtrl_2(0x01, 0x01, 50, 0x00)
            # time.sleep(5)
            break


if __name__ == "__main__":
    main()
