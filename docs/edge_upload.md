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
        │                                        │                                        │
        │                                        │                                        │
        │<───────────────────────────────────────│<───────────────────────────────────────│
        │           Poll /edge/status            │        SFTP Model Download             │
        │                                        │        (bypasses edge server)          │
        v                                        v                                        v
   Download model                          Monitor training                         Model ready
   via SFTP                                via cloud API + SSH
```

## Two SSH Credential Sets

**Important**: This workflow uses two separate SSH credential sets:

| Credential Set | Purpose | Who Uses It | When |
|---------------|---------|-------------|------|
| **Edge Server SSH** | Upload raw images from client to edge | DoRobot client | During recording (rsync) |
| **Cloud Server SSH** | 1. Upload encoded video to cloud<br>2. Download trained model | Edge server (upload)<br>DoRobot client (download) | After encoding / After training |

### Edge Server SSH (for image upload)
```bash
# Client config (~/.dorobot_edge.conf)
EDGE_SERVER_HOST="192.168.1.100"      # Edge server on LAN
EDGE_SERVER_USER="dorobot"
EDGE_SERVER_PORT="22"
EDGE_SERVER_PATH="/data/dorobot/uploads"
```

### Cloud Server SSH (for model download)
```bash
# Returned by edge server in /edge/status response
{
  "ssh_host": "cloud-gpu-instance.example.com",
  "ssh_username": "root",
  "ssh_port": 22,
  "ssh_password": "base64_encoded_password"  # Decoded by client
}
```

## Complete Data Flow

### Phase 1: Image Upload (Client → Edge)
```
DoRobot Client                    Edge Server (API)
     │                                  │
     │  rsync raw images (LAN, ~6 sec)  │
     │ ──────────────────────────────>  │
     │                                  │
     │  POST /edge/upload-complete      │
     │  {repo_id, episode_index}        │
     │ ──────────────────────────────>  │
     │                                  │
     │  Response: {status: "encoding"}  │
     │ <──────────────────────────────  │
     │                                  │
     │  (continue recording next        │
     │   episode immediately)           │
```

### Phase 2: Encoding + Cloud Upload (Edge → Cloud)
```
Edge Server                       Cloud Server
     │                                  │
     │  Encode images to MP4            │
     │  (libx264, ~30 sec)              │
     │                                  │
     │  SFTP encoded video (WAN)        │
     │ ──────────────────────────────>  │
     │                                  │
     │  POST /transactions/start        │
     │ ──────────────────────────────>  │
     │                                  │
     │  Response: {transaction_id,      │
     │    ssh_info, model_dir}          │
     │ <──────────────────────────────  │
     │                                  │
     │  (stores cloud SSH credentials   │
     │   for later client download)     │
```

### Phase 3: Training Completion Detection
```
DoRobot Client                    Edge Server                     Cloud Server
     │                                  │                               │
     │  GET /edge/status/{repo_id}      │                               │
     │ ──────────────────────────────>  │                               │
     │                                  │  Method 1: API Status Check   │
     │                                  │  GET /transactions/{id}       │
     │                                  │ ─────────────────────────────>│
     │                                  │                               │
     │                                  │  (if API returns TRAINING,    │
     │                                  │   try fallback...)            │
     │                                  │                               │
     │                                  │  Method 2: SSH Folder Check   │
     │                                  │  ssh test -d {model_path}     │
     │                                  │ ─────────────────────────────>│
     │                                  │                               │
     │                                  │  "MODEL_EXISTS"               │
     │                                  │ <─────────────────────────────│
     │                                  │                               │
     │  Response: {status: "COMPLETED", │                               │
     │    ssh_host, ssh_username,       │                               │
     │    ssh_password, model_path}     │                               │
     │ <──────────────────────────────  │                               │
```

### Phase 4: Model Download (Cloud → Client)
```
DoRobot Client                                         Cloud Server
     │                                                       │
     │  SFTP connect (using cloud SSH credentials)           │
     │ ─────────────────────────────────────────────────────>│
     │                                                       │
     │  Recursive download from:                             │
     │  {model_dir}/train/act_{transaction_id}/              │
     │    checkpoints/last/pretrained_model                  │
     │ <─────────────────────────────────────────────────────│
     │                                                       │
     │  Save to: ~/DoRobot/models/{model_name}/              │
     │                                                       │
```

## Training Completion Detection

The edge server uses two methods to detect training completion:

### Method 1: Cloud API Status Check
```python
# Edge server polls cloud API
response = requests.get(f"{cloud_api_url}/transactions/{transaction_id}")
status = response.json().get("status")  # "TRAINING", "COMPLETED", "FAILED"
```

**Problem**: API status sometimes doesn't update to COMPLETED even when training finishes.

### Method 2: SSH Model Folder Check (Fallback)
```python
# Edge server SSHs into cloud and checks if model folder exists
model_path = f"{model_dir}/train/act_{transaction_id}/checkpoints/last/pretrained_model"
check_cmd = f"test -d '{model_path}' && echo 'MODEL_EXISTS' || echo 'MODEL_NOT_FOUND'"
result = ssh_execute(check_cmd)
if "MODEL_EXISTS" in result:
    status = "COMPLETED"  # Override API status
