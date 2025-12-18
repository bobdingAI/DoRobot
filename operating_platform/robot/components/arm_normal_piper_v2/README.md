# Agilex Piper Robot Arm DORA Node

This DORA node provides control interface for the Agilex Piper 6-DOF collaborative robot arm via CAN bus communication.

## Dependencies

```bash
pip install piper_sdk>=0.0.8
```

**External SDK**: https://github.com/agilexrobotics/piper_sdk

## Pre-requisite Steps for Piper

### 1. Hardware Setup

```bash
# 1. Power on Piper arm first
# 2. Connect CAN USB adapter to computer
# 3. Connect CAN cable to Piper arm
```

### 2. CAN Bus Configuration (Required)

```bash
# Setup CAN interface (run as root)
sudo ip link set can_left type can bitrate 1000000
sudo ip link set can_left up

# Verify CAN is up
ip link show can_left
# Should show: can_left: <NOARP,UP,LOWER_UP>
```

For dual-arm setup:
```bash
sudo ip link set can_right type can bitrate 1000000
sudo ip link set can_right up
```

### 3. Verify CAN Interface

```bash
# List available CAN interfaces
ip link show type can

# Check CAN statistics
ip -details -statistics link show can_left
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `CAN_BUS` | CAN interface name | `can_left`, `can_right`, `can0` |

## DORA Node Interface

### Inputs

| ID | Type | Description |
|----|------|-------------|
| `tick` | Timer | Polling interval (33ms = 30Hz) |
| `action_joint` | float32[7] | Joint positions (rad) + gripper (m) |
| `action_joint_ctrl` | float32[7] | Joint control from inference (rad) + gripper (m) |
| `action_endpose` | float32[6] | Cartesian pose (m, rad) |
| `action_gripper` | float32[1] | Gripper position (m) |

### Outputs

| ID | Type | Description |
|----|------|-------------|
| `slave_jointstate` | float32[7] | Current joint positions + gripper |
| `slave_endpose` | float32[6] | Current end effector pose |
| `master_jointstate` | float32[7] | Master arm joint positions (teach mode) |

## Unit Conversions

```python
# Joint angles: SDK uses 0.001 degrees, we use radians
factor = 1000 * 180 / np.pi

# Joint position (radians) to SDK units:
sdk_joint = round(position_rad * factor)

# Gripper: SDK uses 0.001mm units, we use meters
gripper_sdk = int(abs(gripper_m * 1000 * 1000))
```

## Teleoperation with Anything-U-Arm

For using Piper as follower with Anything-U-Arm as leader:

### 1. Connect UArm Leader

```bash
# Connect Anything-U-Arm via USB (default /dev/ttyUSB0)
ls -la /dev/ttyUSB*
```

### 2. Configure Environment Variables

```bash
export ARM_LEADER_PORT="/dev/ttyUSB0"     # UArm serial port
export ARM_FOLLOWER_CAN="can_left"         # Piper CAN interface
export SERVO_TYPE="zhonglin"               # or "feetech"
export CAMERA_TOP_PATH="0"                 # Top camera index
export CAMERA_WRIST_PATH="1"               # Wrist camera index
```

### 3. Run Teleoperation

```bash
cd /path/to/DoRobot
bash scripts/run_piper_uarm.sh REPO_ID=my-dataset SINGLE_TASK="testing"
```

### Troubleshooting

1. **CAN interface name mismatch**: If your CAN adapter creates a different interface (e.g., `can0`):
   ```bash
   ARM_FOLLOWER_CAN=can0 bash scripts/run_piper_uarm.sh
   ```

2. **Piper enable timeout**: The arm has a 0.05s auto-enable timeout. If it fails, check CAN connection.

3. **UArm software zeroing**: Keep the UArm still for 1 second during initialization (records zero position).

## Dataflow Example

```yaml
- id: arm_piper_follower
  path: ../../components/arm_normal_piper_v2/main.py
  inputs:
    tick: dora/timer/millis/33
    action_joint: arm_uarm_leader/joint
  outputs:
    - slave_jointstate
  env:
    CAN_BUS: can_left
```

## Documentation

See `docs/piper.md` for complete integration documentation.
