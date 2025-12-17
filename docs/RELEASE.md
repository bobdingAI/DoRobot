# DoRobot Release Notes

This document tracks all changes made to the DoRobot data collection system.

---

## v0.2.121 (2025-12-17) - Natural Chinese TTS with edge-tts

### Summary
Added natural-sounding Chinese TTS using Microsoft Edge neural voices.
espeak-ng sounds robotic; edge-tts sounds like a native speaker.

### How It Works
1. First tries edge-tts (natural, requires internet)
2. Falls back to espeak-ng (robotic, works offline)

### Chinese Voices Available
- `zh-CN-XiaoxiaoNeural` (female, default)
- `zh-CN-YunxiNeural` (male)

### Changes

**utils/utils.py:**
- Added `_say_edge_tts()` function for neural TTS
- `say()` now tries edge-tts first, falls back to espeak-ng

**scripts/setup_env.sh:**
- Added `mpv` to apt dependencies (audio player)
- Added `pip install edge-tts` for neural TTS

### Requirements
```bash
# System packages
sudo apt install mpv

# Python package
pip install edge-tts

# Test it
edge-tts --voice zh-CN-XiaoxiaoNeural --text "准备就绪" --write-media test.mp3
mpv test.mp3
```

---

## v0.2.120 (2025-12-17) - Fix espeak-ng Package Name

### Summary
Fixed incorrect package name in setup_env.sh - `espeak-ng-data-cmn` doesn't exist.

### Fix
Changed from `espeak-ng espeak-ng-data-cmn` to `espeak-ng espeak-ng-data`.
The Mandarin Chinese (cmn) voice is included in the standard `espeak-ng-data` package.

### Changes

**scripts/setup_env.sh:**
- Changed package from `espeak-ng-data-cmn` to `espeak-ng-data`

---

## v0.2.119 (2025-12-17) - Fix Chinese TTS Voice on Linux

### Summary
Fixed Chinese text-to-speech not working properly on Linux - was reading Chinese characters in English instead of speaking Chinese.

### Problem
The `say()` function used `espeak-ng -v zh` which doesn't work correctly. It would spell out Chinese characters in English phonetics instead of speaking Mandarin.

### Fix
Changed voice code from `zh` to `cmn` (Mandarin Chinese):
- `espeak-ng -v cmn` - correct voice code for Mandarin
- Added `-s 130` to slow down speech rate for better clarity
- Improved error handling with stderr suppression

### Changes

**utils/utils.py:**
- Changed `espeak-ng -v zh` to `espeak-ng -v cmn -s 130`
- Added `stderr=subprocess.DEVNULL` to suppress noise
- Simplified error handling

---

## v0.2.118 (2025-12-17) - Fix Memory Leak During Data Collection

### Summary
Fixed critical memory leak that caused OOM (Out of Memory) crash after collecting 15-20 episodes.

### Problem
During data collection, the system would crash with OOM after ~16-17 episodes. Linux OOM killer would terminate the process:
```
Killed
```
DORA daemon event handling times increased dramatically (100ms → 5000ms+) as memory filled up.

### Root Cause
In `_save_episode_table()`, each episode was concatenated into `hf_dataset` using:
```python
self.hf_dataset = concatenate_datasets([self.hf_dataset, ep_dataset])
```
This accumulated ALL episode data in memory, causing ~50-100MB per episode memory growth.

### Fix
Modified `_save_episode_table()` to only write parquet files without keeping episodes in memory:
- Episode data is now written directly to parquet and immediately freed
- Removed memory-accumulating `concatenate_datasets()` call
- Added explicit `del ep_dataset` for immediate memory release

### Changes

**dataset/dorobot_dataset.py:**
- `_save_episode_table()`: Removed `concatenate_datasets()` call that accumulated all episodes in memory
- Each episode now writes to parquet file and releases memory immediately
- Added comment explaining the memory-efficient approach

### Impact
- Data collection can now run indefinitely without memory growth
- Memory usage stays constant regardless of number of episodes recorded

---

## v0.2.117 (2025-12-17) - Update setup_env.sh for Audio Dependencies

### Summary
Added missing audio dependencies to setup_env.sh for Chinese TTS support.

### Changes

**scripts/setup_env.sh:**
- Added `sudo apt update` before installing packages
- Added `espeak-ng` and `espeak-ng-data-cmn` for Chinese TTS support
- Improved installation order and error handling

---

## v0.2.116 (2025-12-17) - Add Chinese TTS Voice Prompts

### Summary
Changed all audio prompts from English to Chinese for better user experience during data collection.

### Changes

**utils/utils.py:**
- Updated `say()` function to support Chinese TTS:
  - macOS: Uses `Ting-Ting` voice for Chinese
  - Linux: Uses `espeak-ng` with Chinese support (fallback to spd-say)
  - Windows: Auto-detects Chinese via SpeechSynthesizer
- Added `lang` parameter (default "zh") for language selection
- Added error handling with fallback for Linux

**core/main.py:**
- Translated all 37 `log_say()` prompts to Chinese, including:
  - "准备就绪。按N键保存并开始下一集。" (Ready to start)
  - "请重置环境。按P键继续。" (Reset environment)
  - "采集结束。共采集X集。" (End collection)
  - "训练完成。模型已下载。" (Training complete)
  - Status messages for edge/cloud workflows

**core/replay.py:**
- Translated replay prompt to "正在回放录像"

### Linux Setup
```bash
# Install Chinese TTS support
sudo apt install espeak-ng espeak-ng-data-cmn
```

---

## v0.2.112 (2025-12-12) - Fix Inference Mode Leader Arm Handling

### Summary
Fixed multiple issues preventing inference mode from working without leader arm:

1. **`__init__` KeyError**: Hardcoded `self.config.leader_arms["main"]` crashed when empty config passed
2. **Error reporting bug**: Hardcoded `i == 1` assumed leader arms, wrong in inference mode
3. **Skip 3s wait**: When `--robot.leader_arms="{}"` passed, skip the 3-second detection

### Changes

**manipulator.py:**
- `__init__`: Check if `"main"` exists in leader_arms before accessing
- `connect()`: If `self.leader_arms` is empty, skip 3-second detection wait
- Error reporting: Use `base_msg` content to determine arm type instead of index

### Usage
```bash
# run_so101_inference.sh now passes empty leader_arms
python operating_platform/core/inference.py \
    --robot.type=so101 \
    --robot.leader_arms="{}" \
    ...
```

### Expected Output
```
[SO101] No leader arms configured - inference mode (follower only)
[连接成功] 所有设备已就绪:
  - 摄像头: image_top, image_wrist
  - 从臂关节角度: main_follower
```

---

## v0.2.111 (2025-12-12) - Auto-detect Inference Mode (Skip Leader Arm Check)

### Summary
Modified `manipulator.py` to auto-detect inference mode and skip leader arm connection check.
In inference mode (when running `dora_control_dataflow.yml`), only the follower arm is connected.
The manipulator now detects this by checking if leader arm data arrives within 3 seconds.

### Problem
Running `bash scripts/run_so101_inference.sh` failed with:
```
TimeoutError: 连接超时，未满足的条件: 等待主臂关节角度超时: 未收到[main_leader]
```
Even though inference mode doesn't need a leader arm.

### Solution
In `connect()` method:
1. Wait 3 seconds to see if any leader arm data arrives
2. If no leader data → inference mode → skip leader arm check
3. Only check cameras and follower arm connection

### Changes

**manipulator.py:**
- Added leader arm detection with 3s timeout in `connect()`
- Made leader arm condition check conditional on `has_leader_arm_data`
- Fixed success printing logic to handle both modes correctly

### Behavior
```
# Teleoperation mode (dora_teleoperate_dataflow.yml)
[SO101] Leader arm data detected - teleoperation mode
[连接成功] 所有设备已就绪:
  - 摄像头: image_top, image_wrist
  - 主臂关节角度: main_leader
  - 从臂关节角度: main_follower

# Inference mode (dora_control_dataflow.yml)
[SO101] No leader arm data - inference mode (follower only)
[连接成功] 所有设备已就绪:
  - 摄像头: image_top, image_wrist
  - 从臂关节角度: main_follower
```

---

## v0.2.110 (2025-12-11) - Fix Joint Naming in dora_control_dataflow.yml

### Summary
Fixed joint naming mismatch in `dora_control_dataflow.yml` that caused follower arm not to be detected.

### Problem
Error: `未收到 [main_follower]; 已收到 []`

### Root Cause
- `dora_control_dataflow.yml` used `follower_joint` as the input key
- `manipulator.py` checks if "main_follower" exists in received joint keys
- Since "main_follower" is not a substring of "follower_joint", the check failed

### Fix
Changed `dora_control_dataflow.yml` to use `main_follower_joint` (matching teleoperate dataflow):
```yaml
inputs:
  main_follower_joint: arm_so101_follower/joint  # Was: follower_joint
```

---

## v0.2.109 (2025-12-11) - Add Device Config Loading to run_so101_inference.sh

### Summary
Added device config file loading to inference script, matching `run_so101.sh` behavior.

### Changes
- Load camera/USB port settings from `~/.dorobot_device.conf`
- Config file search order: `~/.dorobot_device.conf` → `/etc/dorobot/device.conf` → `.device.conf`
- Display loaded config file path in startup banner

---

## v0.2.108 (2025-12-11) - All-in-One Inference Launcher

### Summary
Combined DORA startup and inference into single command.

### Usage
```bash
bash scripts/run_so101_inference.sh [DATASET_PATH] [MODEL_PATH] [SINGLE_TASK]
```

### Changes
- Script now starts DORA in background
- Waits 5s for DORA nodes to initialize
- Runs inference Python command
- Cleanup on exit (stops DORA, removes IPC files)

---

## v0.2.107 (2025-12-11) - Simplify inference.sh for Two-Terminal Workflow

### Summary
Simplified `run_so101_inference.sh` to only run the Python inference command.
User now starts DORA manually in a separate terminal first.

### Workflow
```bash
# Terminal 1: Start DORA
cd operating_platform/robot/robots/so101_v1
dora run dora_control_dataflow.yml      # Follower only (recommended)
# OR
dora run dora_teleoperate_dataflow.yml  # Needs both leader + follower

# Terminal 2: Run inference
bash scripts/run_so101_inference.sh ~/dataset ~/model "Pick apple"
```

### Changes
- Removed DORA startup logic from inference.sh
- Script now only runs Python command
- Added clear usage instructions in script header
- Accepts task description as 3rd argument

---

## v0.2.106 (2025-12-10) - Tar-based Upload for 3-4x Faster Transfer

### Summary
Implemented tar-based upload mode for edge uploads. Instead of rsyncing ~27,000 PNG files
individually, the client now creates a tar archive, uploads a single file, and the edge
server extracts it. This reduces upload time from ~60 minutes to ~15-20 minutes for 24GB.

### Performance
| Metric | Before (rsync) | After (tar) |
|--------|----------------|-------------|
| Upload time (24GB) | ~60 min | ~15-20 min |
| Speedup | - | 3-4x faster |

### Changes

**edge_upload.py:**
- `_create_tar_archive()`: Creates tar of dataset in /tmp (no compression, PNG already compressed)
- `_upload_tar_file()`: Uploads single tar via SFTP with progress callback
- `sync_dataset()`: Added `use_tar=True` parameter (default), falls back to direct mode if tar fails
- `notify_upload_complete()`: Added `is_tar` and `tar_path` fields to API request

### Flow
1. Create tar: `tar cf /tmp/{repo_id}.tar -C {parent} {repo_id}`
2. Upload single tar file via SFTP
3. Delete local tar file
4. Notify edge server with `is_tar=True`
5. Edge extracts tar and continues with encoding

### Requires
- data-platform v2.0.44+ (for tar extraction on edge server)

---

## v0.2.105 (2025-12-10) - Update Edge Upload Documentation

### Summary
Updated `docs/edge_upload.md` with comprehensive workflow documentation covering
the complete CLOUD_OFFLOAD=2 edge upload and model download flow.

### Documentation Added
- Architecture diagram showing bidirectional flow (upload + download)
- Two SSH credential sets explanation (Edge SSH vs Cloud SSH)
- Complete data flow diagrams for all 4 phases:
  1. Image Upload (Client → Edge)
  2. Encoding + Cloud Upload (Edge → Cloud)
  3. Training Completion Detection
  4. Model Download (Cloud → Client)
- Training completion detection methods (API status + SSH folder check fallback)
- Code examples for DoRobot client download implementation
- API endpoint documentation with request/response examples
- Version history section

---

## v0.2.104 (2025-12-10) - Use SFTP for Model Download (like cloud_train.py)

### Summary
Changed model download from HTTP to SFTP, borrowing the working pattern from
`cloud_train.py`. HTTP download was not suitable for model folders with many files.
SFTP download is the same method used by the working CLOUD_OFFLOAD=1 mode.

### Changes

**edge_upload.py:**
- `download_model_from_cloud()` now uses SFTP via paramiko (was HTTP)
- SSH credentials (host, username, password, port) passed from edge status
- `poll_training_status()` returns SSH info from edge status response
- `run_edge_upload()` decodes base64 password and calls SFTP download
- Recursive directory download (identical to cloud_train.py pattern)

