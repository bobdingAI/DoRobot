# DoRobot

> Dora LeRobot Version - A robotics operating platform for robot control, data collection, and policy training.

## Quick Start

### Get the Project

```bash
git clone https://github.com/dora-rs/DoRobot.git
cd DoRobot
```

### Automated Environment Setup (Recommended)

Use the setup script to create a unified conda environment with all dependencies:

```bash
# Core only - for data collection (fastest install)
bash scripts/setup_env.sh

# With training dependencies (for policy training)
bash scripts/setup_env.sh --training

# With CUDA support
bash scripts/setup_env.sh --cuda 12.4

# With CUDA + training
bash scripts/setup_env.sh --cuda 12.4 --training

# With Ascend NPU support (310B)
bash scripts/setup_env.sh --npu

# NPU + training
bash scripts/setup_env.sh --npu --training

# All dependencies
bash scripts/setup_env.sh --all
```

**Setup Options:**

| Option | Description |
|--------|-------------|
| `--name NAME` | Environment name (default: dorobot) |
| `--python VER` | Python version (default: 3.11) |
| `--device DEVICE` | Device: cpu, cuda11.8, cuda12.1, cuda12.4, npu |
| `--cuda VER` | CUDA version shorthand (11.8, 12.1, 12.4) |
| `--npu` | Enable Ascend NPU support |
| `--torch-npu VER` | torch-npu version (default: 2.5.1) |
| `--extras EXTRAS` | Optional deps: training, simulation, tensorflow, all |
| `--training` | Shorthand for --extras training |
| `--all` | Install all optional dependencies |

**Dependency Groups:**

| Group | Packages | Use Case |
|-------|----------|----------|
| (none) | Core only | Data collection, robot control (fastest) |
| `server` | flask, gevent, socketio | Web UI, visualization server |
| `training` | diffusers, wandb, matplotlib, numba | Policy training |
| `simulation` | gymnasium, pymunk, gym-pusht | Simulation environments |
| `tensorflow` | tensorflow, tensorflow-datasets | TF dataset formats |
| `all` | Everything | Full installation |

### Manual Environment Setup (Alternative)

#### 1.1 Initialize DoRobot Environment

```bash
# Create and activate conda environment
conda create --name dorobot python==3.11
conda activate dorobot

# Install the project (choose one)
pip install -e .                    # Core only (fastest, for data collection)
pip install -e ".[training]"        # Core + training dependencies
pip install -e ".[simulation]"      # Core + simulation environments
pip install -e ".[all]"             # Everything

# Install DORA-RS
pip install dora-rs-cli

# Install robot dependencies
cd operating_platform/robot/robots/so101_v1 && pip install -e .
cd operating_platform/robot/components/arm_normal_so101_v1 && pip install -e .
```

#### 1.2 Install PyTorch (Choose Your Platform)

**CUDA:**
```bash
# CUDA 11.8
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# CUDA 12.4
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

**CPU Only:**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

**Ascend NPU (310B):**
```bash
# Install PyTorch 2.5.1 (CPU version, compatible with torch-npu)
pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu

# Install torch-npu
pip install torch-npu==2.5.1
```

> **NPU Prerequisites:** CANN toolkit must be installed. Visit [Huawei Ascend](https://www.hiascend.com/software/cann) for installation instructions.

#### 1.3 Install System Dependencies (Linux)

```bash
sudo apt install libportaudio2
```

## SO101 Robot Operations

### 2.1 Calibrate SO101 Arm

Calibration files are stored in `arm_normal_so101_v1/.calibration`

**Calibrate Arm 1:**
```bash
cd operating_platform/robot/components/arm_normal_so101_v1/

# Calibrate leader arm 1
dora run dora_calibrate_leader.yml

# Calibrate follower arm 1
dora run dora_calibrate_follower.yml
```

**Calibrate Arm 2:**
```bash
cd operating_platform/robot/components/arm_normal_so101_v1/

# Calibrate leader arm 2
dora run dora_calibrate_leader2.yml

