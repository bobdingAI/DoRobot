# SO101 Remote Leader System

This is a standalone leader arm system for distributed SO101 teleoperation.
It runs on a separate PC from the follower and communicates via Zenoh over LAN.

## Quick Start

### 1. Install Dependencies

```bash
cd remote_leader
pip install -r requirements.txt
```

### 2. Connect the Leader Arm

Connect the SO101 leader arm to the PC via USB. The arm should appear as `/dev/ttyACM0` or similar.

### 3. Calibrate (First Time Only)

If you don't have a calibration file, copy one from the main DoRobot system or run calibration:

```bash
# Copy calibration from DoRobot
cp /path/to/DoRobot/operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json .calibration/
```

### 4. Run the Leader

```bash
# Auto-detect port and use default settings
python leader_main.py

# Or with explicit configuration
ARM_LEADER_PORT=/dev/ttyACM0 python leader_main.py
```

### 5. Connect the Follower

On the follower PC, set the environment variable to connect to the leader:

```bash
ZENOH_LEADER_ENDPOINT=tcp://<leader-ip>:7447 bash scripts/run_so101.sh
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOROBOT_SYSTEM_ID` | `so101` | System identifier for Zenoh topics |
| `ARM_LEADER_PORT` | auto-detect | Serial port for leader arm |
| `ARM_NAME` | `SO101-leader` | Arm name (matches calibration file) |
| `CALIBRATION_DIR` | `./.calibration/` | Directory containing calibration files |
| `ZENOH_LISTEN` | `tcp/0.0.0.0:7447` | Zenoh listen endpoint |
| `ZENOH_CONNECT` | (none) | Optional: Zenoh connect endpoint |
| `PUBLISH_RATE_HZ` | `30` | Joint publishing rate in Hz |

### Command Line Arguments

```bash
python leader_main.py --help

Options:
  --port, -p        Serial port for leader arm
  --calibration, -c Path to calibration file
  --zenoh-listen    Zenoh listen endpoint
  --zenoh-connect   Zenoh connect endpoint
  --rate, -r        Publishing rate in Hz
  --system-id       System identifier
```

## Network Architecture

```
┌─────────────────────┐                    ┌─────────────────────┐
│   Leader PC         │                    │   Follower PC       │
│                     │                    │                     │
│  ┌───────────────┐  │                    │  ┌───────────────┐  │
│  │ Leader Arm    │  │                    │  │ Follower Arm  │  │
│  │ (passive)     │  │                    │  │ (active)      │  │
│  └───────┬───────┘  │                    │  └───────┬───────┘  │
│          │          │                    │          │          │
│  ┌───────▼───────┐  │    Zenoh LAN      │  ┌───────▼───────┐  │
│  │ leader_main   │──┼──────────────────►│  │ manipulator   │  │
│  │ (publisher)   │  │  Joint Positions  │  │ (subscriber)  │  │
│  └───────────────┘  │                    │  └───────────────┘  │
│                     │                    │                     │
│  tcp/0.0.0.0:7447   │                    │  Cameras + DORA     │
└─────────────────────┘                    └─────────────────────┘
```

## Zenoh Topics

| Topic | Publisher | Rate | Description |
|-------|-----------|------|-------------|
| `dorobot/so101/leader/joint` | Leader | 30Hz | Normalized joint positions (37 bytes) |
| `dorobot/so101/leader/calibration` | Leader | On startup | Calibration JSON |
| `dorobot/so101/leader/heartbeat` | Leader | 1Hz | Connection status (19 bytes) |

## Message Format

### Joint State (Binary, 37 bytes)

```
┌──────────────┬──────────┬───────┐
│ Field        │ Type     │ Bytes │
├──────────────┼──────────┼───────┤
│ timestamp_ns │ uint64   │ 8     │
│ sequence     │ uint32   │ 4     │
│ positions[6] │ float32  │ 24    │
│ flags        │ uint8    │ 1     │
└──────────────┴──────────┴───────┘

Struct format: <QI6fB (little-endian)

Positions order:
  0: shoulder_pan (degrees)
  1: shoulder_lift (degrees)
  2: elbow_flex (degrees)
  3: wrist_flex (degrees)
  4: wrist_roll (degrees)
  5: gripper (0-100%)
```

## Troubleshooting

### "Could not find arm port"

- Check that the arm is connected via USB
- Run `ls /dev/ttyACM*` or `ls /dev/ttyUSB*` to find the port
- Specify the port with `--port` or `ARM_LEADER_PORT`

### "Calibration file not found"

- Copy the calibration file from the main DoRobot installation
- Or specify the path with `--calibration`

### "Failed to connect to Zenoh"

- Check that the port 7447 is not in use
- Try a different port: `--zenoh-listen tcp/0.0.0.0:7448`

### Follower not receiving data

- Check network connectivity between PCs
- Ensure the firewall allows UDP/TCP on port 7447
- Try disabling multicast: set `enable_multicast=False` in code

## Files

```
remote_leader/
├── leader_main.py      # Main entry point
├── arm_driver.py       # Arm hardware interface
├── zenoh_publisher.py  # Zenoh publishing logic
├── messages.py         # Message serialization
├── requirements.txt    # Python dependencies
├── README.md           # This file
├── .calibration/       # Calibration files
│   └── SO101-leader.json
└── motors/             # Motor driver library
    ├── __init__.py
    ├── motors_bus.py
    ├── feetech/
    │   ├── __init__.py
    │   ├── feetech.py
    │   └── tables.py
    └── utils/
        ├── __init__.py
        ├── utils.py
        └── encoding_utils.py
```