### Model Download Flow (SFTP)
1. Training completes on cloud server
2. Edge server stores SSH credentials in status (from cloud transaction)
3. DoRobot gets SSH info when polling status (ssh_host, ssh_username, etc.)
4. Downloads model directly from cloud via SFTP (bypassing edge server)
5. Model saved to local directory

### Requires
- data-platform v2.0.41+ (for ssh_info in edge status)

---

## v0.2.103 (2025-12-10) - Fix Model Download from Cloud Server

### Summary
Fixed model download in edge workflow. Previously, DoRobot tried to download
models via SFTP from edge server, but models are stored on cloud server.
Now downloads directly from cloud server via HTTP.

### Changes

**edge_upload.py:**
- Added `download_model_from_cloud()` method for HTTP download from cloud server
- `poll_training_status()` now returns dict with `transaction_id`, `cloud_api_url`, `model_path`
- `run_edge_upload()` now uses cloud download instead of SFTP download
- Downloads model via `/transactions/{id}/model` endpoint on cloud server
- Handles both zip archives and single files

### Model Download Flow (Fixed)
1. Training completes on cloud server
2. Edge server returns `cloud_api_url` and `transaction_id` in status
3. DoRobot downloads directly from cloud: `{cloud_api_url}/transactions/{tx_id}/model`
4. Model extracted to local `~/DoRobot/model/` directory

### Requires
- data-platform v2.0.40+ (for `cloud_api_url` in edge status)

---

## v0.2.102 (2025-12-10) - Add Transaction ID to Edge Upload Logs

### Summary
Added transaction_id to edge upload status logs for easier debugging.
When polling training status, logs now show which transaction to check on the server.

### Changes

**edge_upload.py:**
- `poll_training_status()` now extracts transaction_id from status response
- Status logs include transaction_id: `Status: TRAINING, Progress: xxx (tx=abc123)`
- Completion and failure logs also include transaction_id
- Makes it easy to correlate client logs with server admin console

### Example Output
```
[EdgeUpload] Status: TRAINING, Progress: Training in progress (tx=abc12345-1234-5678-abcd-123456789abc)
[EdgeUpload] Training completed! (tx=abc12345-...) Model path: /path/to/model
```

---

## v0.2.101 (2025-12-10) - Fix Training Not Starting After Encoding

### Summary
Fixed issue where training never started after encoding completed.
The robot would keep polling "READY" status indefinitely.

### Root Cause
1. Robot calls `/edge/train` while encoding is still in progress
2. Edge server returns "Dataset still encoding, please wait" but doesn't start training
3. Encoding completes, status becomes "READY"
4. Robot keeps polling but never re-triggers training
5. Status stays at "READY" forever

### Fix
**edge_upload.py:**
- `poll_training_status()` now detects "READY" status
- When "READY" is seen, automatically re-calls `trigger_training()`
- Tracks `training_triggered` flag to avoid multiple re-triggers
- Training proceeds after encoding completes

### Behavior After Fix
1. Upload completes, encoding starts
2. Robot polls status, sees "ENCODING"
3. Encoding completes, status becomes "READY"
4. **Robot detects READY, re-triggers training**
5. Training starts on cloud GPU

---

## v0.2.100 (2025-12-10) - Clear Edge Target Folder Before Upload

### Summary
Added automatic clearing of target folder on edge server before SFTP upload.
This prevents leftover files from previous uploads causing issues.

### Changes

**edge_upload.py:**
- Added `clear_remote_directory()` method to clear remote folder contents
- `sync_dataset()` now calls `clear_remote_directory()` before uploading
- Works with both paramiko (password) and SSH key authentication
- Non-fatal: if clear fails, upload continues with a warning

### Behavior
Before each CLOUD=2 upload:
1. Create remote directory (if not exists)
2. **NEW:** Clear all contents from remote directory
3. Upload dataset files via SFTP

---

## v0.2.99 (2025-12-09) - Fix CLOUD=2 Cloud Credentials Passing

### Summary
Fixed CLOUD=2 workflow where edge server failed to upload to cloud due to missing credentials.

### Root Cause
- Robot device loads API_PASSWORD from ~/.dorobot_device.conf
- API_PASSWORD was NOT exported to Python (edge_upload.py)
- edge_upload.py did not pass cloud credentials in API requests
- Edge server had no credentials to authenticate with cloud training server

### Fix Details

**run_so101.sh:**
- Added `export API_PASSWORD` (line 597) to pass cloud credentials to Python

**edge_upload.py:**
- Added `DEFAULT_API_PASSWORD` constant reading from `API_PASSWORD` env var
- Added `api_password` field to `EdgeConfig` dataclass
- Updated `from_env()` to read `API_PASSWORD`
- `notify_upload_complete()` now passes `cloud_username` and `cloud_password` in JSON payload
- `trigger_training()` now passes `cloud_username` and `cloud_password` in JSON payload

### Credential Flow (After Fix)
```
~/.dorobot_device.conf (API_PASSWORD)
       ↓
run_so101.sh (export API_PASSWORD)
       ↓
edge_upload.py (EdgeConfig.api_password)
       ↓
POST /edge/upload-complete {cloud_username, cloud_password}
       ↓
Edge Server → Cloud Training Server (authenticated)
```

---

## v0.2.97 (2025-12-09) - README: CLOUD=2 Edge Workflow Documentation

### Summary
Added comprehensive documentation for the CLOUD=2 edge workflow in README.md.

### New Section: Quick Start: Edge Workflow (CLOUD=2) - Recommended

The new section includes:
- Architecture diagram showing data flow: Robot → Edge Server → Cloud → Model
- Performance comparison table (CLOUD=2 is 50x faster than direct upload)
- Step-by-step setup guide for edge server
- Robot device configuration instructions
- Complete workflow with automatic training and model download
- Edge server environment variables reference
- Multi-user support documentation

### Key Points Documented
- CLOUD=2 is the default and recommended mode
- LAN transfer takes ~6 seconds vs ~5 minutes for WAN upload
- Robot doesn't wait for encoding/training
- Model is automatically downloaded after training

---

## v0.2.96 (2025-12-09) - Fix Quick Start Guide Clarity

### Summary
Fixed Quick Start guide to clarify that the laptop IS the API server, not a separate edge server.

### Workflow Clarification
1. **Orange Pi (robot device)**: Collect data with `CLOUD=4` (raw images only)
2. **USB copy**: Transfer data from Orange Pi to laptop
3. **Laptop (API server)**: Run `edge.sh` to encode, upload to cloud, download model
4. **USB copy back**: Transfer model from laptop to Orange Pi for inference

---

## v0.2.95 (2025-12-09) - README: Edge Server Workflow Quick Start Guide

### Summary
Added comprehensive documentation for the USB transfer workflow using CLOUD=4 and edge.sh.

### New Documentation

**Quick Start: Edge Server Workflow (USB Transfer)**
- Step 1: Collect data on robot device with CLOUD=4
- Step 2: Copy data to edge server via USB
- Step 3: Run edge.sh on edge server (encode -> train -> download)
- Step 4: Copy model back (optional)

**Updated CLOUD Modes**
- Added CLOUD=4 (Local raw) to mode tables and examples
- CLOUD=4 saves raw images only, no encoding, perfect for USB transfer

**edge.sh Reference**
- Complete usage reference with all options
- Multi-user support documentation

---

## v0.2.94 (2025-12-09) - Multi-User edge.sh with Mandatory Credentials

### Summary
Updated edge.sh to require mandatory `-u username` and `-p password` parameters for multi-user edge server usage. This ensures user isolation when multiple users run edge.sh on a shared edge server.

### Breaking Change
The old positional argument syntax is no longer supported:
```bash
# OLD (no longer works)
scripts/edge.sh ~/DoRobot/dataset/my_data

# NEW (required)
scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my_data
```

### New Usage

```bash
scripts/edge.sh -u <username> -p <password> -d <dataset_path> [options]

Required:
  -u, --username      API username (for authentication and path isolation)
  -p, --password      API password
  -d, --dataset       Path to dataset directory with raw images

Optional:
  --skip-training     Skip training (just upload + encode)
  --repo-id NAME      Custom repo ID (default: folder name)
  --model-output PATH Custom model output path (default: dataset/model/)
  --timeout MINUTES   Training timeout in minutes (default: 120)
  --test-connection   Only test SSH and API connections
```

### Examples

```bash
# Full workflow for user "alice"
scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my_data

# Skip training
scripts/edge.sh -u bob -p bob456 -d ~/dataset/test --skip-training

# Test connection
scripts/edge.sh -u alice -p alice123 --test-connection

# Custom timeout
scripts/edge.sh -u alice -p alice123 -d ~/data --timeout 180
```

### Multi-User Isolation
- Each user's uploads go to `/uploaded_data/{username}/{repo_id}/`
- Multiple users can run edge.sh simultaneously on the same server
- No conflicts between users with same repo_id names

### Changes

**scripts/edge.sh**
- Changed from positional argument to required `-u`, `-p`, `-d` options
- Proper argument parsing with error messages
- Shows upload path with username in output

**scripts/edge_encode.py**
- Updated docstring with new usage
- References edge.sh wrapper as recommended usage

---

## v0.2.93 (2025-12-09) - Edge Full Workflow: Wait for Training and Download Model

### Summary
Enhanced edge.sh to wait for training completion and automatically download the trained model. The script now handles the complete workflow: upload -> encode -> train -> download model.

### Features

**Full Workflow Support**
- Script waits for training to complete (with configurable timeout)
- Automatically downloads trained model to local path
- Shows transaction ID from data-platform for tracking
- Default model output: `{dataset_path}/model/`
- Multiple instances can run in parallel for different datasets

**New Command Options**
```bash
scripts/edge.sh <dataset_path> [options]

Options:
  --skip-training     Skip training (just upload + encode)
  --model-output PATH Custom model output path (default: dataset/model/)
  --timeout MINUTES   Training timeout in minutes (default: 120)
  --repo-id NAME      Custom repo ID (default: folder name)
  --test-connection   Only test SSH and API connections
```

### Usage Examples

```bash
# Full workflow: upload -> encode -> train -> download model
scripts/edge.sh ~/DoRobot/dataset/my_repo_id

# Custom model output path
scripts/edge.sh ~/dataset/my_data --model-output /custom/path/model

# Custom timeout (default 120 minutes)
scripts/edge.sh ~/dataset/my_data --timeout 180

# Upload only (skip training and download)
scripts/edge.sh ~/dataset/my_data --skip-training
```

### Workflow Steps

1. **[Step 1/4] Upload** - Upload raw images to edge server via SFTP
2. **[Step 2/4] Encode** - Trigger encoding on edge server
3. **[Step 3/4] Train** - Trigger cloud training (returns transaction ID)
4. **[Step 4/4] Wait & Download** - Poll status until complete, download model

### Changes

**operating_platform/core/edge_upload.py**
- Added `download_model()` method to EdgeUploader for SFTP model download
- Updated `trigger_training()` to return `(success, transaction_id)` tuple
- Recursive directory download with progress callback

**scripts/edge_encode.py**
- Added `wait_training_and_download()` function
- Added `--model-output` and `--timeout` command-line options
- Updated `run_retry_workflow()` to 4-step workflow with model download
- Updated docstring with full workflow documentation

**scripts/edge.sh**
- Updated documentation with new options
- Shows default model output path at startup
- Note about waiting for training completion

### Notes
- Script will NOT exit until training completes and model is downloaded
- Use `--skip-training` if you only want upload+encode functionality
- Multiple parallel sessions supported for different datasets

---

## v0.2.92 (2025-12-09) - Add edge.sh Wrapper Script

### Summary
Added edge.sh wrapper script for simpler edge upload invocation.

### Usage
```bash
scripts/edge.sh ~/DoRobot/dataset/my_repo_id
scripts/edge.sh ~/dataset/my_data --skip-training
scripts/edge.sh --test-connection
```

---

## v0.2.91 (2025-12-09) - Multi-user Upload Path Isolation

### Summary
Changed edge upload path structure to include API_USERNAME for multi-user isolation on shared API servers.

### Problem
When multiple users share the same edge/API server, upload paths could conflict:
- Old: `/uploaded_data/{REPO_ID}/`
- Users uploading datasets with same repo_id would overwrite each other

### Solution
Include API_USERNAME in the upload path:
- New: `/uploaded_data/{API_USERNAME}/{REPO_ID}/`
- Each user's data is isolated in their own subdirectory

### Changes

**operating_platform/core/edge_upload.py**
- Added `api_username` field to `EdgeConfig` (from `API_USERNAME` env var, default: "default")
- Added `get_upload_path(repo_id)` method that returns `{remote_path}/{api_username}/{repo_id}`
- Updated `sync_dataset()` to use new path structure
- Updated `notify_upload_complete()` to send full path with username
- Updated log messages to show API user and full path

**scripts/edge_encode.py**
- Updated docstring to document API_USERNAME
- Updated log output to show API user and full upload path
- Updated test_connection() to show path structure

**scripts/run_so101.sh**
- Export API_USERNAME to environment
- Version bumped to 0.2.91

### Configuration

Add to `~/.dorobot_device.conf`:
```bash
API_USERNAME="your_username"
```

