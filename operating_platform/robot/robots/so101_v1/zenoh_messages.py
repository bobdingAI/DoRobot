"""
Zenoh Message Protocol for Distributed SO101 Teleoperation

This module defines the message formats for communication between
leader and follower systems over Zenoh.

Message Types:
- Joint State: Binary format for real-time joint positions (37 bytes)
- Calibration: JSON format for calibration exchange
- Heartbeat: Binary format for connection monitoring (19 bytes)
- Handshake: JSON format for connection establishment
"""

import struct
import time
import json
from dataclasses import dataclass, asdict
from typing import Optional
from enum import IntEnum, IntFlag


# =============================================================================
# Constants
# =============================================================================

# Joint message struct format: timestamp(u64) + sequence(u32) + positions(6xf32) + flags(u8)
JOINT_MSG_FORMAT = '<QI6fB'
JOINT_MSG_SIZE = struct.calcsize(JOINT_MSG_FORMAT)  # 37 bytes

# Heartbeat struct format: timestamp(u64) + sequence(u32) + state(u8) + fps_x10(u16) + latency_us(u32)
HEARTBEAT_MSG_FORMAT = '<QIBHI'
HEARTBEAT_MSG_SIZE = struct.calcsize(HEARTBEAT_MSG_FORMAT)  # 19 bytes

# Protocol version
PROTOCOL_VERSION = "1.0"

# Motor names in order (must match on both sides)
MOTOR_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper"
]


# =============================================================================
# Flags and Enums
# =============================================================================

class JointFlags(IntFlag):
    """Flags for joint state messages."""
    NORMALIZED = 0x01      # Data is normalized
    DEGREES_MODE = 0x02    # Using degrees normalization
    CALIBRATED = 0x04      # System is calibrated
    EMERGENCY = 0x80       # Emergency stop active


class SystemState(IntEnum):
    """System state for heartbeat messages."""
    INITIALIZING = 0
    CALIBRATING = 1
    READY = 2
    ACTIVE = 3
    ERROR = 4
    DISCONNECTING = 5


# =============================================================================
# Joint State Messages
# =============================================================================

