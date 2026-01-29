# Distributed SO101 Teleoperation via Zenoh

This document describes the distributed teleoperation architecture where the leader arm runs on a separate PC from the follower arm, communicating via Zenoh over LAN.

## Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Distributed Teleoperation                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────┐          Zenoh LAN           ┌─────────────────────┐
│   │   Leader PC (PC1)   │                              │  Follower PC (PC2)  │
│   │                     │                              │                     │
│   │  ┌───────────────┐  │                              │  ┌───────────────┐  │
│   │  │ Leader Arm    │  │                              │  │ Follower Arm  │  │
│   │  │ (passive)     │  │                              │  │ (active)      │  │
│   │  └───────┬───────┘  │                              │  └───────┬───────┘  │
│   │          │ Serial   │                              │          │ Serial   │
│   │  ┌───────▼───────┐  │    Joint Positions (30Hz)   │  ┌───────▼───────┐  │
│   │  │ leader_main   │──┼─────────────────────────────►│  │ manipulator   │  │
│   │  │ (publisher)   │  │                              │  │ (subscriber)  │  │
│   │  └───────────────┘  │                              │  └───────────────┘  │
│   │                     │                              │          │          │
│   │  tcp/0.0.0.0:7447   │                              │  Cameras + DORA     │
│   └─────────────────────┘                              └─────────────────────┘
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Leader PC (PC1)

```bash
cd remote_leader
pip install -r requirements.txt
python leader_main.py
```

### Follower PC (PC2)

```bash
ZENOH_LEADER_ENDPOINT=tcp://192.168.1.100:7447 bash scripts/run_so101.sh
```

## Zenoh Topic Structure

### Topic Naming Convention

```
dorobot/<system_id>/<component>/<data_type>
```

### Topics

| Topic | Publisher | Subscriber | Rate | Size | Description |
|-------|-----------|------------|------|------|-------------|
| `dorobot/so101/leader/joint` | Leader | Follower | 30Hz | 37B | Normalized joint positions |
| `dorobot/so101/leader/calibration` | Leader | Follower | On startup | ~1KB | Calibration JSON |
| `dorobot/so101/leader/heartbeat` | Leader | Follower | 1Hz | 19B | Connection status |

## Message Formats

### Joint State Message (Binary - 37 bytes)

High-performance binary format for real-time joint data.

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
```

**Positions order:**
- 0: shoulder_pan (degrees)
- 1: shoulder_lift (degrees)
- 2: elbow_flex (degrees)
- 3: wrist_flex (degrees)
- 4: wrist_roll (degrees)
- 5: gripper (0-100%)

**Flags:**
```python
FLAG_NORMALIZED   = 0x01  # Data is normalized
FLAG_DEGREES_MODE = 0x02  # Using degrees normalization
FLAG_CALIBRATED   = 0x04  # System is calibrated
FLAG_EMERGENCY    = 0x80  # Emergency stop active
```

**Sample Python code:**
```python
import struct
import time

# Serialize
msg = struct.pack('<QI6fB',
    int(time.time_ns()),     # timestamp
    42,                       # sequence
    -90.0, 54.5, -150.0,     # shoulder_pan, shoulder_lift, elbow_flex
    -20.0, 30.0, 50.0,       # wrist_flex, wrist_roll, gripper
    0x07                      # flags
)

# Deserialize
data = struct.unpack('<QI6fB', msg)
positions = list(data[2:8])
```

### Calibration Message (JSON)

Sent on startup for validation.

```json
{
  "version": "1.0",
  "timestamp_ns": 1706234567000000000,
  "arm_name": "SO101-leader",
  "arm_role": "leader",
  "motors": {
    "shoulder_pan": {
      "id": 1,
      "drive_mode": 0,
      "homing_offset": 1250,
      "range_min": 1951,
      "range_max": 2335,
      "norm_mode": "degrees"
    },
    ...
  }
}
```

### Heartbeat Message (Binary - 19 bytes)

Connection monitoring at 1Hz.

```
┌──────────────┬──────────┬───────┐
│ Field        │ Type     │ Bytes │
├──────────────┼──────────┼───────┤
│ timestamp_ns │ uint64   │ 8     │
│ sequence     │ uint32   │ 4     │
│ state        │ uint8    │ 1     │
│ fps_x10      │ uint16   │ 2     │
│ latency_us   │ uint32   │ 4     │
└──────────────┴──────────┴───────┘
```

## Calibration in Distributed Environment

### Design Principle

Each machine maintains **independent calibration**. Only **normalized values** (degrees/percentage) are transmitted over the network, making the protocol hardware-agnostic.

```
Leader (PC1)                              Follower (PC2)
┌─────────────────┐                      ┌─────────────────┐
│ Raw encoder     │                      │ Receive normalized│
│ e.g., 2143      │                      │ e.g., -45.0°     │
│       ↓         │                      │       ↓          │
│ Normalize using │                      │ Denormalize using│
│ leader calib    │                      │ follower calib   │
│       ↓         │                      │       ↓          │
│ -45.0° ─────────┼──── Zenoh LAN ──────→│ Raw encoder      │
│                 │                      │ e.g., 1876       │
└─────────────────┘                      └─────────────────┘
```

### Calibration Files

- **Leader PC:** `remote_leader/.calibration/SO101-leader.json`
- **Follower PC:** Uses existing calibration in `operating_platform/.../SO101-follower.json`

### Calibration Procedure

Calibrate each arm independently on its own machine:

```bash
# On Leader PC
cd remote_leader
python -m calibrate --arm leader --port /dev/ttyACM0