Or set via environment:
```bash
API_USERNAME=alice bash scripts/run_so101.sh
```

### Remote Structure

```
/uploaded_data/
  ├── alice/
  │   ├── test_dataset_1/
  │   └── test_dataset_2/
  └── bob/
      └── test_dataset_1/  # Same repo_id, different user
```

---

## v0.2.90 (2025-12-09) - Add CLOUD=4 Local Raw Mode

### Summary
Added CLOUD=4 mode: skip encoding, save raw images locally only. Useful for testing or later upload with `edge_encode.py`.

### New Feature: CLOUD=4 (Local Raw Mode)

Added a fifth offload mode that saves raw images locally without any encoding or upload:
- Skip video encoding entirely (save PNG images only)
- No upload to edge or cloud servers
- Use `edge_encode.py` later to upload and encode when ready

**CLOUD Mode Summary:**

| Value | Mode | Encoding | Upload | Training |
|-------|------|----------|--------|----------|
| 0 | Local Only | Local (NPU/CPU) | None | None |
| 1 | Cloud Raw | Cloud server | Raw images | Cloud |
| 2 | Edge | Edge server | Raw images | Cloud (via edge) |
| 3 | Cloud Encoded | Local (NPU/CPU) | Encoded videos | Cloud |
| 4 | Local Raw | None | None | None |

**Usage:**
```bash
# Local raw mode (skip encoding, save raw images locally)
CLOUD=4 bash scripts/run_so101.sh

# Later, upload and encode with edge_encode.py
python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id
```

### Use Cases
- Testing data collection without waiting for encoding
- Debugging dataset structure before upload
- Collecting data when edge/cloud servers are unavailable
- Manual upload workflow with `edge_encode.py`

### Changes

**operating_platform/core/main.py**
- Added `OFFLOAD_LOCAL_RAW = 4` constant
- Updated `skip_encoding` logic: modes 1, 2, and 4 skip encoding
- Added mode 4 handling in startup, UI prompts, voice prompts
- Added mode 4 exit handler that shows path and `edge_encode.py` command

**scripts/run_so101.sh**
- Added CLOUD=4 support in comments, logging, CLI args
- Updated help text with all 5 modes
- Updated runtime controls display for mode 4
- Version bumped to 0.2.90

---

## v0.2.89 (2025-12-09) - Rename to edge_encode.py

### Summary
Renamed `retry_edge_upload.py` to `edge_encode.py` for clearer naming.

### Usage

```bash
# Upload dataset and trigger training
python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id

# Upload only (skip training)
python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

# Test connection first
python scripts/edge_encode.py --test-connection
```

---

## v0.2.88 (2025-12-09) - Add edge upload retry script

### Summary
Added script to upload existing raw image datasets to edge server for encoding and training.

### Use Case
When running with CLOUD=2 (edge mode), data is saved locally as raw images. If the edge upload fails (network issue, server down, etc.), this script can retry the upload without re-collecting data.

### Features
- Upload existing raw image datasets to edge server
- Trigger encoding and training on edge server
- Test SSH and API connections before upload
- Validates dataset has images before upload
- Progress logging with upload speed stats
- Status polling for encoding completion

---

## v0.2.87 (2025-12-09) - Fix 2-minute startup delay in edge mode

### Summary
Fixed 2-minute delay at "All systems ready!" screen when edge server connection test times out or fails.

### Problem
In edge mode (CLOUD=2), the system was stuck at "All systems ready!" for ~2 minutes before continuing. This was caused by SSH connection test using long timeouts (30s connect + 60s command timeout).

### Root Cause
`test_edge_connection()` in main.py calls `uploader.test_connection()` which uses 30-second SSH connect timeout and 60-second command timeout. When the edge server is unreachable, these timeouts add up.

### Solution
Added `quick_test` parameter to `EdgeUploader.test_connection()`:
- `quick_test=True`: Use 5-second timeout for startup checks
- `quick_test=False`: Use normal 30-second timeout for actual operations

Updated `test_edge_connection()` in main.py to use `quick_test=True` for the startup connection check.

### Changes

**operating_platform/core/edge_upload.py**
- Added `quick_test: bool = False` parameter to `test_connection()`
- When `quick_test=True`, uses 5-second timeout for both SSH connect and command
- Creates separate paramiko client for quick test to avoid affecting main connection

**operating_platform/core/main.py**
- Changed `uploader.test_connection()` to `uploader.test_connection(quick_test=True)`
- Added comment explaining the timeout reduction

### Expected Behavior
- Startup delay reduced from ~2 minutes to ~5 seconds when edge server is unreachable
- No impact on actual upload operations (still use normal timeouts)
- Clear "Edge server connection failed!" message after 5 seconds instead of 2 minutes

---

## v0.2.86 (2025-12-09) - Fix USB port increment issue with improved cleanup

### Summary
Fixed video/serial port numbers incrementing after multiple recording sessions. The issue was caused by insufficient cleanup timing and force-killing processes without allowing them to release USB resources.

### Problem
After several rounds of data collection, USB port numbers kept increasing:
- `/dev/video0` → `/dev/video2` → `/dev/video4`
- `/dev/ttyACM0` → `/dev/ttyACM2` → `/dev/ttyACM4`

This happened more frequently after v0.2.64 due to cleanup timing issues.

### Root Causes
1. **`dora stop` didn't wait** - Sent STOP events but returned before nodes processed them
2. **Force kill with SIGKILL (-9)** - Bypassed signal handlers so `cleanup_video_capture()` never ran
3. **No wait after pkill** - Camera processes killed before releasing VideoCapture
4. **Wrong cleanup order** - Should kill camera/arm nodes FIRST, wait for release, then kill coordinator

### Solution
Rewrote `cleanup()` and `cleanup_stale_sockets()` functions with proper timing:

**New cleanup sequence:**
1. `dora stop` - Send STOP events to DORA nodes
2. **Wait 3 seconds** - Allow nodes to receive STOP and release resources
3. `pkill -SIGTERM` camera/arm processes - Trigger cleanup handlers
4. **Wait 2 seconds** - Allow cleanup_video_capture() to run
5. `dora destroy` - Clean up DORA graph
6. Kill DORA coordinator with SIGTERM (wait up to 5s)
7. Force kill (SIGKILL) only remaining stuck processes

### Changes

**scripts/run_so101.sh**
- `cleanup()`: Complete rewrite with 6-step cleanup sequence
- `cleanup_stale_sockets()`: Graceful shutdown before force kill
- Added dora-daemon cleanup
- Wait timeouts: 3s after dora stop, 2s after SIGTERM, 5s for DORA coordinator
- Version bumped to 0.2.86

### Expected Behavior
- Port numbers should remain stable: `/dev/video0`, `/dev/video2`, `/dev/ttyACM0`, `/dev/ttyACM1`
- Multiple sessions without needing to unplug/replug USB devices
- Clean shutdown logs showing each cleanup step

---

## v0.2.85 (2025-12-09) - Preserve config settings when running detect.sh

### Summary
Fixed detect.sh/detect_usb_ports.py to preserve existing non-hardware settings when updating device configuration.

### Problem
Running `bash scripts/detect.sh` would overwrite the entire `~/.dorobot_device.conf` file, removing user-configured settings like:
- CLOUD, NPU
- EDGE_SERVER_HOST, EDGE_SERVER_USER, EDGE_SERVER_PASSWORD, etc.
- API_BASE_URL, API_USERNAME, API_PASSWORD

### Solution
Added `load_existing_config()` function that reads and preserves non-hardware fields before regenerating the config. Now detect.sh only updates hardware detection fields (CAMERA_*, ARM_*) while preserving all other settings.

**Preserved fields:**
- CLOUD, NPU
- EDGE_SERVER_HOST, EDGE_SERVER_USER, EDGE_SERVER_PASSWORD, EDGE_SERVER_PORT, EDGE_SERVER_PATH
- API_BASE_URL, API_USERNAME, API_PASSWORD

**Updated fields (hardware detection):**
- CAMERA_TOP_PATH, CAMERA_WRIST_PATH
- ARM_LEADER_PORT, ARM_FOLLOWER_PORT

### Changes

**scripts/detect_usb_ports.py**
- Added `load_existing_config()` function to parse and preserve non-hardware fields
- Updated `save_device_config()` to call `load_existing_config()` first
- Config now always includes CLOUD, NPU, EDGE_*, and API_* sections with preserved or default values
- Shows "Preserved settings: ..." in output when fields are preserved

---

## v0.2.84 (2025-12-09) - Fix cloud_offload type from bool to int

### Summary
Fixed draccus config parsing error when using CLOUD environment variable. Changed `cloud_offload` field type from `bool` to `int` to support all 4 modes (0,1,2,3).

### Problem
Running `CLOUD=2 bash scripts/run_so101.sh` failed with:
```
draccus.utils.DecodingError: `record.cloud_offload`: Couldn't parse `2` into a bool
```

### Root Cause
In v0.2.80, we renamed `CLOUD_OFFLOAD` to `CLOUD` with values 0,1,2,3, but `RecordConfig.cloud_offload` was still typed as `bool`.

### Solution
Changed the field type and added derived `skip_encoding` boolean:

**operating_platform/core/record.py**
```python
# RecordConfig dataclass
cloud_offload: int = 0  # Was: bool = False

# Record.__init__
self.cloud_offload = getattr(record_cfg, 'cloud_offload', 0)
# Skip encoding for modes 1 (cloud raw) and 2 (edge) - they do encoding remotely
# Modes 0 (local) and 3 (cloud encoded) do local encoding
self.skip_encoding = self.cloud_offload in (1, 2)

# Record.save() method
if skip_encoding is None:
    skip_encoding = self.skip_encoding
```

### Skip Encoding Logic

| CLOUD | Mode | Skip Encoding | Encoding Location |
|-------|------|---------------|-------------------|
| 0 | Local only | False | Local (NPU/CPU) |
| 1 | Cloud raw | True | Cloud server |
| 2 | Edge | True | Edge server |
| 3 | Cloud encoded | False | Local (NPU/CPU) |

---

## v0.2.83 (2025-12-09) - Pin setuptools version

### Summary
Added `pip install setuptools==68.2.2` to setup_env.sh to avoid compatibility issues with newer setuptools versions.

### Changes
- Added Step 2.8 to pin setuptools==68.2.2 before installing packages

---

## v0.2.82 (2025-12-09) - Add python-socketio to setup script

### Summary
Added explicit `pip install python-socketio` to setup_env.sh for ZeroMQ communication support.

### Changes
- Added Step 7.5 to install python-socketio in setup_env.sh
- portaudio19-dev already present in apt install section

---

## v0.2.81 (2025-12-09) - Slim Core Dependencies for Faster Installation

### Summary
Removed unused packages from core dependencies and moved web/server packages to optional `[server]` group. This speeds up installation for data collection use cases.

### Removed from Core (not used in data collection)
- `zarr` - Not used anywhere in codebase
- `gevent` - Only used in server/test files
- `flask`, `flask-cors`, `flask-socketio` - Only used in server/visualization
- `python-socketio`, `websocket-client` - Only used in server
- `schedule` - Only used in server/test files

### New Optional Dependency Group
```bash
# Install server dependencies (for web UI, visualization)
pip install -e ".[server]"
```

**`[server]` group includes:**
- gevent, flask, flask-cors, flask-socketio
- python-socketio, websocket-client, schedule

### Impact
- **~30-60 seconds faster** core installation
- **~50+ fewer transitive dependencies** for data collection only
- No impact on data collection, training, or inference functionality

### Usage
```bash
# Data collection only (fastest)
bash scripts/setup_env.sh

# With server/visualization
pip install -e ".[server]"

# Everything
pip install -e ".[all]"
```

---

## v0.2.80 (2025-12-09) - Simplified Parameter Names for International Users

### Summary
Renamed environment variables for better usability by non-English speakers: shorter, single-word parameter names.

### Changes

**Parameter Renames:**
- `CLOUD_OFFLOAD` → `CLOUD` (values: 0, 1, 2, 3)
- `USE_NPU` → `NPU` (values: 0, 1)

**Files Updated:**
- `scripts/run_so101.sh`: All references to CLOUD_OFFLOAD → CLOUD, USE_NPU → NPU
- `scripts/run_so101_inference.sh`: USE_NPU → NPU
- `README.md`: Updated all example commands and documentation
- `~/.dorobot_device.conf`: Template updated with new parameter names

### Usage Examples

```bash
# Cloud modes (CLOUD=0,1,2,3)
CLOUD=0 bash scripts/run_so101.sh  # Local only
CLOUD=1 bash scripts/run_so101.sh  # Cloud raw
CLOUD=2 bash scripts/run_so101.sh  # Edge (default)
CLOUD=3 bash scripts/run_so101.sh  # Cloud encoded

# NPU options (NPU=0,1)
NPU=0 bash scripts/run_so101.sh    # Disable NPU
NPU=1 bash scripts/run_so101.sh    # Enable NPU (default)

# Combined
CLOUD=2 NPU=0 bash scripts/run_so101.sh
```

### Backward Compatibility
The old parameter names (`CLOUD_OFFLOAD`, `USE_NPU`) are no longer recognized. Users must update their scripts and config files to use the new names.

---