@dataclass
class JointStateMessage:
    """Joint state message for real-time position data."""
    timestamp_ns: int
    sequence: int
    positions: list[float]  # 6 joint positions
    flags: int

    def to_bytes(self) -> bytes:
        """Serialize to binary format."""
        if len(self.positions) != 6:
            raise ValueError(f"Expected 6 positions, got {len(self.positions)}")
        return struct.pack(
            JOINT_MSG_FORMAT,
            self.timestamp_ns,
            self.sequence,
            *self.positions,
            self.flags
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'JointStateMessage':
        """Deserialize from binary format."""
        if len(data) != JOINT_MSG_SIZE:
            raise ValueError(f"Expected {JOINT_MSG_SIZE} bytes, got {len(data)}")
        unpacked = struct.unpack(JOINT_MSG_FORMAT, data)
        return cls(
            timestamp_ns=unpacked[0],
            sequence=unpacked[1],
            positions=list(unpacked[2:8]),
            flags=unpacked[8]
        )

    @classmethod
    def create(cls, positions: list[float], sequence: int,
               flags: int = JointFlags.NORMALIZED | JointFlags.DEGREES_MODE | JointFlags.CALIBRATED
              ) -> 'JointStateMessage':
        """Create a new joint state message with current timestamp."""
        return cls(
            timestamp_ns=time.time_ns(),
            sequence=sequence,
            positions=positions,
            flags=flags
        )

    def get_latency_ms(self) -> float:
        """Calculate latency from message timestamp to now."""
        return (time.time_ns() - self.timestamp_ns) / 1_000_000


# =============================================================================
# Heartbeat Messages
# =============================================================================

@dataclass
class HeartbeatMessage:
    """Heartbeat message for connection monitoring."""
    timestamp_ns: int
    sequence: int
    state: SystemState
    fps_x10: int  # FPS * 10 (e.g., 300 = 30.0 fps)
    latency_us: int

    def to_bytes(self) -> bytes:
        """Serialize to binary format."""
        return struct.pack(
            HEARTBEAT_MSG_FORMAT,
            self.timestamp_ns,
            self.sequence,
            int(self.state),
            self.fps_x10,
            self.latency_us
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'HeartbeatMessage':
        """Deserialize from binary format."""
        if len(data) != HEARTBEAT_MSG_SIZE:
            raise ValueError(f"Expected {HEARTBEAT_MSG_SIZE} bytes, got {len(data)}")
        unpacked = struct.unpack(HEARTBEAT_MSG_FORMAT, data)
        return cls(
            timestamp_ns=unpacked[0],
            sequence=unpacked[1],
            state=SystemState(unpacked[2]),
            fps_x10=unpacked[3],
            latency_us=unpacked[4]
        )

    @classmethod
    def create(cls, sequence: int, state: SystemState,
               fps: float = 30.0, latency_us: int = 0) -> 'HeartbeatMessage':
        """Create a new heartbeat message with current timestamp."""
        return cls(
            timestamp_ns=time.time_ns(),
            sequence=sequence,
            state=state,
            fps_x10=int(fps * 10),
            latency_us=latency_us
        )

    @property
    def fps(self) -> float:
        """Get FPS as float."""
        return self.fps_x10 / 10.0


# =============================================================================
# Calibration Messages (JSON)
# =============================================================================

@dataclass
class MotorCalibrationInfo:
    """Calibration info for a single motor."""
    id: int
    drive_mode: int
    homing_offset: int
    range_min: int
    range_max: int
    norm_mode: str  # "degrees" or "range_0_100"


@dataclass
class CalibrationMessage:
    """Calibration message for exchanging calibration data."""
    version: str
    timestamp_ns: int
    arm_name: str
    arm_role: str  # "leader" or "follower"
    motors: dict[str, MotorCalibrationInfo]

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "version": self.version,
            "timestamp_ns": self.timestamp_ns,
            "arm_name": self.arm_name,
            "arm_role": self.arm_role,
            "motors": {
                name: asdict(motor) for name, motor in self.motors.items()
            }
        }
        return json.dumps(data)

    def to_bytes(self) -> bytes:
        """Serialize to bytes (JSON encoded as UTF-8)."""
        return self.to_json().encode('utf-8')

    @classmethod
    def from_json(cls, json_str: str) -> 'CalibrationMessage':
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        motors = {
            name: MotorCalibrationInfo(**motor_data)
            for name, motor_data in data["motors"].items()
        }
        return cls(
            version=data["version"],
            timestamp_ns=data["timestamp_ns"],
            arm_name=data["arm_name"],
            arm_role=data["arm_role"],
            motors=motors
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CalibrationMessage':
        """Deserialize from bytes (JSON decoded from UTF-8)."""
        return cls.from_json(data.decode('utf-8'))


# =============================================================================
# Handshake Messages (JSON)
# =============================================================================

@dataclass
class HandshakeRequest:
    """Handshake request message."""
    version: str
    timestamp_ns: int
    sender: str  # "leader" or "follower"
    sender_ip: str
    capabilities: dict

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps({
            "type": "request",
            "version": self.version,
            "timestamp_ns": self.timestamp_ns,
            "sender": self.sender,
            "sender_ip": self.sender_ip,
            "capabilities": self.capabilities
        })

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        return self.to_json().encode('utf-8')

    @classmethod
    def from_json(cls, json_str: str) -> 'HandshakeRequest':
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(
            version=data["version"],
            timestamp_ns=data["timestamp_ns"],
            sender=data["sender"],
            sender_ip=data.get("sender_ip", "unknown"),
            capabilities=data.get("capabilities", {})
        )


@dataclass
class HandshakeResponse:
    """Handshake response message."""
    version: str
    timestamp_ns: int
    responder: str  # "leader" or "follower"
    status: str  # "accepted", "rejected"
    calibration_check: dict

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps({
            "type": "response",
            "version": self.version,
            "timestamp_ns": self.timestamp_ns,
            "responder": self.responder,
            "status": self.status,
            "calibration_check": self.calibration_check
        })

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        return self.to_json().encode('utf-8')


# =============================================================================
# Validation Utilities
# =============================================================================

def validate_calibration_compatibility(
    leader_cal: CalibrationMessage,
    follower_cal: CalibrationMessage
) -> dict:
    """
    Validate that leader and follower calibrations are compatible.

    Returns:
        dict with keys: valid, warnings, errors
    """
    result = {"valid": True, "warnings": [], "errors": []}

    # Rule 1: Same motor count
    if len(leader_cal.motors) != len(follower_cal.motors):
        result["valid"] = False
        result["errors"].append(
            f"Motor count mismatch: leader={len(leader_cal.motors)}, "
            f"follower={len(follower_cal.motors)}"
        )
        return result

    # Rule 2: Same motor names in same order
    leader_names = list(leader_cal.motors.keys())
    follower_names = list(follower_cal.motors.keys())
    if leader_names != follower_names:
        result["valid"] = False
        result["errors"].append(
            f"Motor name mismatch: leader={leader_names}, follower={follower_names}"
        )
        return result

    # Rule 3: Same normalization modes
    for motor_name in leader_names:
        leader_mode = leader_cal.motors[motor_name].norm_mode
        follower_mode = follower_cal.motors[motor_name].norm_mode
        if leader_mode != follower_mode:
            result["valid"] = False
            result["errors"].append(
                f"Norm mode mismatch for {motor_name}: "
                f"leader={leader_mode}, follower={follower_mode}"
            )

    # Rule 4: Range compatibility warning (not error)
    for motor_name in leader_names:
        l_min = leader_cal.motors[motor_name].range_min
        l_max = leader_cal.motors[motor_name].range_max
        f_min = follower_cal.motors[motor_name].range_min
        f_max = follower_cal.motors[motor_name].range_max

        l_range = l_max - l_min
        f_range = f_max - f_min
        if max(l_range, f_range) > 0:
            range_diff_pct = abs(l_range - f_range) / max(l_range, f_range) * 100

            if range_diff_pct > 20:  # >20% difference
                result["warnings"].append(
                    f"Large range difference for {motor_name}: "
                    f"leader={l_range}, follower={f_range} ({range_diff_pct:.1f}% diff)"
                )

    return result


# =============================================================================
# Topic Names
# =============================================================================

def get_topic_names(system_id: str = "so101") -> dict[str, str]:
    """
    Get all Zenoh topic names for a given system ID.

    Args:
        system_id: System identifier (default: "so101")

    Returns:
        Dictionary of topic names
    """
    base = f"dorobot/{system_id}"
    return {
        # Leader topics
        "leader_joint": f"{base}/leader/joint",
        "leader_calibration": f"{base}/leader/calibration",
        "leader_heartbeat": f"{base}/leader/heartbeat",

        # Follower topics
        "follower_joint": f"{base}/follower/joint",
        "follower_calibration": f"{base}/follower/calibration",
        "follower_heartbeat": f"{base}/follower/heartbeat",

        # System topics
        "handshake": f"{base}/system/handshake",
    }
