import pickle
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
import os
import ctypes
import platform
import sys
import json
import numpy as np
import torch

from typing import Any
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from functools import cache
from functools import cached_property

import threading
import cv2

import zmq

from operating_platform.robot.robots.utils import RobotDeviceNotConnectedError
from operating_platform.robot.robots.configs import PiperV1RobotConfig
from operating_platform.config.cameras import CameraConfig, OpenCVCameraConfig

from operating_platform.robot.robots.camera import Camera


ipc_address_image = "ipc:///tmp/dora-zeromq-piper-image"
ipc_address_joint = "ipc:///tmp/dora-zeromq-piper-joint"

recv_images = {}
recv_joint = {}
lock = threading.Lock()  # 线程锁

running_recv_image_server = True
running_recv_joint_server = True

# Connection state tracking
_image_connected = False
_joint_connected = False

# ZeroMQ context and sockets (initialized lazily, cleaned up on disconnect)
zmq_context = None
socket_image = None
socket_joint = None
_zmq_initialized = False


def _init_zmq():
    """Initialize ZeroMQ sockets (lazy initialization)."""
    global zmq_context, socket_image, socket_joint, _zmq_initialized

    if _zmq_initialized:
        return

    zmq_context = zmq.Context()

    socket_image = zmq_context.socket(zmq.PAIR)
    socket_image.connect(ipc_address_image)
    socket_image.setsockopt(zmq.RCVTIMEO, 2000)

    socket_joint = zmq_context.socket(zmq.PAIR)
    socket_joint.connect(ipc_address_joint)
    socket_joint.setsockopt(zmq.RCVTIMEO, 2000)

    _zmq_initialized = True
    print("[PiperV1] ZeroMQ sockets initialized")


def _cleanup_zmq():
    """Clean up ZeroMQ sockets and context."""
    global zmq_context, socket_image, socket_joint, _zmq_initialized
    global _image_connected, _joint_connected

    if not _zmq_initialized:
        return

    try:
        if socket_image is not None:
            socket_image.close(linger=0)
            socket_image = None
        if socket_joint is not None:
            socket_joint.close(linger=0)
            socket_joint = None
        if zmq_context is not None:
            zmq_context.term()
            zmq_context = None

        _zmq_initialized = False
        _image_connected = False
        _joint_connected = False
        print("[PiperV1] ZeroMQ sockets cleaned up")
    except Exception as e:
        print(f"[PiperV1] Error cleaning up ZeroMQ: {e}")

def piper_zmq_send(event_id, buffer, wait_time_s):
    buffer_bytes = buffer.tobytes()
    # print(f"zmq send event_id:{event_id}, value:{buffer}")
    try:
        socket_joint.send_multipart([
            event_id.encode('utf-8'),
            buffer_bytes
        ], flags=zmq.NOBLOCK)
    except zmq.Again:
        pass
    time.sleep(wait_time_s)

def recv_image_server():
    """接收数据线程"""
    global _image_connected
    while running_recv_image_server:
        if socket_image is None:
            time.sleep(0.1)
            continue
        try:
            message_parts = socket_image.recv_multipart()
            if len(message_parts) < 2:
                continue  # 协议错误

            event_id = message_parts[0].decode('utf-8')
            buffer_bytes = message_parts[1]
            metadata = json.loads(message_parts[2].decode('utf-8'))

            # Mark as connected on first successful receive
            if not _image_connected:
                _image_connected = True
                print("[PiperV1] Camera data stream connected")

            if 'image' in event_id:
                # 解码图像
                img_array = np.frombuffer(buffer_bytes, dtype=np.uint8)
                encoding = metadata["encoding"].lower()
                width = metadata["width"]
                height = metadata["height"]

                if encoding == "bgr8":
                    channels = 3
                    frame = (
                        img_array.reshape((height, width, channels))
                        .copy()  # Copy So that we can add annotation on the image
                    )
                elif encoding == "rgb8":
                    channels = 3
                    frame = (img_array.reshape((height, width, channels)))
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

                elif encoding in ["jpeg", "jpg", "jpe", "bmp", "webp", "png"]:
                    channels = 3
                    frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                if frame is not None:
                    with lock:
                        # print(f"Received event_id = {event_id}")
                        recv_images[event_id] = frame

        except zmq.Again:
            # Timeout waiting for data, silently continue
            continue
        except Exception as e:
            print("[PiperV1] recv image error:", e)
            break


