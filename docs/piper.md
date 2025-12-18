# Agilex Piper Robot Arm Integration

This document describes the Piper robot arm component integration in DoRobot.

## Overview

The **Agilex Piper** is a 6-DOF collaborative robot arm with a gripper. The `arm_normal_piper_v2` component provides a DORA node for controlling Piper arms via CAN bus communication.

## Status: Production Ready (100% Complete)

| Feature | Status | Notes |
|---------|--------|-------|
| DORA Node | ✅ Complete | `arm_normal_piper_v2/main.py` |
| Joint Control | ✅ Complete | 6 joints + gripper |
| End Pose Control | ✅ Complete | Cartesian XYZ + RPY |
| Joint State Reading | ✅ Complete | Master and slave modes |
| Gripper Control | ✅ Complete | Position and speed |
| Robot Config | ✅ Complete | `PiperV1RobotConfig` in `configs.py` |
| Dataflow YAML | ✅ Complete | `robots/piper_v1/dora_teleoperate_dataflow.yml` |
| Manipulator Bridge | ✅ Complete | `robots/piper_v1/manipulator.py` |
| Main CLI Integration | ✅ Complete | Integrated into `robots/utils.py` |
| Launcher Script | ✅ Complete | `scripts/run_piper.sh` |
| Documentation | ✅ Complete | Updated this file |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DORA Dataflow                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    CAN Bus    ┌──────────────────────┐   │
│  │  piper_left  │◄─────────────►│  Left Piper Arm      │   │
│  │  (main.py)   │   can_left    │  (Physical Hardware) │   │
│  └──────────────┘               └──────────────────────┘   │
│         │                                                   │
│         ▼                                                   │
│  Outputs: slave_jointstate, slave_endpose,                 │
│           master_jointstate                                 │
│                                                             │
│  ┌──────────────┐    CAN Bus    ┌──────────────────────┐   │
│  │  piper_right │◄─────────────►│  Right Piper Arm     │   │
│  │  (main.py)   │   can_right   │  (Physical Hardware) │   │
│  └──────────────┘               └──────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## Component Location

```
operating_platform/robot/components/arm_normal_piper_v2/
├── main.py           # DORA node implementation
├── pyproject.toml    # Package definition (dr-arm-piper v0.3.12)
├── README.md         # Basic setup instructions
└── test_arm.yml      # Test dataflow configuration
```

## Dependencies

```toml
# pyproject.toml
dependencies = [
  "dora-rs >= 0.3.9",
  "piper_sdk >= 0.0.8"
]
```

**External SDK**: https://github.com/agilexrobotics/piper_sdk

## Hardware Setup

### CAN Bus Configuration

The Piper arm communicates via CAN bus. Setup CAN interfaces before use:

```bash
# Setup CAN interfaces (run as root or with sudo)
sudo ip link set can_left type can bitrate 1000000
sudo ip link set can_left up

sudo ip link set can_right type can bitrate 1000000
sudo ip link set can_right up
```

### Connection Order

1. Power on Piper arms
2. Connect CAN cables
3. Configure CAN interfaces
4. Run DORA dataflow

## DORA Node Interface

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CAN_BUS` | CAN interface name | `can_left`, `can_right` |

### Inputs

| ID | Type | Description |
|----|------|-------------|
| `tick` | Timer | Polling interval (33ms = 30Hz) |
| `action_joint` | float32[7] | Joint positions (rad) + gripper |
| `action_endpose` | float32[6] | Cartesian pose (m, rad) |
| `action_gripper` | float32[1] | Gripper position |

### Outputs

| ID | Type | Description |
|----|------|-------------|
| `slave_jointstate` | float32[7] | Current joint positions + gripper |
| `slave_endpose` | float32[6] | Current end effector pose |
| `master_jointstate` | float32[7] | Master arm joint positions (teach mode) |

## Unit Conversions

The code uses specific conversion factors:

```python
# Joint angles: SDK uses internal units (0.001 degrees), we use radians
factor = 1000 * 180 / np.pi

# Joint position (radians) to SDK units:
sdk_joint = round(position_rad * factor)

# SDK units to radians:
position_rad = sdk_joint / factor

# Gripper: SDK uses 0.001mm units, we use meters
gripper_sdk = int(abs(gripper_m * 1000 * 1000))

# End pose position: SDK uses 0.001mm, we use meters
pose_sdk = position_m * 1000 * 1000

# End pose rotation: SDK uses 0.001 degrees, we use radians
rotation_sdk = rotation_rad * 1000 / (2 * np.pi) * 360
```

## Configuration in DoRobot

The Piper arm is configured in `operating_platform/robot/robots/configs.py`:

```python
# Motor configuration for dual-arm setup
right_leader_arm = PiperMotorsBusConfig(
    port="can_right",
    motors={
        "joint_1": [1,  "piper-motor"],
        "joint_2": [2,  "piper-motor"],
        "joint_3": [3,  "piper-motor"],
        "joint_4": [4,  "piper-motor"],
        "joint_5": [5,  "piper-motor"],
        "joint_6": [6,  "piper-motor"],
        "pose_x":  [7,  "piper-pose"],
        "pose_y":  [8,  "piper-pose"],
        "pose_z":  [9,  "piper-pose"],
        "pose_rx": [10, "piper-pose"],
        "pose_ry": [11, "piper-pose"],
        "pose_rz": [12, "piper-pose"],
        "gripper": [13, "piper-gripper"],
    },
)