# Calibrate follower arm 2
dora run dora_calibrate_follower2.yml
```

### 2.2 Teleoperate SO101 Arm

```bash
cd operating_platform/robot/components/arm_normal_so101_v1/
dora run dora_teleoperate_arm.yml
```

## Data Recording

### 3.1 Hardware Connection Order

**Important:** Follow this order to ensure correct device indices.

1. **Disconnect all devices** (cameras and robotic arms)

2. **Connect head camera first:**
   ```bash
   ls /dev/video*
   # Should see: /dev/video0 /dev/video1
   ```

3. **Connect wrist camera:**
   ```bash
   ls /dev/video*
   # Should see: /dev/video0 /dev/video1 /dev/video2 /dev/video3
   ```

4. **Connect leader arm:**
   ```bash
   ls /dev/ttyACM*
   # Should see: /dev/ttyACM0
   ```

5. **Connect follower arm:**
   ```bash
   ls /dev/ttyACM*
   # Should see: /dev/ttyACM0 /dev/ttyACM1
   ```

### 3.2 Start Data Collection

**Single Command (Recommended):**
```bash
# Basic usage - starts both DORA and CLI automatically
bash scripts/run_so101.sh

# With custom dataset name
REPO_ID=my-dataset bash scripts/run_so101.sh

# With custom task description
REPO_ID=my-dataset SINGLE_TASK="pick up the cube" bash scripts/run_so101.sh
```

**Cloud Upload Modes (CLOUD=0,1,2,3,4):**
```bash
# Mode 0: Local only (encode locally, no upload)
CLOUD=0 bash scripts/run_so101.sh

# Mode 1: Cloud raw (upload raw images to cloud for encoding)
CLOUD=1 bash scripts/run_so101.sh

# Mode 2: Edge (rsync to edge server) - DEFAULT, fastest for LAN
CLOUD=2 bash scripts/run_so101.sh

# Mode 3: Cloud encoded (encode locally, upload encoded to cloud)
CLOUD=3 bash scripts/run_so101.sh

# Mode 4: Local raw (save raw images only, no encoding, for USB transfer)
CLOUD=4 bash scripts/run_so101.sh
```

**NPU Options (NPU=0,1):**
```bash
# Disable NPU (for non-Ascend hardware)
NPU=0 bash scripts/run_so101.sh

# Enable NPU (for Ascend 310B) - DEFAULT
NPU=1 bash scripts/run_so101.sh
```

**Combined Examples:**
```bash
# Edge upload without NPU (for x86 server)
CLOUD=2 NPU=0 bash scripts/run_so101.sh

# Local encode + NPU (no cloud upload)
CLOUD=0 NPU=1 bash scripts/run_so101.sh

# Cloud encoded with NPU
CLOUD=3 NPU=1 bash scripts/run_so101.sh
```

**Manual Two-Terminal Method (Alternative):**

Terminal 1 - Start DORA dataflow:
```bash
conda activate dorobot
cd operating_platform/robot/robots/so101_v1
dora run dora_teleoperate_dataflow.yml
```

Terminal 2 - Start recording CLI:
```bash
conda activate dorobot
bash scripts/run_so101_cli.sh
```

### 3.3 Recording Controls

| Key | Action |
|-----|--------|
| `n` | Save current episode and start new one |
| `e` | Stop recording and exit |

## Quick Start: Edge Server Workflow (USB Transfer)

This workflow is for scenarios where the robot device has no network access to the edge server. Data is collected locally and transferred via USB.

### Step 1: Collect Data on Robot Device (CLOUD=4)

On your robot device (Orange Pi, laptop with robot):

```bash
# Collect data with CLOUD=4 (saves raw images, no encoding)
CLOUD=4 REPO_ID=my-task bash scripts/run_so101.sh
```

After collection, your data is at:
```
~/DoRobot/dataset/my-task/
├── images/
│   ├── episode_000000/
│   └── episode_000001/
├── data/
└── meta/
```

### Step 2: Copy Data to Edge Server via USB

```bash
# On robot device: copy to USB drive
cp -r ~/DoRobot/dataset/my-task /media/usb-drive/

# On edge server: copy from USB drive
cp -r /media/usb-drive/my-task ~/DoRobot/dataset/
```

### Step 3: Run edge.sh on Edge Server

On the edge server, run the full workflow (encode -> train -> download model):

```bash
cd DoRobot

# Full workflow with your credentials
scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my-task

# The script will:
# 1. Upload to local edge storage
# 2. Encode videos on edge server
# 3. Trigger cloud training
# 4. Wait for training completion (shows transaction ID)
# 5. Download trained model to ~/DoRobot/dataset/my-task/model/
```

### Step 4: Copy Model Back (Optional)

If you want to run inference on the robot device:

```bash
# On edge server: copy model to USB
cp -r ~/DoRobot/dataset/my-task/model /media/usb-drive/