```

**Path components**:
- `model_dir`: Cloud instance model output directory (e.g., `/root/gpufree-data/admin-data/outputs`)
- `train/act_{transaction_id}`: Training job folder
- `checkpoints/last/pretrained_model`: Final model checkpoint

**Full example**: `/root/gpufree-data/admin-data/outputs/train/act_abc123/checkpoints/last/pretrained_model`

## How DoRobot Gets Download Information

### Edge Server Response (on COMPLETED)
```json
{
  "status": "COMPLETED",
  "transaction_id": "abc123",
  "model_path": "/root/gpufree-data/.../pretrained_model",
  "ssh_host": "gpu-instance.example.com",
  "ssh_username": "root",
  "ssh_port": 22,
  "ssh_password": "YmFzZTY0X2VuY29kZWRfcGFzc3dvcmQ="
}
```

### DoRobot Client Code (edge_upload.py)
```python
def poll_training_status(self, repo_id: str) -> dict:
    """Poll edge server for training status"""
    response = requests.get(f"{self.edge_api_url}/edge/status/{repo_id}")
    return response.json()

def run_edge_upload(self, episode_path: str, repo_id: str) -> bool:
    # ... upload and wait for training ...

    status = self.poll_training_status(repo_id)

    if status.get("status") == "COMPLETED":
        # Extract SSH credentials
        ssh_host = status.get("ssh_host")
        ssh_username = status.get("ssh_username")
        ssh_port = status.get("ssh_port", 22)
        ssh_password_b64 = status.get("ssh_password")

        # Decode base64 password
        ssh_password = base64.b64decode(ssh_password_b64).decode("utf-8")

        # Download model via SFTP
        self.download_model_from_cloud(
            ssh_host=ssh_host,
            ssh_username=ssh_username,
            ssh_password=ssh_password,
            ssh_port=ssh_port,
            remote_model_path=status.get("model_path"),
            local_output_path=f"~/DoRobot/models/{repo_id}/"
        )
```

### SFTP Download Implementation
```python
def download_model_from_cloud(
    self,
    ssh_host: str,
    ssh_username: str,
    ssh_password: str,
    ssh_port: int,
    remote_model_path: str,
    local_output_path: str,
) -> bool:
    """Download trained model from cloud server via SFTP"""
    import paramiko

    # Connect via SSH
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ssh_host, port=ssh_port, username=ssh_username, password=ssh_password)

    sftp = ssh.open_sftp()

    # Recursive download
    def download_dir(remote_dir, local_dir):
        os.makedirs(local_dir, exist_ok=True)
        for item in sftp.listdir_attr(remote_dir):
            remote_path = f"{remote_dir}/{item.filename}"
            local_path = os.path.join(local_dir, item.filename)
            if stat.S_ISDIR(item.st_mode):
                download_dir(remote_path, local_path)
            else:
                sftp.get(remote_path, local_path)

    download_dir(remote_model_path, local_output_path)

    sftp.close()
    ssh.close()
    return True
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
CLOUD_API_URL=http://cloud-server:8000
API_USERNAME=user
API_PASSWORD=pass
```

## API Endpoints

### POST /edge/upload-complete
Client notifies edge server that upload is complete. Triggers encoding + cloud upload.

**Request**:
```json
{
  "repo_id": "my-dataset",
  "episode_index": 5,
  "cloud_username": "user",     // Optional: override default
  "cloud_password": "pass"      // Optional: override default
}
```

**Response**:
```json
{
  "status": "encoding",
  "message": "Upload received, encoding started"
}
```

### GET /edge/status/{repo_id}
Check encoding/upload/training progress. Returns cloud SSH credentials when completed.

**Response (training)**:
```json
{
  "status": "TRAINING",
  "transaction_id": "abc123",
  "progress": "Training in progress..."
}
```

**Response (completed)**:
```json
{
  "status": "COMPLETED",
  "transaction_id": "abc123",
  "model_path": "/root/gpufree-data/.../pretrained_model",
  "ssh_host": "gpu-instance.example.com",
  "ssh_username": "root",
  "ssh_port": 22,
  "ssh_password": "YmFzZTY0X2VuY29kZWRfcGFzc3dvcmQ="
}
```

### POST /edge/train/{repo_id}
Manually trigger cloud training after encoding complete.

## Error Handling

### Client Side
- rsync failure: Retry up to 3 times with exponential backoff
- Network timeout: Fall back to CLOUD_OFFLOAD=1 (direct cloud upload)
- Edge server unavailable: Warn user, continue with local storage

### Edge Server Side
- Encoding failure: Retry episode, mark as failed after 3 attempts
- Cloud upload failure: Queue for retry, continue with other episodes
- Disk space: Alert when upload directory exceeds threshold
- Training status stuck: SSH folder check fallback detects completion

## Security

- SSH key authentication preferred over password
- SSH passwords are base64-encoded in transit (use HTTPS in production)
- Edge server should be on same LAN (not exposed to internet)
- Upload directory isolated from other services
- Rate limiting on API endpoints

## Version History

- **v2.0.43**: Fixed model_dir path for SSH completion check
- **v2.0.42**: Added SSH-based model folder check as fallback
- **v2.0.41**: Added SSH credentials to edge status for SFTP model download
- **v2.0.40**: Added cloud_api_url to edge status response
- **v2.0.39**: Fixed edge status sync with cloud server