## v0.2.79 (2025-12-09) - Add CLOUD_OFFLOAD=3 Mode (Local Encode → Cloud)

### Summary
Added CLOUD_OFFLOAD=3 mode: encode videos locally with NPU/CPU, then upload encoded videos to cloud for training. Also fixed test_edge_workflow.py PNG format and added edge API logging.

### New Feature: CLOUD_OFFLOAD=3 (Cloud Encoded Mode)

Added a fourth offload mode that combines local encoding with cloud training:
- Encode videos locally using NPU or CPU (same as mode 0)
- Upload encoded videos to cloud for training (same as mode 1/2 training flow)
- Downloads trained model back to client

**CLOUD_OFFLOAD Mode Summary:**

| Value | Mode | Encoding | Upload | Training |
|-------|------|----------|--------|----------|
| 0 | Local Only | Local (NPU/CPU) | None | None |
| 1 | Cloud Raw | Cloud server | Raw images | Cloud |
| 2 | Edge | Edge server | Raw images | Cloud (via edge) |
| 3 | Cloud Encoded | Local (NPU/CPU) | Encoded videos | Cloud |

**Usage:**
```bash
# Cloud encoded mode (encode locally, upload encoded to cloud)
CLOUD_OFFLOAD=3 bash scripts/run_so101.sh
```

### Changes

**operating_platform/core/main.py**
- Added `OFFLOAD_CLOUD_ENCODED = 3` constant
- Renamed `OFFLOAD_CLOUD` to `OFFLOAD_CLOUD_RAW` for clarity
- Updated `skip_encoding` logic: modes 0 and 3 do local encoding
- Added mode 3 handling in startup, UI prompts, voice prompts
- Added mode 3 upload/training flow in 'e' key handlers

**scripts/run_so101.sh**
- Added CLOUD_OFFLOAD=3 support in comments, logging, CLI args
- Updated help text with all 4 modes
- Updated runtime controls display for mode 3

### Bug Fixes

1. **Wrong image format**: `test_edge_workflow.py` was extracting frames as JPEG but `encode_dataset.py` expects PNG
   - Changed ffmpeg extraction from `.jpg` to `.png`
   - Changed OpenCV fallback from `.jpg` to `.png`
   - Updated file glob patterns to match `.png`

### Improvements

1. **Enhanced edge endpoint logging** in `data-platform/api.py`:
   - Added detailed logging for `/edge/upload-complete` with repo_id and dataset_path
   - Added directory structure inspection before encoding (camera directories, PNG/JPG counts)
   - Added full traceback logging on encode/upload task failure
   - Added detailed logging for `/edge/train` with status tracking

### Changes

**scripts/test_edge_workflow.py**
- `extract_frames_with_ffmpeg()`: Output `.png` instead of `.jpg`
- OpenCV fallback: Save as `.png` instead of `.jpg` with JPEG quality
- File counting: Glob for `*.png` instead of `*.jpg`

**data-platform/api.py**
- `/edge/upload-complete`: Log directory structure before encoding
- `/edge/train`: Log dataset path and status transitions
- Error handling: Store traceback in status for debugging

---

## v0.2.77 (2025-12-09) - Fix Config Parsing and AV1 Video Support

### Summary
Fixed config file parsing to handle inline comments, and added ffmpeg-based video extraction for AV1/H.265 codec support.

### Bug Fixes

1. **Config parsing with inline comments**: Values like `HOST="127.0.0.1"  # comment` were parsed incorrectly, including the comment
   - Now properly extracts only the quoted value
   - Handles both single and double quotes

2. **AV1 video codec not supported**: OpenCV couldn't decode AV1-encoded videos on many platforms
   - Now uses ffmpeg for frame extraction (better codec support)
   - Falls back to OpenCV if ffmpeg not available
   - Supports AV1, H.265, and other modern codecs

### Changes

**scripts/test_edge_workflow.py**
- `load_config_file()`: Fixed parsing to handle inline comments after quoted values
- `extract_frames_with_ffmpeg()`: New function using ffmpeg for video extraction
- `extract_frames_from_videos()`: Auto-detects ffmpeg, falls back to OpenCV

### Config File Format

Correct format (inline comments OK):
```bash
EDGE_SERVER_HOST="127.0.0.1"        # Server IP
EDGE_SERVER_USER="ubuntu"           # SSH user
EDGE_SERVER_PASSWORD="mypassword"   # SSH password
```

---

## v0.2.76 (2025-12-08) - Fix Edge API URL and Workflow Error Handling

### Summary
Fixed edge upload API URL defaulting to wrong address and improved workflow error handling.

### Bug Fixes

1. **Wrong API URL**: `edge_upload.py` had hardcoded `http://192.168.1.100:8000` instead of using `API_BASE_URL` from config
   - Now uses `API_BASE_URL` env var first, falls back to `EDGE_API_URL`, then `http://127.0.0.1:8000`

2. **False Success on Failure**: `test_edge_workflow.py` reported "WORKFLOW COMPLETED SUCCESSFULLY" even when encoding or training failed
   - Now properly tracks success/failure of each step
   - Reports "WORKFLOW FAILED" with specific failed steps

### Changes

**operating_platform/core/edge_upload.py**
- Changed default host from `192.168.1.100` to `127.0.0.1`
- Changed default user from `dorobot` to `nupylot`
- API URL now uses `API_BASE_URL` from environment (same as config file)

**scripts/test_edge_workflow.py**
- Track `encode_ok` and `train_ok` separately
- Only report success if all steps pass
- List which steps failed on error

---

## v0.2.75 (2025-12-08) - Simplified Edge Upload Path

### Summary
Changed default edge server upload path from `/data/dorobot/uploads` to `/uploaded_data` for cleaner organization.

### Changes

- `EDGE_SERVER_PATH` default changed to `/uploaded_data`
- Each upload creates subfolder: `/uploaded_data/{repo_id}/`
- Updated in:
  - `~/.dorobot_device.conf`
  - `scripts/run_so101.sh`
  - `operating_platform/core/edge_upload.py`

### Remote Structure

```
/uploaded_data/
  ├── test_edge_20251208_200120/
  │   ├── images/
  │   │   └── episode_000001/
  │   │       └── observation.image/
  │   │           ├── frame_000000.jpg
  │   │           └── ...
  │   └── meta/
  │       └── info.json
  └── test_edge_20251208_200530/
      └── ...
```

---

## v0.2.74 (2025-12-08) - Full Edge Workflow Test Script

### Summary
Added comprehensive test script for CLOUD_OFFLOAD=2 edge workflow that extracts frames from sample videos and tests the full pipeline: upload -> encode -> train.

### New Files

**scripts/test_edge_workflow.py**
- Extracts frames from sample video files to create raw image dataset
- Tests full edge upload workflow:
  1. Extract frames from videos to simulate raw data collection
  2. Upload raw images to edge server via SFTP (paramiko)
  3. Notify edge server to start encoding
  4. Trigger cloud training
- Reports upload speed, timing, and success/failure status
- Supports custom episode/frame limits

### Usage

```bash
# Full workflow test with sample data
python scripts/test_edge_workflow.py --source /Users/nupylot/Public/aimee-6283

# Test with 3 episodes, 30 frames each
python scripts/test_edge_workflow.py --source /path/to/data --episodes 3 --frames 30

# Connection test only (SSH + API)
python scripts/test_edge_workflow.py --test-connection

# Upload and encode only (skip training)
python scripts/test_edge_workflow.py --source /path/to/data --skip-training

# Keep temp data for inspection
python scripts/test_edge_workflow.py --source /path/to/data --keep-temp
```

---

## v0.2.73 (2025-12-08) - Edge Mode as Default

### Summary
Changed hardcoded defaults in run_so101.sh so fresh installs use edge mode by default.

### Changes

**scripts/run_so101.sh**
- Changed CLOUD_OFFLOAD default from 0 to 2 (edge mode)
- Changed EDGE_SERVER_HOST default from 192.168.1.100 to 127.0.0.1
- Changed EDGE_SERVER_USER default from dorobot to nupylot

### Rationale
On a fresh client install without `~/.dorobot_device.conf`, the script now uses edge mode by default. This ensures consistent behavior whether or not a config file exists.

---

## v0.2.72 (2025-12-08) - Device Config Default Values & Edge Upload Test

### Summary
Added support for loading default values from `~/.dorobot_device.conf` including edge server settings, API credentials, and cloud offload mode. Added test script for edge upload verification.

### Changes

**~/.dorobot_device.conf**
- Added edge server configuration defaults:
  - `EDGE_SERVER_HOST="127.0.0.1"`
  - `EDGE_SERVER_USER="nupylot"`
  - `EDGE_SERVER_PASSWORD` (for paramiko SFTP)
  - `EDGE_SERVER_PORT="22"`
  - `EDGE_SERVER_PATH="/data/dorobot/uploads"`
- Added cloud offload default: `CLOUD_OFFLOAD="2"` (edge mode)
- Added API server configuration:
  - `API_BASE_URL`
  - `API_USERNAME`
  - `API_PASSWORD`

**scripts/run_so101.sh**
- Restructured to load config file BEFORE setting defaults
- Config file values now become the defaults (not hardcoded values)
- Precedence: environment variables > config file > script defaults
- Added API_BASE_URL, API_USERNAME, API_PASSWORD variables
- Version bumped to 0.2.72

**scripts/test_edge_upload.py** (NEW)
- Test script for edge upload functionality verification
- Supports creating synthetic test datasets
- Can extract frames from existing videos for testing
- Tests SSH/SFTP connection with password authentication
- Reports upload speed and success/failure status

### Usage

```bash
# Test edge connection only
python scripts/test_edge_upload.py --test-connection

# Test upload with synthetic data
python scripts/test_edge_upload.py

# Test upload with existing dataset
python scripts/test_edge_upload.py --dataset /path/to/dataset

# Extract frames from videos and upload
python scripts/test_edge_upload.py --extract-from /path/to/videos
```

### Config File Precedence

Settings are applied in this order (later overrides earlier):
1. Script defaults (fallback values in run_so101.sh)
2. Config file (`~/.dorobot_device.conf`)
3. Environment variables (command-line overrides)

This means users can:
- Set permanent defaults in `~/.dorobot_device.conf`
- Override temporarily with environment variables

---

## v0.2.71 (2025-12-08) - Edge Upload Password Authentication

### Summary
Added password authentication support using paramiko for edge upload mode. This is simpler than SSH key authentication for initial setup.

### Changes

**operating_platform/core/edge_upload.py**
- Added optional `paramiko` import for password authentication
- Added `password` field to `EdgeConfig` dataclass
- Added `EDGE_SERVER_PASSWORD` environment variable support
- Added paramiko-based methods:
  - `_use_paramiko()`: Check if password auth should be used
  - `_get_ssh_client()`: Get/create paramiko SSH client
  - `_get_sftp()`: Get/create SFTP client
  - `_exec_remote_command()`: Execute commands via paramiko
  - `_sftp_upload_directory()`: Recursive SFTP upload
  - `close()`: Clean up SSH/SFTP connections
- Updated `test_connection()`, `create_remote_directory()`, `sync_dataset()` to use paramiko when password is set
- Falls back to rsync/SSH key auth when no password is set

**scripts/run_so101.sh**
- Added `EDGE_SERVER_PASSWORD` environment variable
- Exports password to edge_upload.py
- Updated usage documentation

**data-platform/train.py** (separate repo)
- Added edge server configuration constants:
  - `EDGE_SERVER_HOST`
  - `EDGE_SERVER_USER`
  - `EDGE_SERVER_PASSWORD`
  - `EDGE_SERVER_PORT`
  - `EDGE_SERVER_PATH`

### Usage

```bash
# Edge mode with password authentication
CLOUD_OFFLOAD=2 EDGE_SERVER_PASSWORD=mypassword bash scripts/run_so101.sh

# Or set all edge server settings
CLOUD_OFFLOAD=2 \
  EDGE_SERVER_HOST=192.168.1.200 \
  EDGE_SERVER_USER=admin \
  EDGE_SERVER_PASSWORD=secret \
  bash scripts/run_so101.sh
```

### Notes
- Password authentication uses paramiko SFTP (slower but simpler)
- SSH key authentication uses rsync (faster for large datasets)
- Install paramiko: `pip install paramiko`

---

## v0.2.70 (2025-12-08) - Edge Upload Mode (CLOUD_OFFLOAD=2)

### Summary
Added new edge upload mode that sends raw images to a local API server (edge server) via rsync for encoding, instead of encoding locally or uploading directly to cloud.

### Problem
Both local encoding (CLOUD_OFFLOAD=0) and direct cloud upload (CLOUD_OFFLOAD=1) have significant wait times:
- Local NPU encoding: ~2-5 minutes per episode
- Direct cloud upload (WAN): ~5 minutes per episode (720MB raw images at ~20 Mbps)

### Solution
Edge upload mode (CLOUD_OFFLOAD=2) uses rsync to transfer raw images to a local edge server on the same LAN:
- LAN transfer: ~6 seconds per episode (720MB at ~1 Gbps)
- Client continues recording immediately
- Edge server handles encoding + cloud upload in background

Time savings: ~5 minutes → ~6 seconds per episode (50x faster client wait time)

### New Files