# On robot device: copy model from USB
cp -r /media/usb-drive/model ~/DoRobot/
```

### edge.sh Usage Reference

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
scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my-task

# Skip training (just encode and upload)
scripts/edge.sh -u bob -p bob456 -d ~/DoRobot/dataset/my-task --skip-training

# Custom training timeout (3 hours)
scripts/edge.sh -u alice -p alice123 -d ~/DoRobot/dataset/my-task --timeout 180

# Test connection first
scripts/edge.sh -u alice -p alice123 --test-connection
```

### Multi-User Support

Multiple users can run edge.sh simultaneously on the same edge server:
- Each user's data is isolated at `/uploaded_data/{username}/{repo_id}/`
- No conflicts between users with the same repo_id
- API credentials are required for authentication

## Training

```bash
conda activate dorobot

python operating_platform/core/train.py \
  --dataset.repo_id="/path/to/dataset" \
  --policy.type=act \
  --output_dir=outputs/train/act_so101_test \
  --job_name=act_so101_test \
  --policy.device=cuda \
  --wandb.enable=false
```

**For NPU training:**
```bash
python operating_platform/core/train.py \
  --dataset.repo_id="/path/to/dataset" \
  --policy.type=act \
  --policy.device=npu \
  ...
```

## Inference

### Using the Inference Launcher (Recommended)

The `run_so101_inference.sh` script handles all setup automatically. After cloud training, just run:

```bash
# Default usage (uses ~/DoRobot/dataset/so101-test and ~/DoRobot/model)
bash scripts/run_so101_inference.sh

# With custom dataset name (must match REPO_ID used during data collection)
REPO_ID=my-task bash scripts/run_so101_inference.sh

# With explicit paths
bash scripts/run_so101_inference.sh --dataset ~/DoRobot/dataset/so101-test --model ~/DoRobot/model

# With custom task description
SINGLE_TASK="Pick up the red cube" bash scripts/run_so101_inference.sh

# Disable NPU (for non-Ascend hardware)
NPU=0 bash scripts/run_so101_inference.sh
```

**Default Paths:**
- Dataset: `~/DoRobot/dataset/${REPO_ID}` (default REPO_ID: so101-test)
- Model: `~/DoRobot/model`

**Important:** Use the SAME device ports as data collection for consistent results.

### Inference Controls

| Key | Action |
|-----|--------|
| `n` | End current episode and start new one |
| `p` | Proceed after robot reset |
| `e` | Stop inference and exit |

### Manual Inference (Alternative)

```bash
conda activate dorobot

python operating_platform/core/inference.py \
  --robot.type=so101 \
  --inference.dataset.repo_id="~/DoRobot/dataset/so101-test" \
  --inference.single_task="task description" \
  --policy.path="~/DoRobot/model"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLOUD` | `2` | Cloud mode: 0=local, 1=cloud raw, 2=edge, 3=cloud encoded |
| `NPU` | `1` | Set to `0` to disable Ascend NPU |
| `REPO_ID` | `so101-test` | Dataset repository ID |
| `SINGLE_TASK` | `start and test...` | Task description |
| `CONDA_ENV` | `dorobot` | Conda environment name |
| `ASCEND_TOOLKIT_PATH` | `/usr/local/Ascend/ascend-toolkit` | CANN toolkit path |

**CLOUD Modes:**

| CLOUD | Mode | Encoding | Upload | Training |
|-------|------|----------|--------|----------|
| 0 | Local only | Local | None | None |
| 1 | Cloud raw | Cloud | Raw images | Cloud |
| 2 | Edge | Edge server | Raw images | Cloud |
| 3 | Cloud encoded | Local | Encoded videos | Cloud |
| 4 | Local raw | None | None | None (for USB transfer) |

## Project Structure

```
DoRobot/
├── operating_platform/
│   ├── core/           # Main pipelines (record, train, inference)
│   ├── robot/          # Robot hardware abstraction
│   │   ├── robots/     # Robot configurations (so101_v1, aloha_v1)
│   │   └── components/ # Hardware components (arms, cameras)
│   ├── policy/         # Policy implementations (ACT, Diffusion, etc.)
│   ├── dataset/        # Dataset management
│   └── utils/          # Utility functions
├── scripts/            # Launch scripts
│   ├── setup_env.sh    # Environment setup
│   ├── run_so101.sh    # Unified launcher
│   └── run_so101_cli.sh
└── docs/               # Documentation
```

## Acknowledgment

- LeRobot: [https://github.com/huggingface/lerobot](https://github.com/huggingface/lerobot)
- DORA-RS: [https://github.com/dora-rs/dora](https://github.com/dora-rs/dora)