# On Follower PC (using existing DoRobot calibration)
bash scripts/calibrate_so101.sh
```

## Configuration

### Environment Variables

**Leader (PC1):**
| Variable | Default | Description |
|----------|---------|-------------|
| `DOROBOT_SYSTEM_ID` | `so101` | System identifier for Zenoh topics |
| `ARM_LEADER_PORT` | auto-detect | Serial port for leader arm |
| `ARM_NAME` | `SO101-leader` | Arm name (matches calibration file) |
| `CALIBRATION_DIR` | `./.calibration/` | Calibration directory |
| `ZENOH_LISTEN` | `tcp/0.0.0.0:7447` | Zenoh listen endpoint |
| `PUBLISH_RATE_HZ` | `30` | Joint publishing rate |

**Follower (PC2):**
| Variable | Default | Description |
|----------|---------|-------------|
| `ZENOH_LEADER_ENDPOINT` | (none) | Set to enable distributed mode |
| `DOROBOT_SYSTEM_ID` | `so101` | Must match leader |

### Command Line Arguments (Leader)

```bash
python leader_main.py --help

Options:
  --port, -p        Serial port for leader arm
  --calibration, -c Path to calibration file
  --zenoh-listen    Zenoh listen endpoint
  --rate, -r        Publishing rate in Hz
  --system-id       System identifier
```

## Error Handling

### Connection Loss Detection

- **Heartbeat timeout:** 3 seconds without heartbeat = disconnected
- **Joint data timeout:** 200ms without joint data = stale

### Follower Safety Behavior

On leader disconnect:
1. Log warning
2. Hold last known position (data becomes stale)
3. Automatically resume when leader reconnects

### Latency Monitoring

Latency is calculated from message timestamp:
```python
latency_ms = (time.time_ns() - msg.timestamp_ns) / 1_000_000
if latency_ms > 100:
    log.warning(f"High latency: {latency_ms:.1f}ms")
```

## Network Requirements

- **Bandwidth:** ~27 KB/s per arm (37 bytes × 30 Hz × 2 directions)
- **Latency:** <50ms recommended for smooth teleoperation
- **Protocol:** TCP or UDP (Zenoh handles automatically)
- **Port:** 7447 (default Zenoh port)

### Firewall Configuration

Ensure port 7447 is open for TCP/UDP:
```bash
# Linux (ufw)
sudo ufw allow 7447/tcp
sudo ufw allow 7447/udp

# Or disable firewall for testing
sudo ufw disable
```

## File Structure

### Leader System (`remote_leader/`)

```
remote_leader/
├── leader_main.py          # Main entry point
├── zenoh_publisher.py      # Zenoh publishing logic
├── arm_driver.py           # Feetech motor interface
├── messages.py             # Message serialization
├── requirements.txt        # Python dependencies
├── README.md               # Leader-specific docs
├── .calibration/
│   └── SO101-leader.json   # Leader calibration
└── motors/                 # Motor driver library
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

### Follower Modifications

Modified files in `operating_platform/`:
- `robot/robots/so101_v1/manipulator.py` - Added `ZenohLeaderSubscriber`
- `robot/robots/so101_v1/zenoh_messages.py` - Message protocol definitions

## Troubleshooting

### "Could not find arm port"

```bash
# Check connected devices
ls /dev/ttyACM* /dev/ttyUSB*

# Specify port explicitly
ARM_LEADER_PORT=/dev/ttyACM0 python leader_main.py
```

### "Calibration file not found"

```bash
# Copy from DoRobot installation
cp /path/to/DoRobot/.../SO101-leader.json remote_leader/.calibration/
```

### "Failed to connect to Zenoh"

```bash
# Check if port is in use
netstat -tuln | grep 7447

# Try different port
python leader_main.py --zenoh-listen tcp/0.0.0.0:7448
```

### Follower Not Receiving Data

1. Check network connectivity: `ping <leader-ip>`
2. Verify firewall settings
3. Check Zenoh endpoint format: `tcp://192.168.1.100:7447`
4. Try disabling multicast (in code set `enable_multicast=False`)

### High Latency

- Check network congestion
- Reduce publishing rate: `--rate 20`
- Use wired connection instead of WiFi