**operating_platform/core/edge_upload.py**
- `EdgeConfig`: Configuration dataclass for edge server connection
- `EdgeUploader`: Main class for rsync upload and edge server communication
- `EdgeUploadThread`: Background thread for non-blocking uploads
- `run_edge_upload()`: Convenience function for edge upload workflow

**docs/edge_upload.md**
- Design document for edge upload feature
- Architecture diagram and time comparison
- Configuration and error handling documentation

### Changes

**operating_platform/core/main.py**
- Added offload mode constants: `OFFLOAD_LOCAL=0`, `OFFLOAD_CLOUD=1`, `OFFLOAD_EDGE=2`
- Added `test_edge_connection()` function for connection testing at startup
- Updated exit flow to handle edge upload mode separately from cloud mode
- Backward compatible with boolean `cloud_offload` values

**scripts/run_so101.sh**
- Added `CLOUD_OFFLOAD=2` support (edge mode)
- Added edge server environment variables:
  - `EDGE_SERVER_HOST` (default: 192.168.1.100)
  - `EDGE_SERVER_USER` (default: dorobot)
  - `EDGE_SERVER_PORT` (default: 22)
  - `EDGE_SERVER_PATH` (default: /data/dorobot/uploads)
- Updated help text and examples

### Usage

```bash
# Edge mode (fastest - rsync to edge server on same LAN)
CLOUD_OFFLOAD=2 bash scripts/run_so101.sh

# Edge mode with custom server
CLOUD_OFFLOAD=2 EDGE_SERVER_HOST=192.168.1.200 bash scripts/run_so101.sh

# Cloud mode (direct upload to cloud)
CLOUD_OFFLOAD=1 bash scripts/run_so101.sh

# Local mode (encode locally with NPU/CPU)
CLOUD_OFFLOAD=0 bash scripts/run_so101.sh
```

### CLOUD_OFFLOAD Mode Summary

| Value | Mode | Description |
|-------|------|-------------|
| 0 | Local | Encode locally (NPU/CPU), upload videos to cloud |
| 1 | Cloud | Skip encoding, upload raw images directly to cloud |
| 2 | Edge | Skip encoding, rsync to edge server for encoding |

### Edge Server Requirements
- SSH access from client
- rsync installed
- Write access to upload directory
- data-platform API with edge upload endpoints (`/edge/upload-complete`, `/edge/status/{repo_id}`, `/edge/train`)

---

## v0.2.62 (2025-12-07) - Fix Exit During Reset Phase

### Summary
Fixed video encoding being skipped when pressing 'e' during the reset phase (after pressing 'n' to save episode).

### Problem
When user pressed 'n' (save episode), then 'p' (reset), then 'e' (exit), the program exited immediately without waiting for video encoding. The logs showed:
```
[Daemon] Robot disconnected
[Cleanup] Releasing resources...
[Cleanup] OpenCV windows closed
[Cleanup] Daemon stopped
[Cleanup] Resources released
```
No encoding logs appeared, and no `videos/` folder was created.

### Root Cause
There were TWO separate 'e' key handlers in `main.py`:
1. **Line 359-365 (inside reset loop)**: Only called `daemon.stop()` and `return` - **missing video encoding wait**
2. **Line 428+ (main loop)**: Properly waited for `async_saver.stop(wait_for_completion=True)`

When 'e' was pressed during the reset phase (after 'n' but before 'p'), the first handler was triggered, bypassing all encoding.

### Solution
Updated the 'e' handler inside the reset loop (lines 359-418) to include proper cleanup:
1. Voice prompt for encoding status
2. Close camera display
3. Stop DORA daemon
4. Call `record.stop()` to finish recording
5. Call `record.async_saver.stop(wait_for_completion=True)` to wait for encoding
6. Show save statistics
7. Run cloud training if enabled

### Changes

**operating_platform/core/main.py**
- Expanded reset loop 'e' handler from 6 lines to ~60 lines
- Now matches the main loop 'e' handler behavior exactly
- Added proper logging for each exit step

---

## v0.2.61 (2025-12-06) - Default Settings & Auto Dataset Cleanup

### Summary
Changed default settings and added automatic dataset folder cleanup at start.

### Changes

**run_so101.sh**
- `CLOUD_OFFLOAD` default changed from `1` to `0` (local encoding by default)
- `USE_NPU` remains `1` by default (NPU enabled)

**operating_platform/core/main.py**
- Dataset folder is now always cleared at start of data collection
- Users no longer need to manually delete old data
- Prevents issues with incomplete/corrupted data from previous runs

### Default Mode
```
USE_NPU=1         # NPU enabled (for Ascend hardware)
CLOUD_OFFLOAD=0   # Local encoding (default)
```

To enable cloud mode:
```bash
CLOUD_OFFLOAD=1 bash scripts/run_so101.sh
```

---

## v0.2.60 (2025-12-06) - Launcher Improvements & Permission Fixes

### Summary
Added version display, improved controls documentation, fixed serial port permissions for both ttyACM0 and ttyACM1, and added permission validation before starting.

### Changes

**run_so101.sh**
1. Added version display in launcher header
2. Added missing controls to display:
   - 'p' - Proceed after robot reset
   - Ctrl+C - Emergency stop and exit
3. Added `check_device_permissions()` function that validates serial port permissions (777) before "All systems ready"
4. If permissions are wrong, shows clear error message with fix instructions and exits

**detect_usb_ports.py**
1. `set_device_permissions()` now always includes default devices:
   - `/dev/video0`, `/dev/video2`
   - `/dev/ttyACM0`, `/dev/ttyACM1`
2. Added `sudo usermod -aG dialout $USER` for serial port group access
3. Shows step-by-step progress (1/2: usermod, 2/2: chmod)

### Permission Check Output

When permissions are correct:
```
[STEP] Checking device permissions...
[INFO] Permission OK: /dev/ttyACM0 (777)
[INFO] Permission OK: /dev/ttyACM1 (777)
[INFO] All device permissions OK
```

When permissions are wrong:
```
[ERROR] Permission denied: /dev/ttyACM1 (current: 660, required: 777)

[ERROR] ==========================================
[ERROR]   PERMISSION ERROR - Cannot continue
[ERROR] ==========================================

Please run: bash scripts/detect.sh
```

---

## v0.2.58 (2025-12-06) - Fixed Default Device Paths

### Summary
Changed detect.sh to use fixed default device paths for single-arm systems. Users plug devices in a specific order to get consistent assignments.

### Device Plug Order
Plug devices in this order for correct assignment:
1. **Top camera** → `/dev/video0`
2. **Wrist camera** → `/dev/video2`
3. **Leader arm** → `/dev/ttyACM0`
4. **Follower arm** → `/dev/ttyACM1`

### Changes

**scripts/detect_usb_ports.py**
- Use fixed default paths instead of dynamic detection
- Simplified for single-arm system (removed ARM_LEADER2/FOLLOWER2)
- Config header now includes plug order instructions
- Detected devices shown as comments for reference

### Generated Config Example

```bash
# IMPORTANT: Plug devices in this order for correct assignment:
#   1. Top camera    -> /dev/video0
#   2. Wrist camera  -> /dev/video2
#   3. Leader arm    -> /dev/ttyACM0
#   4. Follower arm  -> /dev/ttyACM1

# === Camera Configuration ===
CAMERA_TOP_PATH="/dev/video0"
CAMERA_WRIST_PATH="/dev/video2"

# === Arm Configuration (Single Arm System) ===
ARM_LEADER_PORT="/dev/ttyACM0"
ARM_FOLLOWER_PORT="/dev/ttyACM1"

# === Detected Devices (for reference) ===
# Video: /dev/video0 - DSJ-2062-309
# Video: /dev/video2 - DSJ-2062-309
# Serial: /dev/ttyACM0 - USB Single Serial
# Serial: /dev/ttyACM1 - USB Single Serial
```

---

## v0.2.57 (2025-12-06) - Setup Script Update Mode & Lazy Rerun Imports

### Summary
Added `--update` flag to setup_env.sh for installing into existing conda environments, and made rerun-sdk an optional dependency with lazy imports.

### Changes

**setup_env.sh**
- Added `--update` flag to install into existing environment without recreating
- When environment exists: shows tip about `--update` option
- In update mode: skips conda create, uses existing environment
- Added mode indicator (CREATE vs UPDATE) in setup header

**setup_env_base.sh**
- Added `-y`/`--yes` flag to skip confirmation prompt (for CI/automation)
- Non-interactive mode logs when skipping confirmation

**Lazy Rerun Imports**
- `operating_platform/core/teleoperate.py`: Lazy import rerun and visualization utils
- `operating_platform/dataset/visual/visual_dataset.py`: Lazy import rerun
- Both files now only import rerun when the functionality is actually used
- Clear error message if rerun not installed: "Install it with: pip install rerun-sdk"

**Removed rerun-sdk from default installation**
- Removed `pip install rerun-sdk` from setup_env.sh and setup_env_base.sh
- Rerun is now optional - only needed for visualization features
- Added comment: "Note: Rerun SDK is optional - only needed for visualization"

### Usage

```bash
# Fresh install (default)
bash scripts/setup_env.sh

# Update existing environment
bash scripts/setup_env.sh --update

# Update with additional deps
bash scripts/setup_env.sh --update --training

# Non-interactive base install (CI)
conda activate myenv && bash scripts/setup_env_base.sh -y
```

### Benefits
- Faster reinstalls - no need to delete and recreate environment
- CI/automation friendly with `-y` flag
- Data collection works without rerun-sdk installed
- Clear error message when visualization features need rerun

---

## v0.2.56 (2025-12-06) - Detect.sh Mechanism & Lazy Rerun Imports

### Summary
Cherry-picked detect.sh mechanism from dev_310p_yingma for USB device detection with persistent paths and automatic permissions.

### Changes

**New: scripts/detect.sh**
- Simple wrapper that runs detect_usb_ports.py with --save --chmod

**scripts/detect_usb_ports.py**
- `--save` option to save config to `~/.dorobot_device.conf`
- `--chmod` option to run `sudo chmod 777` on detected devices
- Replaced OpenCV detection with v4l2-ctl/udevadm-based detection

**scripts/run_so101.sh**
- Loads device config from `~/.dorobot_device.conf` if exists
- Auto chmod 777 on devices at startup
- Environment variable exports for DORA YAML

**DORA YAML files**
- Use environment variables: `$CAMERA_TOP_PATH`, `$ARM_LEADER_PORT`, etc.

---

## v0.2.49 (2025-12-05) - Fix USB Video Device Detection

### Summary
Fixed `detect_usb_ports.py` not detecting video devices on Orange Pi and other systems where OpenCV can't open cameras directly.

### Problem
The script used OpenCV (`cv2.VideoCapture`) to verify video devices, which failed on Orange Pi even though the cameras work with other tools.

### Solution
Replace OpenCV-based detection with v4l2-ctl and udevadm-based detection:
1. Try `v4l2-ctl --device=/dev/videoX --all` to check for "Video Capture" capability
2. Fallback to `udevadm info` to check `ID_V4L_CAPABILITIES`
3. Final fallback: check if device exists and is readable

### Changes

**File: `scripts/detect_usb_ports.py`**
- Added `is_video_capture_device()` function using v4l2-ctl/udevadm
- Removed OpenCV dependency from video device detection
- More reliable detection on embedded systems

---

## v0.2.48 (2025-12-05) - Fix OpenCV GUI Support with conda-forge

### Summary
Fixed OpenCV GUI display issues by using conda-forge's OpenCV instead of pip's opencv-python.

### Problem
On systems with GUI display, running data collection fails with:
```
cv2.error: OpenCV(4.12.0) error: (-2:Unspecified error) The function is not implemented.
Rebuild the library with Windows, GTK+ 2.x or Cocoa support.
```