def recv_joint_server():
    """接收数据线程"""
    global _joint_connected
    while running_recv_joint_server:
        if socket_joint is None:
            time.sleep(0.1)
            continue
        try:
            message_parts = socket_joint.recv_multipart()
            if len(message_parts) < 2:
                continue  # 协议错误

            event_id = message_parts[0].decode('utf-8')
            buffer_bytes = message_parts[1]

            # Mark as connected on first successful receive
            if not _joint_connected:
                _joint_connected = True
                print("[PiperV1] Joint data stream connected")

            if 'joint' in event_id:
                joint_array = np.frombuffer(buffer_bytes, dtype=np.float32)
                if joint_array is not None:
                    # print(f"Received pose data for event_id: {event_id}")
                    with lock:
                        recv_joint[event_id] = joint_array

        except zmq.Again:
            # Timeout waiting for data, silently continue
            continue
        except Exception as e:
            print("[PiperV1] recv joint error:", e)
            break



class OpenCVCamera:
    def __init__(self, config: OpenCVCameraConfig):
        self.config = config
        self.camera_index = config.camera_index
        self.port = None

        # Store the raw (capture) resolution from the config.
        self.capture_width = config.width
        self.capture_height = config.height

        # If rotated by ±90, swap width and height.
        if config.rotation in [-90, 90]:
            self.width = config.height
            self.height = config.width
        else:
            self.width = config.width
            self.height = config.height

        self.fps = config.fps
        self.channels = config.channels
        self.color_mode = config.color_mode
        self.mock = config.mock

        self.camera = None
        self.is_connected = False
        self.thread = None
        self.stop_event = None
        self.color_image = None
        self.logs = {}



def make_cameras_from_configs(camera_configs: dict[str, CameraConfig]) -> list[Camera]:
    cameras = {}

    for key, cfg in camera_configs.items():
        if cfg.type == "opencv":
            cameras[key] = OpenCVCamera(cfg)
        else:
            raise ValueError(f"The camera type '{cfg.type}' is not valid.")

    return cameras



