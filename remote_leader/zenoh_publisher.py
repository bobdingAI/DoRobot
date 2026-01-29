"""
Zenoh Publisher for SO101 Leader Arm

This module provides the Zenoh publishing functionality for the leader arm,
including joint state, calibration, and heartbeat publishing.
"""

import time
import json
import threading
from typing import Optional, Callable
from dataclasses import dataclass

try:
    import zenoh
except ImportError:
    raise ImportError(
        "zenoh is required. Install with: pip install eclipse-zenoh"
    )

from messages import (
    JointStateMessage, HeartbeatMessage, CalibrationMessage,
    MotorCalibrationInfo, SystemState, JointFlags,
    get_topic_names, MOTOR_NAMES, PROTOCOL_VERSION
)


@dataclass
class LeaderConfig:
    """Configuration for the leader Zenoh publisher."""
    system_id: str = "so101"
    zenoh_listen: str = "tcp/0.0.0.0:7447"
    zenoh_connect: list[str] = None
    heartbeat_rate_hz: float = 1.0
    enable_multicast: bool = True


class LeaderZenohPublisher:
    """
    Zenoh publisher for the SO101 leader arm.

    Handles:
    - Joint state publishing at configurable rate
    - Calibration info publishing
    - Heartbeat publishing
    - Follower state subscription (optional)
    """

    def __init__(self, config: LeaderConfig):
        self.config = config
        self.topics = get_topic_names(config.system_id)

        # Zenoh session and publishers
        self._session: Optional[zenoh.Session] = None
        self._joint_pub = None
        self._cal_pub = None
        self._heartbeat_pub = None

        # State tracking
        self._sequence = 0
        self._heartbeat_sequence = 0
        self._connected = False
        self._state = SystemState.INITIALIZING

        # Heartbeat thread
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()

        # Follower state callback
        self._follower_state_callback: Optional[Callable] = None
        self._follower_sub = None

        # Statistics
        self._last_publish_time = 0
        self._publish_count = 0
        self._fps = 0.0

    def connect(self) -> bool:
        """
        Initialize Zenoh session and create publishers.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            # Configure Zenoh
            zenoh_config = zenoh.Config()

            # Set listen endpoint
            if self.config.zenoh_listen:
                zenoh_config.insert_json5(
                    "listen/endpoints",
                    json.dumps([self.config.zenoh_listen])
                )

            # Set connect endpoints if provided
            if self.config.zenoh_connect:
                zenoh_config.insert_json5(
                    "connect/endpoints",
                    json.dumps(self.config.zenoh_connect)
                )

            # Enable multicast scouting for peer discovery
            if self.config.enable_multicast:
                zenoh_config.insert_json5("scouting/multicast/enabled", "true")

            # Open session
            print(f"[Leader] Opening Zenoh session on {self.config.zenoh_listen}...")
            self._session = zenoh.open(zenoh_config)

            # Create publishers
            self._joint_pub = self._session.declare_publisher(
                self.topics["leader_joint"]
            )
            self._cal_pub = self._session.declare_publisher(
                self.topics["leader_calibration"]
            )
            self._heartbeat_pub = self._session.declare_publisher(
                self.topics["leader_heartbeat"]
            )

            print(f"[Leader] Publishing joint state on: {self.topics['leader_joint']}")
            print(f"[Leader] Publishing calibration on: {self.topics['leader_calibration']}")
            print(f"[Leader] Publishing heartbeat on: {self.topics['leader_heartbeat']}")

            # Start heartbeat thread
            self._start_heartbeat_thread()

            self._connected = True
            self._state = SystemState.READY

            return True

        except Exception as e:
            print(f"[Leader] Failed to connect: {e}")
            return False

    def disconnect(self) -> None:
        """Clean disconnect from Zenoh network."""
        print("[Leader] Disconnecting...")

        self._state = SystemState.DISCONNECTING

        # Stop heartbeat thread
        if self._heartbeat_thread is not None:
            self._heartbeat_stop.set()
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None

        # Close session
        if self._session is not None:
            self._session.close()
            self._session = None

        self._connected = False
        print("[Leader] Disconnected.")

    def publish_joint_state(
        self,
        positions: list[float],
        flags: int = JointFlags.NORMALIZED | JointFlags.DEGREES_MODE | JointFlags.CALIBRATED
    ) -> None:
        """
        Publish normalized joint positions.

        Args:
            positions: List of 6 normalized joint positions
                      [shoulder_pan, shoulder_lift, elbow_flex,
                       wrist_flex, wrist_roll, gripper]
            flags: Status flags (default: NORMALIZED | DEGREES_MODE | CALIBRATED)
        """
        if not self._connected or self._joint_pub is None:
            return

        # Create and publish message
        msg = JointStateMessage.create(positions, self._sequence, flags)
        self._joint_pub.put(msg.to_bytes())

        # Update statistics
        self._sequence += 1
        self._update_fps()

    def publish_calibration(self, calibration: dict, arm_name: str = "SO101-leader") -> None:
        """
        Publish calibration info.

        Args:
            calibration: Dictionary of motor calibrations
            arm_name: Name of the arm
        """
        if not self._connected or self._cal_pub is None:
            return

        # Convert to message format
        motors = {}
        norm_modes = {
            "shoulder_pan": "degrees",
            "shoulder_lift": "degrees",
            "elbow_flex": "degrees",
            "wrist_flex": "degrees",
            "wrist_roll": "degrees",
            "gripper": "range_0_100"
        }

        for motor_name, cal in calibration.items():
            motors[motor_name] = MotorCalibrationInfo(
                id=cal.id,
                drive_mode=cal.drive_mode,
                homing_offset=cal.homing_offset,
                range_min=cal.range_min,
                range_max=cal.range_max,
                norm_mode=norm_modes.get(motor_name, "degrees")
            )

        msg = CalibrationMessage(
            version=PROTOCOL_VERSION,
            timestamp_ns=time.time_ns(),
            arm_name=arm_name,
            arm_role="leader",
            motors=motors
        )

        self._cal_pub.put(msg.to_bytes())
        print(f"[Leader] Published calibration for {len(motors)} motors")

    def set_follower_state_callback(
        self,
        callback: Callable[[list[float], int], None]
    ) -> None:
        """
        Register callback for receiving follower state feedback.

        Args:
            callback: Function called with (positions, flags) when
                     follower state is received
        """
        self._follower_state_callback = callback

        # Subscribe to follower joint state
        if self._session is not None and self._follower_sub is None:
            def on_follower_joint(sample):
                try:
                    msg = JointStateMessage.from_bytes(sample.payload.to_bytes())
                    if self._follower_state_callback:
                        self._follower_state_callback(msg.positions, msg.flags)
                except Exception as e:
                    print(f"[Leader] Error parsing follower state: {e}")

            self._follower_sub = self._session.declare_subscriber(
                self.topics["follower_joint"],
                on_follower_joint
            )
            print(f"[Leader] Subscribed to follower state: {self.topics['follower_joint']}")

    def get_connection_status(self) -> dict:
        """
        Get current connection status.

        Returns:
            Dict with keys: connected, state, fps, sequence
        """
        return {
            "connected": self._connected,
            "state": self._state.name,
            "fps": self._fps,
            "sequence": self._sequence,
        }

    def set_state(self, state: SystemState) -> None:
        """Set the current system state."""
        self._state = state

    # =========================================================================
    # Private methods
    # =========================================================================

    def _start_heartbeat_thread(self) -> None:
        """Start the heartbeat publishing thread."""
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Heartbeat publishing loop."""
        period = 1.0 / self.config.heartbeat_rate_hz

        while not self._heartbeat_stop.is_set():
            if self._connected and self._heartbeat_pub is not None:
                try:
                    msg = HeartbeatMessage.create(
                        sequence=self._heartbeat_sequence,
                        state=self._state,
                        fps=self._fps,
                        latency_us=0
                    )
                    self._heartbeat_pub.put(msg.to_bytes())
                    self._heartbeat_sequence += 1
                except Exception as e:
                    print(f"[Leader] Heartbeat error: {e}")

            self._heartbeat_stop.wait(period)

    def _update_fps(self) -> None:
        """Update FPS calculation."""
        now = time.time()
        self._publish_count += 1

        if self._last_publish_time > 0:
            elapsed = now - self._last_publish_time
            if elapsed > 0:
                # Exponential moving average
                instant_fps = 1.0 / elapsed
                self._fps = 0.9 * self._fps + 0.1 * instant_fps

        self._last_publish_time = now
