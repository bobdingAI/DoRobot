# Anything-U-Arm DORA Component

This component provides a DORA node for the Anything-U-Arm (6-DOF version) based on Feetech STS3215 servos.

## Configuration

- `PORT`: Serial port path (default: `/dev/ttyUSB0`)
- `ARM_NAME`: Identifier for the arm (default: `UArm-Leader`)
- `ARM_ROLE`: Role of the arm (`leader` or `follower`, default: `leader`)
- `CALIBRATION_DIR`: Directory where calibration JSON files are stored.

## Inputs

- `get_joint`: Timer tick to trigger joint state reading.

## Outputs

- `joint`: Current joint positions [j1, j2, j3, j4, j5, j6, gripper] in degrees/radians.

