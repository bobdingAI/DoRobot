# Quick Start Guide: CLOUD and NPU Options

This guide covers how to use different CLOUD and NPU options with `run_so101.sh`, and recovery steps when something fails.

## CLOUD Offload Modes

The `CLOUD` environment variable controls where data encoding and training happens:

| CLOUD | Mode | Description | Best For |
|-------|------|-------------|----------|
| 0 | Local Only | Encode locally, no upload | Offline development |
| 1 | Cloud Raw | Upload raw images to cloud for encoding | Low-spec devices (slow upload) |
| 2 | Edge Mode | Rsync to edge server | LAN setup (fastest) |
| 3 | Cloud Encoded | Encode locally, upload encoded to cloud | Good CPU/NPU, direct cloud |
| 4 | Local Raw | Skip encoding, save raw images locally | Debugging, manual encode later |

## NPU Configuration

The `NPU` environment variable enables Ascend hardware acceleration:

| NPU | Description |
|-----|-------------|
| 0 | Use CPU (libx264) for encoding |
| 1 | Use Ascend NPU (h264_ascend) for encoding |

**Note**: NPU=1 requires Ascend 310B hardware (e.g., Orange Pi 20T) with CANN toolkit.

---

## Usage Examples

### 1. Local Development (No Cloud)

```bash
# Encode locally, save to local disk only
CLOUD=0 NPU=0 bash scripts/run_so101.sh
```

### 2. Edge Mode (Recommended for LAN)

```bash
# Upload to edge server via rsync (fastest for local network)
CLOUD=2 NPU=1 EDGE_SERVER_HOST=192.168.1.100 bash scripts/run_so101.sh
```

Required environment variables for edge mode:
```bash
export EDGE_SERVER_HOST=192.168.1.100    # Edge server IP
export EDGE_SERVER_USER=nupylot          # SSH username
export EDGE_SERVER_PORT=22               # SSH port (default: 22)
export EDGE_DATA_DIR=/path/to/data       # Remote data directory
```

### 3. Cloud Raw Mode (Upload Raw Images)

```bash
# Upload raw images to cloud, cloud does encoding
CLOUD=1 NPU=0 bash scripts/run_so101.sh
```

Required environment variables:
```bash
export API_USERNAME=your_username
export API_PASSWORD=your_password
export API_BASE_URL=http://cloud-server:8000
```

### 4. Cloud Encoded Mode (Local Encode + Upload)

```bash
# Encode locally with NPU, upload encoded videos to cloud
CLOUD=3 NPU=1 bash scripts/run_so101.sh
```

### 5. Local Raw Mode (Debug)

```bash
# Save raw images only, no encoding
CLOUD=4 bash scripts/run_so101.sh
```

---

## Recovery Workflows

When something fails during the workflow, use these tools to continue:

### Workflow Overview

```
Recording → Encoding → Upload → Training → Download Model
    ↓          ↓          ↓         ↓           ↓
  main.py   edge.sh    edge.sh   train.py   train.py
```

### Scenario 1: Encoding Failed (CLOUD=2 Edge Mode)

If encoding on the edge server failed:

```bash
# Re-run encoding on edge server
scripts/edge.sh -u USERNAME -p PASSWORD -d /path/to/dataset --skip-upload
```

Options:
- `--skip-upload`: Only encode, don't upload to cloud
- `--skip-training`: Upload but don't start training

### Scenario 2: Upload to Cloud Failed

If edge-to-cloud upload failed:

```bash
# Resume upload (skip local encoding)
scripts/edge.sh -u USERNAME -p PASSWORD -d /path/to/dataset
```

Or use train.py directly:
```bash
# Upload and start training via API
python train.py --input /path/to/dataset --output /path/to/model
```

### Scenario 3: Training Failed or Stuck

If cloud training failed or transaction stuck:

```bash
# Resume with existing transaction (--train-only)
python train.py --input /path/to/dataset --output /path/to/model --train-only
```

The `--train-only` flag:
- Checks for existing transaction
- Resumes monitoring if transaction exists
- Skips upload phase

### Scenario 4: Model Download Failed

If training completed but model download failed:

```bash
# Download model only (--download-only)
python train.py --input /path/to/dataset --output /path/to/model --download-only
```

Or use edge.sh:
```bash
scripts/edge.sh -u USERNAME -p PASSWORD -d /path/to/dataset --download-only
```

### Scenario 5: Direct Cloud Training (No Edge)

For direct cloud training without edge server:

```bash
# Using cloud_train.py
python operating_platform/core/cloud_train.py \
    --dataset.repo_id=/path/to/dataset \
    --output.dir=/path/to/model
```

---

## Environment Variables Reference

### Core Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLOUD` | 2 | Cloud offload mode (0-4) |
| `NPU` | 1 | Use NPU for encoding (0/1) |
| `REPO_ID` | generated | Dataset identifier |
| `FPS` | 30 | Recording frame rate |

### Edge Server (CLOUD=2)

| Variable | Default | Description |
|----------|---------|-------------|
| `EDGE_SERVER_HOST` | 127.0.0.1 | Edge server IP address |
| `EDGE_SERVER_USER` | nupylot | SSH username |
| `EDGE_SERVER_PORT` | 22 | SSH port |
| `EDGE_DATA_DIR` | - | Remote data directory |

### Cloud API (CLOUD=1,3)

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | http://127.0.0.1:8000 | Cloud API URL |
| `API_USERNAME` | - | Cloud account username |
| `API_PASSWORD` | - | Cloud account password |

### GPUFree Instance

| Variable | Default | Description |
|----------|---------|-------------|
| `GPUFREE_INSTANCE_UUID` | - | GPUFree instance UUID |
| `GPUFREE_BEARER_TOKEN` | - | GPUFree API token |

---

## Troubleshooting

### "Failed to start instance. Response: None"

GPUFree API can't find/start the instance. The system will automatically try SSH fallback.

If SSH fallback also fails:
1. Check instance is accessible via SSH manually
2. Verify `GPUFREE_INSTANCE_UUID` is correct
3. Check bearer token has access to the instance

### "UPLOAD_FAILED" in Edge Mode

1. Check edge server connectivity: `ssh $EDGE_SERVER_USER@$EDGE_SERVER_HOST`
2. Verify `EDGE_DATA_DIR` exists and is writable
3. Check available disk space on edge server

### Training Status Stuck at "TRAINING"

The system will automatically check via SSH if the model folder exists.

Manual recovery:
```bash
python train.py --input /path/to/dataset --output /path/to/model --train-only
```

### NPU Encoding Timeout

If NPU channels are busy:
- System retries with exponential backoff (up to 30s)
- Falls back to CPU encoding if NPU unavailable
- Check NPU status: `npu-smi info`

---

## Quick Reference

```bash
# Most common: Edge mode with NPU
CLOUD=2 NPU=1 EDGE_SERVER_HOST=192.168.1.100 bash scripts/run_so101.sh

# Local development
CLOUD=0 NPU=0 bash scripts/run_so101.sh

# Recovery: Resume training
python train.py --input /data/dataset --output /data/model --train-only

# Recovery: Download model only
python train.py --input /data/dataset --output /data/model --download-only

# Recovery: Re-encode on edge
scripts/edge.sh -u user -p pass -d /data/dataset --skip-upload
```
