# Edge Upload Design (CLOUD_OFFLOAD=2)

## Overview

Edge Upload is a data collection mode where raw images are transferred to a local API server (edge server) for encoding, instead of encoding locally on the client or uploading directly to the cloud.

This mode provides significant time savings for edge devices (like Orange Pi) where:
- Local NPU/CPU encoding is slow
- WAN upload of raw images to cloud is slow
- A local API server with better CPU is available on the same LAN

## Architecture

```
┌─────────────────┐     rsync (LAN)      ┌─────────────────┐     SFTP (WAN)      ┌─────────────────┐
│   Client        │ ──────────────────>  │   Edge Server   │ ──────────────────> │   Cloud Server  │
│   (Orange Pi)   │      ~6 sec          │   (API Server)  │      ~30 sec        │   (Training)    │
│                 │                      │                 │                      │                 │
│  - Capture      │                      │  - Receive      │                      │  - Train model  │
│  - Save PNG     │                      │  - Encode MP4   │                      │  - Save model   │
│  - rsync        │                      │  - Upload       │                      │                 │
└─────────────────┘                      └─────────────────┘                      └─────────────────┘
        │                                        │
        │ Continue recording                     │ Background processing
        │ immediately                            │ (encode + upload)
        v                                        v
   Next episode                           Cloud training starts
```

## Time Comparison

### Typical Episode Data
| Metric | Value |
|--------|-------|
| Frame rate | 30 FPS |
| Episode duration | ~30 seconds |
| Cameras | 2 |
| Frames per episode | 1800 |
| PNG size | ~400 KB |
| Raw images/episode | ~720 MB |
| Encoded video/episode | ~50 MB |

### Transfer Time Comparison (720 MB per episode)

| Mode | Destination | Speed | Time | Client Wait |
|------|-------------|-------|------|-------------|
| CLOUD_OFFLOAD=0 | Local encode | NPU | ~2-5 min | Blocked |
| CLOUD_OFFLOAD=1 | Cloud (WAN) | ~20 Mbps | ~5 min | Blocked |
| **CLOUD_OFFLOAD=2** | **Edge (LAN)** | **~1 Gbps** | **~6 sec** | **Minimal** |

### Total Time Savings
- Per episode: ~5 minutes → ~6 seconds (50x faster)
- 10 episodes: ~50 minutes → ~1 minute saved in client wait time

## CLOUD_OFFLOAD Modes

| Value | Mode | Description |
|-------|------|-------------|
| 0 | Local | Encode locally (NPU/CPU), upload videos to cloud |
| 1 | Cloud | Skip encoding, upload raw images directly to cloud |
| 2 | Edge | Skip encoding, rsync to edge server, edge encodes + uploads |

## Implementation

### Client Side (DoRobot)

#### Environment Variables
```bash
CLOUD_OFFLOAD=2                    # Enable edge upload mode
EDGE_SERVER_HOST=192.168.1.100     # Edge server IP (same LAN)
EDGE_SERVER_USER=dorobot           # SSH user on edge server
EDGE_SERVER_PATH=/data/uploads     # Upload directory on edge server
```

#### Flow
1. Record episode, save raw PNG images (skip encoding)
2. On episode save, rsync images to edge server
3. Continue recording next episode immediately
4. Edge server handles encoding + cloud upload in background

#### rsync Command
```bash
rsync -avz --progress \
  ~/DoRobot/dataset/{repo_id}/ \
  {user}@{host}:{path}/{repo_id}/
```

### Edge Server Side (data-platform)

#### Components
1. **rsync daemon** or SSH access for receiving uploads
2. **Watcher service** - monitors upload directory for new data
3. **Encoder service** - runs `encode_dataset.py` on new episodes
4. **Uploader service** - uploads encoded videos to cloud

#### Flow
1. Receive dataset via rsync from client
2. Detect new episode (watch for new image directories)
3. Run `encode_dataset.py` to encode images to MP4
4. Upload encoded dataset to cloud via SFTP
5. Trigger training on cloud (existing workflow)

#### API Endpoints
```
POST /edge/upload-complete
  - Client notifies edge server that upload is complete
  - Triggers encoding + cloud upload

GET /edge/status/{repo_id}
  - Check encoding/upload progress

POST /edge/train/{repo_id}
  - Trigger cloud training after encoding complete
```

### Cloud Server Side

No changes required - receives encoded videos via existing SFTP workflow.

## Configuration

### Client (~/.dorobot_edge.conf)
```bash
# Edge server configuration
EDGE_SERVER_HOST="192.168.1.100"
EDGE_SERVER_USER="dorobot"
EDGE_SERVER_PORT="22"
EDGE_SERVER_PATH="/data/dorobot/uploads"

# Optional: SSH key for passwordless rsync
EDGE_SERVER_KEY="~/.ssh/dorobot_edge"
```

### Edge Server
```bash
# Upload directory (must be writable)
EDGE_UPLOAD_DIR=/data/dorobot/uploads

# Encoding settings
EDGE_ENCODE_PRESET=fast       # ffmpeg preset
EDGE_ENCODE_CRF=23            # quality (lower=better)

# Cloud connection (existing config)
DOROBOT_API_URL=http://cloud-server:8000
DOROBOT_USERNAME=user
DOROBOT_PASSWORD=pass
```

## Error Handling

### Client Side
- rsync failure: Retry up to 3 times with exponential backoff
- Network timeout: Fall back to CLOUD_OFFLOAD=1 (direct cloud upload)
- Edge server unavailable: Warn user, continue with local storage

### Edge Server Side
- Encoding failure: Retry episode, mark as failed after 3 attempts
- Cloud upload failure: Queue for retry, continue with other episodes
- Disk space: Alert when upload directory exceeds threshold

## Security

- SSH key authentication preferred over password
- Edge server should be on same LAN (not exposed to internet)
- Upload directory isolated from other services
- Rate limiting on API endpoints

## Monitoring

### Client
- Display rsync progress during upload
- Show "Uploading to edge server..." status
- Log transfer speed and time

### Edge Server
- Dashboard showing:
  - Pending episodes to encode
  - Encoding progress
  - Upload queue to cloud
  - Training status

## Future Enhancements

1. **Parallel encoding** - Encode multiple episodes simultaneously
2. **Incremental sync** - Only sync changed files
3. **Compression** - Compress images before rsync (if CPU-bound)
4. **Multi-client** - Handle multiple clients uploading simultaneously
5. **Auto-discovery** - Client auto-discovers edge server on LAN