left_leader_arm = PiperMotorsBusConfig(
    port="can_left",
    motors={...}  # Same structure
)
```

## Test Files

Test configurations are available in `test/piper/`:

| File | Purpose |
|------|---------|
| `arms_only.yml` | Basic arm control with Rerun visualization |
| `arms_only_web.yml` | Web-based visualization |
| `record.yml` | Data recording setup |
| `piper.py` | Test DORA node (similar to main.py) |
| `arm_ctrl.py` | Direct SDK control test |
| `print_joint.py` | Joint state printer node |

### Running Test

```bash
cd test/piper
dora up
dora start arms_only.yml
```

## Production Integration (`piper_v1`)

The production-ready integration is located in `operating_platform/robot/robots/piper_v1/`. This integration uses ZeroMQ to bridge DORA data to the main DoRobot CLI.

### Components

1.  **`dora_teleoperate_dataflow.yml`**: The main DORA dataflow for teleoperation.
2.  **`dora_zeromq.py`**: A ZeroMQ bridge node that runs within the DORA dataflow.
3.  **`manipulator.py`**: The Python interface that implements the `Robot` protocol.
4.  **`scripts/run_piper.sh`**: A unified launcher script.

### Configuration

The Piper robot is configured in `operating_platform/robot/robots/configs.py` as `PiperV1RobotConfig`.

### Usage

To start a teleoperation and recording session with Piper using a native Piper master arm:

```bash
# Set CAN interfaces (if not already up)
sudo ip link set can_left type can bitrate 1000000
sudo ip link set can_left up
sudo ip link set can_right type can bitrate 1000000
sudo ip link set can_right up

# Launch the integrated system
bash scripts/run_piper.sh REPO_ID=my-piper-dataset SINGLE_TASK="testing piper integration"
```

To start teleoperation using the **Anything-U-Arm (6-DOF Leader)**:

```bash
# Set CAN for Piper follower
sudo ip link set can_left type can bitrate 1000000
sudo ip link set can_left up

# Launch with UArm leader
# Ensure UArm is connected via USB (default /dev/ttyUSB0)
bash scripts/run_piper_uarm.sh REPO_ID=my-uarm-piper-dataset SINGLE_TASK="uarm to piper teleop"
```

### Environment Variables for `run_piper_uarm.sh`

| Variable | Default | Description |
|----------|---------|-------------|
| `ARM_LEADER_PORT` | `/dev/ttyUSB0` | Serial port for Anything-U-Arm leader |
| `ARM_FOLLOWER_CAN` | `can_left` | CAN interface for Piper follower arm |
| `CAMERA_TOP_PATH` | `0` | Device path or index for top camera |
| `CAMERA_WRIST_PATH` | `1` | Device path or index for wrist camera |

## API Reference

### Main Functions

```python
def enable_fun(piper: C_PiperInterface):
    """Enable arm motors with 0.05s timeout."""

def main():
    """DORA node main loop handling:
    - tick: Read joint states and end pose
    - action_joint: Send joint position commands
    - action_endpose: Send Cartesian pose commands
    - action_gripper: Send gripper commands
    """
```

### Piper SDK Methods Used

```python
piper = C_PiperInterface(can_bus)
piper.ConnectPort()
piper.EnablePiper()
piper.GetArmEnableStatus()
piper.MotionCtrl_2(mode, ctrl, speed, reserved)
piper.JointCtrl(j1, j2, j3, j4, j5, j6)
piper.EndPoseCtrl(x, y, z, rx, ry, rz)
piper.GripperCtrl(position, speed, force, reserved)
piper.GetArmJointMsgs()      # Slave joint state
piper.GetArmJointCtrl()      # Master joint command
piper.GetArmEndPoseMsgs()    # End pose
piper.GetArmGripperMsgs()    # Gripper state
piper.GetArmGripperCtrl()    # Gripper command
```

## Visualization

The test dataflow includes Rerun visualization with URDF models:

```yaml
# In arms_only.yml - Downloads Piper URDF meshes
build: |
  wget -nc -P urdf/ https://raw.githubusercontent.com/agilexrobotics/Piper_ros/.../base_link.STL
  wget -nc -P urdf/ https://raw.githubusercontent.com/agilexrobotics/Piper_ros/.../link1.STL
  # ... (links 2-8)
```

## Contributing

To complete the Piper integration:

1. Create `robots/piper_v1/` folder structure
2. Implement `manipulator.py` ZeroMQ bridge
3. Create production dataflow YAML
4. Add to CLI robot factory
5. Create launcher script
6. Add unit tests

See `robots/so101_v1/` as a reference implementation.