### Root Cause
The pip-installed `opencv-python` package has ffmpeg/PyAV version conflicts that cause `cv2.imshow` to hang or fail. This is a known issue in the LeRobot community (see [huggingface/lerobot#520](https://github.com/huggingface/lerobot/issues/520)).

### Solution
Use conda-forge's OpenCV package instead of pip's opencv-python. This is the proven solution from the LeRobot community:

```bash
conda install -y -c conda-forge ffmpeg
pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python
conda install -y -c conda-forge "opencv>=4.10.0"
```

### Changes

**File: `scripts/setup_env.sh`**
- Step 8: Install ffmpeg and OpenCV from conda-forge instead of pip

**File: `scripts/setup_env_base.sh`**
- Step 7: Install ffmpeg and OpenCV from conda-forge instead of pip

### Immediate Fix (for existing installations)

```bash
conda install -y -c conda-forge ffmpeg
pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python
conda install -y -c conda-forge "opencv>=4.10.0"
```

---

## v0.2.47 (2025-12-05) - Fix PyTorch/torchvision Version Conflicts

### Summary
Fixed PyTorch version conflicts caused by `lerobot[feetech]` or other packages installing incompatible torchvision versions.

### Problem
After running `pip install -e .` and `pip install 'lerobot[feetech]'`, the torchvision version gets overwritten to an incompatible version, causing runtime errors:
```
RuntimeError: operator torchvision::nms does not exist. We performed an exhaustive search over all registered ops, but could not find it. ...
This could be a bug in PyTorch which might occur if torchvision is installed with a different version of PyTorch.
```

### Root Cause
The `lerobot[feetech]` package (and possibly other dependencies) specifies torchvision constraints that override the manually installed `torchvision==0.20.1` with an incompatible version that doesn't match `torch==2.5.1`.

### Solution
Added Step 9.5 (in `setup_env.sh`) / Step 8.5 (in `setup_env_base.sh`) to reinstall the correct PyTorch versions **after** all other packages are installed:
- `torch==2.5.1`
- `torchvision==0.20.1`
- `torchaudio==2.5.1`
- `torch-npu==2.5.1` (if NPU mode)

This ensures version compatibility is maintained regardless of what other packages try to install.

### Changes

**File: `scripts/setup_env.sh`**
- Added Step 9.5: Reinstall PyTorch after all packages installed
- Reinstall torch-npu if using NPU device

**File: `scripts/setup_env_base.sh`**
- Added Step 8.5: Same fix for base environment setup script

### Impact
- NPU inference now works correctly with `torch-npu==2.5.1`
- No more `operator torchvision::nms does not exist` errors
- Package installation order no longer matters

---

## v0.2.46 (2025-12-05) - Fix OpenCV Crash on Headless Exit

### Summary
Fixed crash when pressing 'e' to exit on headless systems, which was preventing video encoding.

### Problem
On headless systems without GUI support (like OpenEuler embedded), `cv2.destroyAllWindows()` throws an exception:
```
OpenCV(4.12.0) error: (-2:Unspecified error) The function is not implemented. Rebuild the library with Windows, GTK+ 2.x or Cocoa support.
```
This exception caused the entire exit sequence to abort, skipping video encoding and leaving no `videos/` folder.

### Solution
Wrap OpenCV cleanup calls in try-except to gracefully handle headless systems. The error is logged at debug level and doesn't interrupt the save/encode workflow.

### Changes

**File: `operating_platform/core/main.py`**
- Wrap `cv2.destroyAllWindows()` in try-except at exit path
- Wrap `cv2.destroyAllWindows()` in try-except during reset abort
- Add terminal keyboard cleanup in abort path
- Log OpenCV errors at debug level (not error) since they're expected on headless

---

## v0.2.45 (2025-12-05) - Device Config File for Stable USB Ports

### Summary
Added automatic device configuration file support to solve USB/camera port instability between sessions.

### Problem
USB device paths (`/dev/video0`, `/dev/ttyACM0`) can change between recording sessions, inference runs, or reboots. This causes the system to connect to wrong cameras or arms.

### Solution
Added support for a device configuration file (`~/.dorobot_device.conf`) that stores persistent USB paths based on physical port location. This file is automatically loaded by `run_so101.sh`.

### Changes

**File: `scripts/detect_usb_ports.py`**
- Added `--save` option to generate device config file
- Added `--output` option to specify custom output path
- New `save_device_config()` function creates shell-sourceable config

**File: `scripts/run_so101.sh`**
- Added device config file loading (checks multiple locations)
- Config file locations (in order): `~/.dorobot_device.conf`, `/etc/dorobot/device.conf`, `$PROJECT_ROOT/.device.conf`
- Logs when config file is loaded
- Updated warnings to suggest `--save` option

### Workflow for Stable Ports

```bash
# 1. Connect all devices (cameras, arms) in your desired configuration
# 2. Run detection script to save persistent paths:
python scripts/detect_usb_ports.py --save

# 3. Config file created at ~/.dorobot_device.conf
# 4. run_so101.sh will automatically load this config
bash scripts/run_so101.sh
```

### Generated Config File Example

```bash
# ~/.dorobot_device.conf
# DoRobot Device Configuration
# Generated by: python scripts/detect_usb_ports.py --save

# === Camera Configuration ===
# /dev/video0 - USB_Camera
CAMERA_TOP_PATH="/dev/v4l/by-path/platform-xhci-hcd.0-usb-0:1:1.0-video-index0"

# /dev/video2 - USB_Camera
CAMERA_WRIST_PATH="/dev/v4l/by-path/platform-xhci-hcd.0-usb-0:2:1.0-video-index0"

# === Arm Configuration ===
# /dev/ttyACM0 - Feetech_Motor
ARM_LEADER_PORT="/dev/serial/by-path/platform-xhci-hcd.0-usb-0:3:1.0"

# /dev/ttyACM1 - Feetech_Motor
ARM_FOLLOWER_PORT="/dev/serial/by-path/platform-xhci-hcd.0-usb-0:4:1.0"
```

### Benefits
- Ports remain stable across reboots
- No need to reconnect devices in specific order
- One-time setup per device
- Works with both data collection and inference

---

## v0.2.44 (2025-12-05) - Terminal Keyboard Input for Headless Mode

### Summary
Added terminal-based keyboard input for headless systems without GUI. When `SHOW=0`, users can now press 'n', 'p', 'e' keys in the terminal to control recording.

### Problem
When running on headless systems (OpenEuler embedded, no GUI), `cv2.waitKey()` cannot capture keyboard input because it requires an OpenCV window. This made it impossible to interact with the recording system when `SHOW=0`.

### Solution
Added `TerminalKeyboard` class that uses `termios` to read raw keyboard input directly from the terminal (stdin) without requiring a GUI window.

### Changes

**New File: `operating_platform/utils/keyboard_input.py`**
- `TerminalKeyboard` class for non-blocking terminal keyboard input
- Uses `termios` and `select` for raw input on Linux/macOS
- `get_key_headless()` function as drop-in replacement for `cv2.waitKey()`

**File: `operating_platform/core/main.py`**
- Initialize terminal keyboard when `show_display=False`
- Use `get_key_headless()` instead of `cv2.waitKey()` in headless mode
- Proper cleanup of terminal keyboard on exit

### Usage
```bash
# Run in headless mode - keyboard input works in terminal
SHOW=0 bash scripts/run_so101.sh

# Press 'n' to save episode
# Press 'p' to proceed after reset
# Press 'e' to exit
```

### Notes
- Terminal must be a TTY (not piped input)
- Works on Linux and macOS
- Falls back gracefully if termios not available (Windows)

---

## v0.2.43 (2025-12-05) - Add LeRobot Feetech Support

### Summary
Added `lerobot[feetech]` installation to setup scripts for Feetech motor support.

### Changes

**Files: `scripts/setup_env.sh`, `scripts/setup_env_base.sh`**
- Added `pip install 'lerobot[feetech]'` step after SO101 arm component installation
- Re-numbered subsequent installation steps

---

## v0.2.42 (2025-12-05) - Always Start Fresh Dataset

### Summary
Changed data collection to always clear existing dataset directory on startup, preventing errors from corrupted/incomplete datasets from previous interrupted sessions.

### Problem
When the data collection script crashes or is interrupted, it may leave incomplete dataset files (e.g., missing `meta/tasks.jsonl`). On restart, the script would try to resume from this corrupted state, causing errors like:
```
FileNotFoundError: No such file or directory: '.../meta/tasks.jsonl'
```

### Solution
Always remove existing dataset directory and start fresh on each run. This ensures a clean slate without corrupted metadata.

### Changes

**File: `operating_platform/core/main.py`**
- Removed resume logic that checked for existing data
- Always clear existing dataset directory if non-empty
- Start fresh recording session every time

### Impact
- No more errors from corrupted/incomplete datasets
- Each `run_so101.sh` invocation starts with a clean dataset
- Previous data in the same repo_id will be deleted (use different REPO_ID to preserve old data)

### Usage Note
If you want to preserve data from a previous session, use a different `REPO_ID`:
```bash
REPO_ID=my-dataset-v2 bash scripts/run_so101.sh
```

---

## v0.2.41 (2025-12-05) - Add SHOW Parameter and Change CLOUD_OFFLOAD Default

### Summary
Added `SHOW` parameter for headless operation and changed `CLOUD_OFFLOAD` default to `0` (local encoding).

### Changes

**File: `scripts/run_so101.sh`**
- Changed `CLOUD_OFFLOAD` default from `1` to `0` (local encoding by default)
- Added `SHOW` parameter (default: `1`, set to `0` for headless systems)
- Updated help text and examples

**File: `operating_platform/core/record.py`**
- Added `display` field to `RecordConfig` (default: `True`)

**File: `operating_platform/core/main.py`**
- Use `show_display` flag that combines user setting with headless detection
- Conditionally create `CameraDisplay` only when display is enabled
- Updated all display loops to check `show_display`

**File: `README.md`**
- Updated environment variables documentation
- Added data collection examples with mode combinations
- Added mode summary table

### Usage Examples

```bash
# Default: Local encoding with camera display (NPU enabled)
bash scripts/run_so101.sh

# Headless mode (no camera display)
SHOW=0 bash scripts/run_so101.sh

# Cloud mode (upload to cloud for encoding)
CLOUD_OFFLOAD=1 bash scripts/run_so101.sh

# Headless + cloud mode
SHOW=0 CLOUD_OFFLOAD=1 bash scripts/run_so101.sh
```

### Mode Summary

| SHOW | CLOUD_OFFLOAD | Result |
|------|---------------|--------|
| 1 | 0 | Camera display + local NPU encoding (default) |
| 0 | 0 | Headless + local NPU encoding |
| 1 | 1 | Camera display + cloud upload |
| 0 | 1 | Headless + cloud upload |

---

## v0.2.40 (2025-12-04) - Fix PyTorch Install for ARM64/aarch64

### Summary
Fixed PyTorch installation on ARM64 architecture (Orange Pi, aarch64, OpenEuler).

### Problem
PyTorch CPU index (`https://download.pytorch.org/whl/cpu`) doesn't have ARM64 builds for version 2.5.1. The script failed with:
```
ERROR: Could not find a version that satisfies the requirement torch==2.5.1
```

### Solution
Detect architecture and use PyPI directly for ARM64 (which has ARM64 wheels), while keeping the CPU index for x86_64.

### Changes

**Files: `scripts/setup_env.sh`, `scripts/setup_env_base.sh`**
- Detect architecture with `uname -m`
- ARM64/aarch64: Install from PyPI directly (no `--index-url`)
- x86_64: Continue using `--index-url https://download.pytorch.org/whl/cpu`

---

## v0.2.39 (2025-12-04) - Disable Update Repos During Install

### Summary
Prevent dnf/yum from refreshing update repositories during package installation on OpenEuler/RHEL.

### Changes

**Files: `scripts/setup_env.sh`, `scripts/setup_env_base.sh`**
- Add `--disablerepo=*update*` to dnf/yum commands
- Add `--setopt=install_weak_deps=False` to dnf for faster install
- Fallback to normal install if package not found in base repos

This prevents the slow metadata refresh from update repos during installation.

---

## v0.2.38 (2025-12-04) - Base Environment Setup Script

### Summary
Added `setup_env_base.sh` script that installs into the current conda environment instead of creating a new one.

### Changes

**New File: `scripts/setup_env_base.sh`**
- Installs all dependencies into the current active conda environment
- No new conda environment created
- Same options as `setup_env.sh`: `--device`, `--npu`, `--training`, etc.
- Confirms before installing to avoid accidental modifications
- Supports apt, dnf, and yum package managers

### Usage
```bash
conda activate base
bash scripts/setup_env_base.sh --npu
```

---

## v0.2.36 (2025-12-04) - OpenEuler/RHEL Package Manager Support

### Summary
Added support for OpenEuler, Fedora, RHEL, and CentOS in the environment setup script.

### Changes

**File: `scripts/setup_env.sh`**
- Auto-detect package manager (apt, dnf, yum)
- Support for Debian/Ubuntu (apt): `speech-dispatcher`, `portaudio19-dev`
- Support for OpenEuler/Fedora/RHEL 8+ (dnf): `speech-dispatcher`, `portaudio-devel`, `gcc`, `gcc-c++`, `make`
- Support for CentOS/RHEL 7 (yum): same packages as dnf
- Fallback message for unknown package managers

### Supported Distributions
- Debian/Ubuntu (apt)
- OpenEuler (dnf/yum)
- Fedora (dnf)
- RHEL 8+ (dnf)
- CentOS/RHEL 7 (yum)

---

## v0.2.35 (2025-12-04) - Persistent USB Port Configuration

### Summary
Added persistent USB port configuration to ensure device paths remain stable across episodes and cable reconnections.

### Problem
When starting new episode data collection, USB and video ports change (e.g., `/dev/video0` becomes `/dev/video2`, `/dev/ttyACM0` becomes `/dev/ttyACM1`). This indicates resources are not fully released, or Linux kernel assigns different device numbers.

### Solution
Use persistent device paths based on USB topology instead of kernel-assigned indices:
- Cameras: `/dev/v4l/by-path/...` instead of `/dev/video0`
- Serial: `/dev/serial/by-path/...` or `/dev/serial/by-id/...` instead of `/dev/ttyACM0`

These paths are based on physical USB port location, not enumeration order.

### Changes

**New File: `scripts/detect_usb_ports.py`**
- Utility script to detect USB devices and display persistent paths
- `--yaml` flag outputs ready-to-use YAML configuration
- `--watch` flag monitors device changes in real-time

**File: `operating_platform/robot/components/camera_opencv/main.py`**
- Support for device path strings (not just numeric indices)
- Accepts `/dev/v4l/by-path/...` paths in `CAPTURE_PATH`
- Logs symlink resolution for debugging
- Retry logic on initial camera open failure

**File: `operating_platform/robot/robots/so101_v1/dora_teleoperate_dataflow.yml`**
- Added documentation header explaining port stability issue
- Added example persistent paths as comments for cameras and arms

**File: `CLAUDE.md`**
- Added persistent USB port configuration documentation

### Usage
```bash
# Detect your device paths (run on Orange Pi)
python scripts/detect_usb_ports.py --yaml

# Update dora_teleoperate_dataflow.yml with persistent paths:
# CAPTURE_PATH: "/dev/v4l/by-path/platform-xhci-hcd.0-usb-0:1:1.0-video-index0"
# PORT: "/dev/serial/by-path/platform-xhci-hcd.0-usb-0:2:1.0"
```

---

## V25 (2025-11-29) - USB Port & ZeroMQ Socket Cleanup

### Summary
Fixed USB port and ZeroMQ socket resource leaks that caused video device numbers to increment after each data collection session.

### Problem
After completing data collection and starting a second round, video port numbers increase (e.g., `/dev/video0` becomes `/dev/video2`), indicating the USB camera ports were not properly released. Similarly, ttyACM* devices may remain locked.

### Root Cause
1. ZeroMQ sockets created at module import time were never closed
2. No signal handlers for graceful cleanup on Ctrl+C or normal exit
3. `disconnect()` didn't release ZeroMQ context and sockets

### Solution

**1. Lazy ZeroMQ Initialization (manipulator.py)**
- Changed from module-level socket creation to lazy initialization
- `_init_zmq()` called in `connect()` - sockets created only when needed
- `_cleanup_zmq()` called in `disconnect()` - properly closes sockets and context

**2. Signal Handlers (main.py)**
- Added `signal.SIGINT` and `signal.SIGTERM` handlers
- Added `atexit.register()` for cleanup on any exit path
- Global `_daemon` reference for cleanup access
- `cleanup_resources()` ensures daemon.stop() is called once

**3. Improved Disconnect (manipulator.py)**
- Thread join with timeout (prevents hanging)
- ZeroMQ socket close with `linger=0` (immediate close)
- Context termination
- Clear received data buffers

### Changes

**File: `operating_platform/robot/robots/so101_v1/manipulator.py`**
- Added `_init_zmq()` for lazy socket initialization
- Added `_cleanup_zmq()` for proper socket/context cleanup
- Updated `connect()` to call `_init_zmq()`
- Updated `disconnect()` to call `_cleanup_zmq()` and clear buffers
- Added null checks in receiver threads for socket availability

**File: `operating_platform/core/main.py`**
- Added `signal` and `atexit` imports
- Added `cleanup_resources()` function
- Added `signal_handler()` for SIGINT/SIGTERM
- Register cleanup handlers in `main()`
- Store daemon reference globally for cleanup access

### Expected Behavior
- Video ports remain consistent across collection sessions
- No more `/dev/video0` -> `/dev/video2` jumps
- Clean exit on Ctrl+C or 'e' key
- ZeroMQ sockets properly released

---

## V24 (2025-11-29) - NPU Video Encoder Fallback

### Summary
Fixed video encoding failure on Ascend NPU when encoding many episodes due to hardware channel exhaustion.

### Problem
When collecting 10+ episodes, video encoding fails with:
```
Failed to create venc channel, ret is -1610055668
Error initializing output stream 0:0
```

### Root Cause
The Ascend NPU has limited video encoding channels (typically 2-4). When encoding multiple episodes simultaneously during async save, all channels become exhausted, causing `h264_ascend` encoder to fail.

### Solution
Added automatic fallback to `libx264` software encoder when NPU hardware encoder fails:
1. Detect NPU channel exhaustion errors (exit code != 0, "Failed to create venc channel" in stderr)
2. Automatically retry with `libx264` software encoder
3. Log warning about fallback for debugging

### Changes

**File: `operating_platform/utils/video.py`**
- Refactored `encode_video_frames()` to use helper function `_build_ffmpeg_cmd()`
- Added try/except around ffmpeg subprocess call
- Detect NPU errors: "Failed to create venc channel" or "Error initializing output stream"
- Automatic fallback to `libx264` when NPU fails
- Capture ffmpeg stderr for better error diagnostics

```python
try:
    subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True)
except subprocess.CalledProcessError as e:
    if vcodec == "h264_ascend" and "Failed to create venc channel" in str(e.stderr):
        logging.warning(f"NPU encoder failed, falling back to libx264")
        # Build and run fallback command with libx264
        ...
```

### Impact
- 10+ episode collections now complete successfully on Ascend NPU
- Software fallback may be slower but ensures data is not lost
- Users see warning log when fallback occurs

---

## V23 (2025-11-28) - Unified Environment & UX Improvements

### Summary
Major UX overhaul with single-command startup, unified environment setup, combined camera visualization, and NPU support for Ascend hardware.

### Changes

**UX Improvement 1: Single-Command Startup**
- New unified launcher script `scripts/run_so101.sh` starts both DORA dataflow and CLI automatically
- Proper startup order: DORA first, then CLI after ZeroMQ sockets are ready
- Automatic cleanup of stale socket files from previous runs
- Graceful shutdown of both processes on exit (Ctrl+C or 'e' key)
- Configurable timeouts via environment variables

**UX Improvement 2: Combined Camera Visualization**
- New `CameraDisplay` class (`operating_platform/utils/camera_display.py`) combines all camera feeds into single window
- Horizontal layout with camera labels for easy identification
- Removes window clutter from multiple separate camera windows
- Consistent window positioning

**UX Improvement 3: Unified Environment Setup**
- New `scripts/setup_env.sh` creates single `dorobot` conda environment
- Supports multiple device types: CPU, CUDA 11.8/12.1/12.4, Ascend NPU
- Optional dependency groups: training, simulation, tensorflow, all
- Automatic installation of SO101 robot components and dependencies

**NPU Support (Ascend 310B)**
- Added torch-npu integration for Ascend AI processors
- CANN toolkit environment sourcing in launcher script
- Tested on Orange Pi AI Pro 20T development board

**File Changes:**
- New: `scripts/run_so101.sh` - Unified launcher
- New: `scripts/setup_env.sh` - Environment setup script
- New: `operating_platform/utils/camera_display.py` - Combined camera display
- New: `docs/DESIGN_UX_IMPROVEMENTS.md` - UX design document
- Modified: `operating_platform/robot/robots/so101_v1/manipulator.py` - NPU compatibility
- Modified: `pyproject.toml` - Optional dependency groups, NPU packages
- Modified: `README.md` - Updated documentation

---

## V22 (2025-11-28) - Timestamp & Logging Cleanup

### Changes
- Fixed timestamp calculation in `add_frame()` to always use frame_index/fps for consistency
- Added timestamp validation with monotonic increasing check
- Cleaned up verbose Chinese debug print statements in `remove_episode()`
- Replaced print() with logging.info()/warning() throughout dataset module

**File: `operating_platform/dataset/dorobot_dataset.py`**
- Line ~890: Calculate timestamp from frame_index, ignore frame dict timestamp
- Line ~895: Added validation for monotonically increasing timestamps
- Line ~1035: Cleaned up `remove_episode()` debug output

---

## V21 (2025-11-28) - Video Encoder Logging

### Changes
- Added progress logging for video encoding with timing info
- Skip message for already-encoded videos during resume

**File: `operating_platform/dataset/dorobot_dataset.py`**
- Line ~1219: Added `[VideoEncoder] Encoding N videos for episode X...` log
- Line ~1235: Added elapsed time logging after encoding complete

---

## V20 (2025-11-28) - Exit Sequence Fix

### Changes
- Fixed exit sequence to stop DORA daemon FIRST before waiting for async saves
- Prevents ARM hardware errors during save operations
- Async saver properly shutdown with `stop(wait_for_completion=True)`

**File: `operating_platform/core/main.py`**
- Line ~300: Stop daemon before saving (disconnect hardware gracefully)
- Line ~320: Use `async_saver.stop()` instead of just `wait_all_complete()`

---

## V19 (2025-11-28) - Recording Workflow Simplification

### Changes
- Merged 'n' (next episode) and 'p' (proceed after reset) key actions
- 'n' now saves immediately and starts new episode without reset prompt
- Removed reset timeout loop - continuous recording flow
- Added voice prompt: "Recording episode N" after save

**File: `operating_platform/core/main.py`**
- Line ~280: 'n' key now calls `record.save()` and immediately restarts
- Removed: Reset wait loop with 'p' key confirmation
- Removed: 60-second auto-proceed timeout

---

## V18 (2025-11-28) - Voice Prompts

### Changes
- Added voice prompts for recording state changes using existing `log_say()` function
- "Ready to start. Press N to save and start next episode."
- "Recording episode N."
- "End collection. Please wait for video encoding."

**File: `operating_platform/core/main.py`**
- Line ~270: Voice prompt on recording start
- Line ~295: Voice prompt on new episode
- Line ~305: Voice prompt on exit

---

## V17 (2025-11-28) - USB Port Cleanup & Hardware Handling

### Summary
Major reliability improvements for hardware disconnection and cleanup on exit.

### Problem 1: USB ports not released on exit
When the program exits (Ctrl+C, 'e' key, or crash), USB ports for cameras and robot arms remain locked, requiring physical reconnection.

### Problem 2: ARM errors during save
Robot arm communication errors occur during async save because hardware wasn't properly disconnected.

### Problem 3: ZeroMQ timeout spam
Console flooded with "Dora ZeroMQ Received Timeout" messages during normal polling.

### Changes

**File: `operating_platform/robot/components/camera_opencv/main.py`**
- Added signal handlers (SIGINT/SIGTERM) and atexit cleanup
- VideoCapture properly released on any exit path
- Global `_video_capture` reference for cleanup access

**File: `operating_platform/robot/components/arm_normal_so101_v1/main.py`**
- Added signal handlers and atexit cleanup for FeetechMotorsBus
- Disconnect with `disable_torque=True` on exit
- Proper cleanup on STOP event

**File: `operating_platform/robot/robots/so101_v1/dora_zeromq.py`**
- Added ZeroMQ socket and context cleanup on exit
- Signal handlers for graceful shutdown
- Removed timeout log messages (normal polling behavior)

**File: `operating_platform/robot/robots/aloha_v1_TODO/dora_zeromq.py`**
- Removed "Dora ZeroMQ Received Timeout" log message

**File: `operating_platform/robot/robots/pika_v1_TODO/manipulator.py`**
- Removed timeout log messages for Pika, VIVE, and Gripper receivers

**File: `operating_platform/core/daemon.py`**
- `stop()` now actually disconnects robot hardware
- Checks `robot.is_connected` before disconnect
- Proper error handling for disconnect failures

**File: `operating_platform/utils/video.py`**
- Converted print() to logging.info() for better visibility

---

## V16 (2025-11-27) - Shared Resource & Timeout Fixes

### Problem 1: Images not written for episodes after episode 0
After V15 fix, no errors appeared but:
- Episode 0 images exist (~1700 files)
- Episodes 1-9 have directories but 0 images
- `total_episodes: 0` - no saves completed
- Missing `data/` and `videos/` folders

### Root Cause 1
`save_episode()` unconditionally calls `stop_audio_writer()` at line 957.
When async worker processes episode 0's save on the SHARED dataset object,
it stops the audio_writer while the recording thread is still recording
episodes 1-9. This breaks the shared resource.

### Problem 2: `wait_all_complete()` timeout doesn't work
The timeout parameter was ineffective because `queue.join()` in Python
has no timeout parameter - the check only happens AFTER join() returns.

### Problem 3: Image write errors silently swallowed
`write_image()` just prints errors without proper logging, making debugging difficult.

### Changes

**File: `operating_platform/dataset/dorobot_dataset.py`**

1. Only stop audio writer in synchronous mode:
```python
# Line ~957-963
# IMPORTANT: Only stop audio writer in synchronous mode (episode_data is None)
# When called from async worker (episode_data provided), the recording thread
# is still recording and using the shared audio_writer. Stopping it here would
# break audio recording for subsequent episodes.
if not episode_data:
    self.stop_audio_writer()
    self.wait_audio_writer()
```

**File: `operating_platform/core/async_episode_saver.py`**

2. Fixed `wait_all_complete()` to use polling with actual timeout:
```python
# Line ~421-444
if timeout:
    # NOTE: queue.join() doesn't have a timeout parameter!
    # We use polling instead to implement proper timeout behavior.
    poll_interval = 0.5
    while True:
        with self._lock:
            pending = len(self._pending_saves)
            queue_size = self.save_queue.qsize()

        if pending == 0 and queue_size == 0:
            break

        elapsed = time.time() - start_time
        if elapsed > timeout:
            logging.warning(...)
            return False

        time.sleep(poll_interval)
```

**File: `operating_platform/dataset/image_writer.py`**

3. Improved error logging in `write_image()`:
```python
# Line ~71-84
def write_image(image: np.ndarray | PIL.Image.Image, fpath: Path):
    import logging
    try:
        ...
    except Exception as e:
        # Log error with full traceback for debugging
        import traceback
        logging.error(f"[ImageWriter] Failed to write image {fpath}: {e}\n{traceback.format_exc()}")
```

---

## V15 (2025-11-27) - Race Condition Fix

### Problem
Episode saves occasionally fail with column length mismatch:
```
pyarrow.lib.ArrowInvalid: Column 2 named timestamp expected length 436 but got length 437
```

### Root Cause
Race condition between recording thread and save_async():
1. Recording thread (`process()`) continuously calls `add_frame()`
2. `save_async()` captures buffer reference
3. Before deep copy completes, recording thread adds another frame
4. Result: `size` counter doesn't match actual list lengths

### Changes

**File: `operating_platform/core/record.py`**

1. Added buffer lock in `__init__`:
```python
# Line ~133-135
# Lock to protect buffer swap during save_async (prevents race condition
# where recording thread adds frame while buffer is being captured)
self._buffer_lock = threading.Lock()
```

2. Use lock in `process()` around `add_frame()`:
```python
# Line ~225-227
# Use lock to prevent race condition with save_async buffer swap
with self._buffer_lock:
    self.dataset.add_frame(frame, self.record_cfg.single_task)
```

3. Use lock in `save_async()` for atomic buffer swap:
```python
# Line ~267-279
import copy

# CRITICAL: Use lock to atomically capture buffer and swap to new one
# This prevents the recording thread from adding frames during the swap
with self._buffer_lock:
    current_ep_idx = self.dataset.episode_buffer.get("episode_index", "?")
    logging.info(f"[Record] Queueing episode {current_ep_idx} for async save...")

    # Deep copy the buffer INSIDE the lock (before recording thread can add more frames)
    buffer_copy = copy.deepcopy(self.dataset.episode_buffer)

    # Create new episode buffer INSIDE the lock
    self.dataset.episode_buffer = self._create_new_episode_buffer()

# Queue save task with the copied buffer (outside lock to minimize lock hold time)
metadata = self.async_saver.queue_save(
    episode_buffer=buffer_copy,  # Pass the COPY, not the live buffer
    ...
)
```

---

## V14 (2025-11-27) - Dynamic Timeout Fix

### Problem
Long recordings (20+ seconds) fail because image write timeout (60s) is too short.
Log showed image writer taking 10+ minutes for longer recordings.

### Root Cause
Fixed 60 second timeout in `_wait_episode_images()` insufficient for episodes with many frames.

### Changes

**File: `operating_platform/dataset/dorobot_dataset.py`**

Changed `_wait_episode_images()` timeout from fixed 60s to dynamic calculation:
```python
# Line ~1154-1189
def _wait_episode_images(self, episode_index: int, episode_length: int, timeout_s: float | None = None) -> None:
    """
    Wait for a specific episode's images to be written.
    ...
    Args:
        ...
        timeout_s: Maximum time to wait in seconds. If None, calculates dynamically
                   based on episode length and number of cameras.
    """
    ...
    # Calculate dynamic timeout if not specified
    # Allow 0.5 seconds per image as a conservative estimate, with a minimum of 120 seconds
    # For a 20 second recording at 30fps with 2 cameras: 600 frames * 2 cameras * 0.5s = 600 seconds
    if timeout_s is None:
        num_images = episode_length * len(camera_keys)
        timeout_s = max(120.0, num_images * 0.5)
    ...
```

---

## V13 (2025-11-27) - Assertion & Image Writer Fixes

### Problem 1: Assertion Errors
```
AssertionError: len(video_files) == self.num_episodes * len(self.meta.video_keys)
```

### Root Cause 1
Global file count assertions fail with async save because:
- Episodes can be saved out of order
- Failed saves leave gaps in file counts
- Retries mean temporary inconsistencies

### Problem 2: Image File Not Found / Truncated
```
FileNotFoundError: [Errno 2] No such file or directory: '.../frame_000000.png'
OSError: image file is truncated
```

### Root Cause 2
Async saves started processing before image_writer finished writing all queued images.

### Changes

**File: `operating_platform/dataset/dorobot_dataset.py`**

1. Replaced global file count assertions with per-episode checks:
```python
# Line ~984-996 (REMOVED old assertions)
# OLD CODE (REMOVED):
# if len(self.meta.video_keys) > 0:
#     video_files = list(self.root.rglob("*.mp4"))
#     assert len(video_files) == self.num_episodes * len(self.meta.video_keys)
# parquet_files = list(self.root.rglob("*.parquet"))
# assert len(parquet_files) == self.num_episodes

# NEW CODE:
# NOTE: Removed file count assertions for async save compatibility.
# With async save, episodes may be saved out of order or have failed saves,
# so total file counts may not match num_episodes. Instead, we just verify
# that THIS episode's files were created successfully.
episode_parquet = self.root / self.meta.get_data_file_path(ep_index=episode_index)
if not episode_parquet.exists():
    raise RuntimeError(f"Failed to create parquet file for episode {episode_index}: {episode_parquet}")

if len(self.meta.video_keys) > 0:
    for key in self.meta.video_keys:
        episode_video = self.root / self.meta.get_video_file_path(episode_index, key)
        if not episode_video.exists():
            raise RuntimeError(f"Failed to create video file for episode {episode_index}: {episode_video}")
```

**File: `operating_platform/core/record.py`**

2. Added image_writer wait in `stop()`:
```python
# Line ~235-240
def stop(self):
    if self.running == True:
        self.running = False
        self.thread.join()
        self.dataset.stop_audio_writer()

    # CRITICAL: Wait for image_writer to finish ALL queued images BEFORE async saves
    # Without this, async saves will fail because images haven't been written yet
    if self.dataset.image_writer is not None:
        logging.info("[Record] Waiting for image_writer to complete all pending images...")
        self.dataset.image_writer.wait_until_done()
        logging.info("[Record] Image writer finished")
    ...
```

---

## V12 (2025-11-27) - Retry Failure Fix

### Problem
Retry attempts fail with:
```
KeyError: 'size' key not found in episode_buffer
```

### Root Cause
`save_episode()` uses `.pop()` to extract `size` and `task` from buffer:
```python
episode_length = episode_buffer.pop("size")  # Permanently removes key!
tasks = episode_buffer.pop("task")
```
When async saver retries a failed save, these keys are already gone.

### Changes

**File: `operating_platform/dataset/dorobot_dataset.py`**

Added deep copy at start of `save_episode()`:
```python
# Line ~910-934
def save_episode(self, episode_data: dict | None = None) -> int:
    import copy

    if episode_data:
        # IMPORTANT: Deep copy to preserve original buffer for retry compatibility.
        # The async saver may retry failed saves, and we use .pop() below which
        # modifies the buffer. Without this copy, retries would fail with
        # "size key not found in episode_buffer" because keys were already popped.
        episode_buffer = copy.deepcopy(episode_data)
    else:
        episode_buffer = self.episode_buffer

    validate_episode_buffer(episode_buffer, self.meta.total_episodes, self.features)

    # size and task are special cases that won't be added to hf_dataset
    episode_length = episode_buffer.pop("size")
    tasks = episode_buffer.pop("task")
    ...
```

---

## Summary Table

| Version | Issue | File | Fix |
|---------|-------|------|-----|
| V12 | Retry fails (`size key not found`) | dorobot_dataset.py | Deep copy in save_episode() |
| V13 | Image not found / truncated | record.py | Wait for image_writer in stop() |
| V13 | Assertion errors (file counts) | dorobot_dataset.py | Per-episode file checks |
| V14 | Timeout for long recordings | dorobot_dataset.py | Dynamic timeout calculation |
| V15 | Race condition (column mismatch) | record.py | Lock for atomic buffer swap |
| V16 | Shared audio_writer stopped | dorobot_dataset.py | Only stop in sync mode |
| V16 | `wait_all_complete()` timeout broken | async_episode_saver.py | Use polling with timeout |
| V16 | Image write errors silent | image_writer.py | Proper logging |
| V17 | USB ports not released on exit | camera_opencv, arm_so101, dora_zeromq | Signal handlers + atexit cleanup |
| V17 | ARM errors during save | daemon.py | Proper robot disconnect |
| V17 | ZeroMQ timeout log spam | dora_zeromq.py, manipulator.py | Remove timeout log messages |
| V18 | No audio feedback | main.py | Voice prompts via log_say() |
| V19 | Reset prompt interrupts flow | main.py | Remove reset loop, 'n' saves directly |
| V20 | ARM errors on exit | main.py | Stop daemon FIRST before async saves |
| V21 | No encoding progress info | dorobot_dataset.py | Video encoder logging with timing |
| V22 | Timestamp sync errors | dorobot_dataset.py | Calculate from frame_index/fps |
| V22 | Verbose Chinese debug output | dorobot_dataset.py | Replace print() with logging |
| V23 | Two-step startup process | scripts/run_so101.sh | Single-command unified launcher |
| V23 | Multiple camera windows | camera_display.py | Combined camera visualization |
| V23 | Complex environment setup | scripts/setup_env.sh | Unified setup with device options |
| V23 | No NPU support | pyproject.toml, manipulator.py | Ascend NPU integration |
| V24 | NPU encoder channel exhaustion | video.py | Auto fallback to libx264 |
| V25 | USB port leak (video devices) | manipulator.py, main.py | Lazy ZMQ init + signal handlers |

---

## Test Results

| Version | Episodes | Completed | Failed | Notes |
|---------|----------|-----------|--------|-------|
| V12 | 6 | 1 | 5 | Multiple error types |
| V13 | 6 | 1 | 5 | Still old assertions |
| V14 | 7 | 6 | 1 | Race condition on episode 5 |
| V15 | 10 | 0 | 10 | No errors but no saves (shared resource issue) |
| V16 | 10 | 10 | 0 | All episodes saved successfully |
| V17 | 10 | 10 | 0 | USB ports properly released |
| V18-V22 | - | - | - | Incremental improvements |
| V23 | 10 | 10 | 0 | Full workflow verified with unified launcher |
| V24 | 10+ | TBD | TBD | NPU fallback to libx264 when channels exhausted |
| V25 | TBD | TBD | TBD | USB ports should remain consistent across sessions |

---

## Rollback Instructions

To rollback to a specific version, revert the changes listed for that version and all subsequent versions.

### Rollback V25 -> V24
1. In `manipulator.py`, restore module-level ZMQ socket creation
2. Remove `_init_zmq()` and `_cleanup_zmq()` functions
3. In `main.py`, remove signal handlers and atexit registration
4. Remove `cleanup_resources()` function

### Rollback V24 -> V23
1. In `video.py`, remove `_build_ffmpeg_cmd()` helper function
2. In `video.py`, remove try/except fallback logic in `encode_video_frames()`
3. Restore direct subprocess.run() call without capture_output

### Rollback V23 -> V22
1. Remove `scripts/run_so101.sh` and `scripts/setup_env.sh`
2. Remove `operating_platform/utils/camera_display.py`
3. Remove `docs/DESIGN_UX_IMPROVEMENTS.md`
4. Revert `main.py` camera display changes (restore individual `cv2.imshow()` per camera)
5. Revert `pyproject.toml` optional dependency groups and NPU packages

### Rollback V22 -> V21
1. In `dorobot_dataset.py`, revert timestamp calculation to use frame dict timestamp
2. Restore Chinese debug print statements in `remove_episode()`

### Rollback V21 -> V20
1. In `dorobot_dataset.py`, remove video encoder timing/logging messages

### Rollback V20 -> V19
1. In `main.py`, move `daemon.stop()` back after async saves complete
2. Use `wait_all_complete()` instead of `async_saver.stop()`

### Rollback V19 -> V18
1. In `main.py`, restore reset wait loop with 'p' key confirmation
2. Restore 60-second auto-proceed timeout
3. Separate 'n' key behavior (don't save, just end episode)

### Rollback V18 -> V17
1. Remove `log_say()` voice prompt calls from `main.py`

### Rollback V17 -> V16
1. Remove signal handlers and atexit cleanup from `camera_opencv/main.py`
2. Remove signal handlers and atexit cleanup from `arm_normal_so101_v1/main.py`
3. Remove signal handlers and cleanup from `so101_v1/dora_zeromq.py`
4. Restore ZeroMQ timeout log messages in `dora_zeromq.py`, `manipulator.py`
5. In `daemon.py`, revert `stop()` to empty pass statement
6. In `video.py`, change `logging.info()` back to `print()`

### Rollback V16 -> V15
1. In `dorobot_dataset.py`, remove the `if not episode_data:` condition around `stop_audio_writer()`/`wait_audio_writer()`
2. In `async_episode_saver.py`, restore `queue.join()` in `wait_all_complete()` instead of polling
3. In `image_writer.py`, change `logging.error()` back to `print()`

### Rollback V15 -> V14
Remove the `_buffer_lock` and associated `with self._buffer_lock:` blocks from `record.py`.

### Rollback V14 -> V13
Change `_wait_episode_images()` timeout back to `timeout_s: float = 60.0` and remove the dynamic calculation.

### Rollback V13 -> V12
1. Restore global file count assertions in `dorobot_dataset.py`
2. Remove `image_writer.wait_until_done()` from `record.py` stop()

### Rollback V12 -> Original
Remove `copy.deepcopy()` from `save_episode()`.