class PiperV1Manipulator:
    def __init__(self, config: PiperV1RobotConfig):
        self.config = config
        self.robot_type = self.config.type

        self.use_videos = self.config.use_videos
        self.microphones = getattr(self.config, 'microphones', {})

        # Leader arms
        self.leader_arms = {}
        if "main" in self.config.leader_arms:
            self.leader_arms['main_leader'] = self.config.leader_arms["main"]

        # Follower arms
        self.follower_arms = {}
        if "main" in self.config.follower_arms:
            self.follower_arms['main_follower'] = self.config.follower_arms["main"]
        
        self.cameras = make_cameras_from_configs(self.config.cameras)
        self.connect_excluded_cameras = []

        self.recv_image_thread = threading.Thread(target=recv_image_server, daemon=True)
        self.recv_image_thread.start()

        self.recv_joint_thread = threading.Thread(target=recv_joint_server, daemon=True)
        self.recv_joint_thread.start()

        self.is_connected = False
        self.logs = {}

    def get_motor_names(self, arms: dict[str, dict]) -> list:
        return [f"{arm}_{motor}" for arm, bus in arms.items() for motor in bus.motors]
    
    @property
    def _leader_motors_ft(self) -> dict[str, type]:
        return {f"{arm}_{motor}.pos": float for arm, bus in self.leader_arms.items() for motor in bus.motors}
    
    @property
    def _follower_motors_ft(self) -> dict[str, type]:
        return {f"{arm}_{motor}.pos": float for arm, bus in self.follower_arms.items() for motor in bus.motors}

    @property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {
            cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3) for cam in self.cameras
        }

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._follower_motors_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._leader_motors_ft

    @property
    def camera_features(self) -> dict:
        cam_ft = {}
        for cam_key, cam in self.cameras.items():
            key = f"observation.images.{cam_key}"
            cam_ft[key] = {
                "shape": (cam.height, cam.width, cam.channels),
                "names": ["height", "width", "channels"],
                "info": None,
            }
        return cam_ft
    
    @property
    def microphone_features(self) -> dict:
        mic_ft = {}
        for mic_key, mic in self.microphones.items():
            key = f"observation.audio.{mic_key}"
            mic_ft[key] = {
                "shape": (1,),
                "names": ["channels"],
                "info": None,
            }
        return mic_ft
    
    @property
    def motor_features(self) -> dict:
        action_names = self.get_motor_names(self.leader_arms)
        state_names = self.get_motor_names(self.follower_arms)
        return {
            "action": {
                "dtype": "float32",
                "shape": (len(action_names),),
                "names": action_names,
            },
            "observation.state": {
                "dtype": "float32",
                "shape": (len(state_names),),
                "names": state_names,
            },
        }
    
    def connect(self):
        # Initialize ZeroMQ sockets
        _init_zmq()

        timeout = 50
        start_time = time.perf_counter()

        print("[PiperV1] Detecting available data streams...")
        leader_arm_timeout = 3.0
        leader_arm_start = time.perf_counter()
        has_leader_arm_data = False
        while time.perf_counter() - leader_arm_start < leader_arm_timeout:
            if any(any(name in key for key in recv_joint) for name in self.leader_arms):
                has_leader_arm_data = True
                break
            time.sleep(0.1)

        if has_leader_arm_data:
            print("[PiperV1] Leader arm data detected - teleoperation mode")
        else:
            print("[PiperV1] No leader arm data - inference mode (follower only)")

        conditions = [
            (
                lambda: all(name in recv_images for name in self.cameras if name not in self.connect_excluded_cameras),
                lambda: [name for name in self.cameras if name not in recv_images],
                "等待摄像头图像超时"
            ),
            (
                lambda: all(
                    any(name in key for key in recv_joint)
                    for name in self.follower_arms
                ),
                lambda: [name for name in self.follower_arms if not any(name in key for key in recv_joint)],
                "等待从臂关节角度超时"
            ),
        ]

        if has_leader_arm_data:
            conditions.insert(1, (
                lambda: all(
                    any(name in key for key in recv_joint)
                    for name in self.leader_arms
                ),
                lambda: [name for name in self.leader_arms if not any(name in key for key in recv_joint)],
                "等待主臂关节角度超时"
            ))

        completed = [False] * len(conditions)

        while True:
            for i in range(len(conditions)):
                if not completed[i]:
                    condition_func = conditions[i][0]
                    if condition_func():
                        completed[i] = True

            if all(completed):
                break

            if time.perf_counter() - start_time > timeout:
                failed_messages = []
                for i in range(len(completed)):
                    if not completed[i]:
                        condition_func, get_missing, base_msg = conditions[i]
                        missing = get_missing()

                        if condition_func():
                            completed[i] = True
                            continue

                        if not missing:
                            completed[i] = True
                            continue

                        if "摄像头" in base_msg:
                            received = [name for name in self.cameras if name not in missing]
                        elif "主臂" in base_msg:
                            received = [name for name in self.leader_arms if name not in missing]
                        elif "从臂" in base_msg:
                            received = [name for name in self.follower_arms if name not in missing]
                        else:
                            received = []

                        msg = f"{base_msg}: 未收到 [{', '.join(missing)}]; 已收到 [{', '.join(received)}]"
                        failed_messages.append(msg)

                if not failed_messages:
                    break
                
                if recv_joint:
                    print(f"Debug - Current joint keys: {list(recv_joint.keys())}")

                raise TimeoutError(f"连接超时，未满足的条件: {'; '.join(failed_messages)}")

            time.sleep(0.01)

        success_messages = []
        cam_received = [name for name in self.cameras
                    if name in recv_images and name not in self.connect_excluded_cameras]
        if cam_received:
            success_messages.append(f"摄像头: {', '.join(cam_received)}")

        if has_leader_arm_data:
            arm_received = [name for name in self.leader_arms
                        if any(name in key for key in recv_joint)]
            if arm_received:
                success_messages.append(f"主臂关节角度: {', '.join(arm_received)}")

        arm_received = [name for name in self.follower_arms
                    if any(name in key for key in recv_joint)]
        if arm_received:
            success_messages.append(f"从臂关节角度: {', '.join(arm_received)}")
        
        print("\n[连接成功] PiperV1 所有设备已就绪:")
        for msg in success_messages:
            print(f"  - {msg}")
        print(f"  总耗时: {time.perf_counter() - start_time:.2f}秒\n")

        self.is_connected = True
    
    @property
    def features(self):
        return {**self.motor_features, **self.camera_features}

    @property
    def has_camera(self):
        return len(self.cameras) > 0

    @property
    def num_cameras(self):
        return len(self.cameras)

    def teleop_step(
        self, record_data=False, 
    ) -> None | tuple[dict[str, Any], dict[str, Any]]:

        if not self.is_connected:
            raise RobotDeviceNotConnectedError(
                "PiperV1 is not connected. You need to run `robot.connect()`."
            )

        if not record_data:
            return

        follower_joint = {}
        for name in self.follower_arms:
            for match_name in recv_joint:
                if name in match_name:
                    now = time.perf_counter()
                    # Piper has 7 values: 6 joints + 1 gripper
                    byte_array = np.zeros(7, dtype=np.float32)
                    pose_read = recv_joint[match_name]
                    byte_array[:7] = pose_read[:7]
                    byte_array = np.round(byte_array, 4)
                    follower_joint[name] = byte_array
                    self.logs[f"read_follower_{name}_joint_dt_s"] = time.perf_counter() - now
                    
        leader_joint = {}
        for name in self.leader_arms:
            for match_name in recv_joint:
                if name in match_name:
                    now = time.perf_counter()
                    byte_array = np.zeros(7, dtype=np.float32)
                    pose_read = recv_joint[match_name]
                    byte_array[:7] = pose_read[:7]
                    byte_array = np.round(byte_array, 4)
                    leader_joint[name] = byte_array
                    self.logs[f"read_leader_{name}_joint_dt_s"] = time.perf_counter() - now

        obs_dict, action_dict = {}, {}

        for name, arm in self.follower_arms.items():
            if name in follower_joint:
                for motor, value in arm.motors.items():
                    # value[0] is the index in the motor list (1-based)
                    idx = value[0] - 1
                    if idx < len(follower_joint[name]):
                        obs_dict[f"{name}_{motor}.pos"] = follower_joint[name][idx]

        for name, arm in self.leader_arms.items():
            if name in leader_joint:
                for motor, value in arm.motors.items():
                    idx = value[0] - 1
                    if idx < len(leader_joint[name]):
                        action_dict[f"{name}_{motor}.pos"] = leader_joint[name][idx]

        for name in self.cameras:
            now = time.perf_counter()
            obs_dict[f"{name}"] = recv_images[name]
            self.logs[f"read_camera_{name}_dt_s"] = time.perf_counter() - now

        return obs_dict, action_dict

    def capture_observation(self) -> dict[str, Any]:
        if not self.is_connected:
            raise RobotDeviceNotConnectedError(
                "PiperV1 is not connected. You need to run `robot.connect()`."
            )

        obs_dict = {}
        # Fetch current follower state
        for name, arm in self.follower_arms.items():
            for match_name in recv_joint:
                if name in match_name:
                    pose_read = recv_joint[match_name]
                    for motor, value in arm.motors.items():
                        idx = value[0] - 1
                        if idx < len(pose_read):
                            obs_dict[f"{name}_{motor}.pos"] = pose_read[idx]

        # Fetch current images
        for name in self.cameras:
            if name in recv_images:
                obs_dict[f"{name}"] = recv_images[name]
        
        return obs_dict

    def send_action(self, action: dict[str, Any]):
        if not self.is_connected:
            raise RobotDeviceNotConnectedError(
                "PiperV1 is not connected. You need to run `robot.connect()`."
            )

        for name in self.follower_arms:
            # Construct the action vector for the follower
            # We look for keys like 'main_follower_joint_1.pos', etc.
            goal_joint = []
            arm_bus = self.follower_arms[name]
            
            # Sort motors by their index to construct a consistent vector
            sorted_motors = sorted(arm_bus.motors.items(), key=lambda x: x[1][0])
            for motor_name, _ in sorted_motors:
                key = f"{name}_{motor_name}.pos"
                if key in action:
                    val = action[key]
                    if isinstance(val, (torch.Tensor, np.ndarray)):
                        val = val.item()
                    goal_joint.append(val)
            
            if goal_joint:
                goal_joint_numpy = np.array(goal_joint, dtype=np.float32)
                # Send to DORA via ZeroMQ bridge
                piper_zmq_send("action_joint", goal_joint_numpy, wait_time_s=0.01)

    def disconnect(self):
        if not self.is_connected:
            raise RobotDeviceNotConnectedError(
                "PiperV1 is not connected. You need to run `robot.connect()` before disconnecting."
            )

        print("[PiperV1] Disconnecting robot...")
        self.is_connected = False

        global running_recv_image_server
        global running_recv_joint_server
        running_recv_image_server = False
        running_recv_joint_server = False

        if self.recv_image_thread.is_alive():
            self.recv_image_thread.join(timeout=3.0)
        if self.recv_joint_thread.is_alive():
            self.recv_joint_thread.join(timeout=3.0)

        _cleanup_zmq()

        recv_images.clear()
        recv_joint.clear()

        print("[PiperV1] Robot disconnected")

    def __del__(self):
        if getattr(self, "is_connected", False):
            try:
                self.disconnect()
            except Exception as e:
                print(f"[PiperV1] Error during cleanup: {e}")
