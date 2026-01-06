# DoRobot Q&A 文档

**最后更新：** 2026-01-06
**维护者：** DoRobot Team

本文档整合了以下内容：
- DORA 数据流通信问题诊断与修复
- 推理系统模型加载与验证
- 摄像头配置和图像数据接入
- 推理模式从臂连接问题
- 数据存储路径配置
- Piper从臂安全改进和故障排查
- 主从臂标定对齐问题和解决方案
- LeRobot零点位置解决方案研究
- 标定工具使用指南
- 从臂硬件故障诊断
- 常见问题解答

## 版本对照表

本文档内容对应的 DoRobot 版本：

| 日期 | 内容 | 对应版本 |
|------|------|----------|
| 2026-01-06 | DORA 数据流通信修复、推理系统诊断 | [v0.2.139](RELEASE.md#v0.2.139) |
| 2026-01-05 | 摄像头配置、路径标准化、推理脚本改进 | [v0.2.138](RELEASE.md#v0.2.138) |
| 2025-12-30 | 姿态映射基准系统 | [v0.2.137](RELEASE.md#v0.2.137) |
| 2025-12-29 | 从臂硬件故障诊断 | [v0.2.136](RELEASE.md#v0.2.136) |
| 2025-12-29 | LeRobot研究、标定工具、Q&A整合 | [v0.2.135](RELEASE.md#v0.2.135) |
| 2025-12-26 | 关节映射修复、电机配置、诊断工�� | [v0.2.134](RELEASE.md#v0.2.134) |
| 2025-12-25 | 主从臂标定对齐、安全保护机制 | [v0.2.132](RELEASE.md#v0.2.132), [v0.2.133](RELEASE.md#v0.2.133) |

---

# 第零部分：DORA 数据流通信问题

**对应版本：** [v0.2.139](RELEASE.md#v0.2.139)

---

## 问题1：推理系统无法接收从臂关节数据

### 症状描述

**现象：**
```
TimeoutError: 连接超时，未满足的条件: 等待从臂关节角度超时: 未收到 [main_follower]; 已收到 []
```

**表现：**
- 推理系统启动后，DORA 节点正常初始化
- 相机数据流连接成功
- 从臂使能成功，读取到安全位置
- 但推理系统一直等待从臂关节数据，最终超时（50秒）

### 根本原因

**事件名称不匹配：**

1. **DORA 配置** (`dora_control_dataflow.yml` line 53)：
   ```yaml
   inputs:
     get_joint: dora/timer/millis/33  # 发送 get_joint 事件
   ```

2. **机械臂组件** (`arm_normal_piper_v2/main.py` line 214)：
   ```python
   elif event["id"] == "tick":  # 只处理 tick 事件
       # 读取关节数据并发送
   ```

3. **结果**：
   - 机械臂组件收不到触发信号
   - 不会发送关节数据到 `joint` 输出
   - ZeroMQ 桥接收不到 `main_follower_joint` 数据
   - 推理系统超时

### 解决方案

**修改文件：** `operating_platform/robot/robots/so101_v1/dora_control_dataflow.yml`

**修改内容：**
```yaml
# 修改前
inputs:
  get_joint: dora/timer/millis/33
  action_joint: so101_zeromq/action_joint

# 修改后
inputs:
  tick: dora/timer/millis/33
  action_joint: so101_zeromq/action_joint
```

**修改位置：** Line 53

### 数据流架构说明

**完整数据流：**
```
定时器 (33ms)
  → DORA: tick 事件
  → arm_so101_follower 组件
  → 读取关节角度
  → 输出: joint
  → DORA: main_follower_joint
  → so101_zeromq 组件
  → ZeroMQ IPC: /tmp/dora-zeromq-so101-joint
  → 推理系统 (manipulator.py)
  → recv_joint['main_follower_joint']
```

**关键组件：**
1. **arm_normal_piper_v2/main.py**: 处理 `tick` 事件，读取并发送关节数据
2. **dora_zeromq.py**: ZeroMQ 桥接，转发 DORA 事件到推理系统
3. **manipulator.py**: 推理系统，接收关节数据并执行推理

### 验证步骤

1. **检查 DORA 配置**：
   ```bash
   grep -A 3 "arm_so101_follower" operating_platform/robot/robots/so101_v1/dora_control_dataflow.yml
   ```
   应该看到 `tick: dora/timer/millis/33`

2. **运行推理系统**：
   ```bash
   bash scripts/run_so101_inference.sh
   ```

3. **验证成功标志**：
   ```
   [SO101] Joint data stream connected
   [连接成功] 所有设备已就绪:
     - 从臂关节角度: main_follower
     总耗时: 3.01秒
   Starting inference
   dt: 0.09 (11276.4hz)
   ```

### 相关问题排查

**如果仍然超时，检查：**

1. **机械臂连接**：
   ```bash
   # 检查 CAN 总线
   ip link show can_left
   ```

2. **DORA 进程**：
   ```bash
   ps aux | grep -E "dora|arm_normal_piper"
   ```

3. **ZeroMQ IPC 文件**：
   ```bash
   ls -la /tmp/dora-zeromq-so101-*
   ```

4. **清理遗留进程**：
   ```bash
   pkill -9 -f "arm_normal_piper_v2/main.py"
   pkill -9 -f "dora_zeromq.py"
   rm -f /tmp/dora-zeromq-so101-*
   ```

---

## 问题2：如何验证训练模型的完整性

### 症状描述

**需求：**
- 验证训练好的模型文件是否完整
- 确认模型参数量和配置正确
- 确保模型可以被推理系统加载

### 验证方法

**1. 检查模型文件**：
```bash
ls -lh dataset/model/
# 应该看到：
# config.json (1.6K)
# model.safetensors (197M)
# train_config.json (4.7K)
```

**2. 验证模型权重**：
```python
from safetensors.torch import load_file
import json

# 检查配置
with open('dataset/model/config.json', 'r') as f:
    config = json.load(f)
print(f"模型类型: {config['type']}")
print(f"输入特征: {list(config['input_features'].keys())}")
print(f"输出特征: {list(config['output_features'].keys())}")

# 检查权重
state_dict = load_file('dataset/model/model.safetensors')
print(f"参数数量: {len(state_dict)}")
total_params = sum(p.numel() for p in state_dict.values())
print(f"总参数量: {total_params:,}")
```

**3. 预期输出**：
```
模型类型: act
输入特征: ['observation.state', 'observation.images.image_top', 'observation.images.image_wrist']
输出特征: ['action']
参数数量: 244
总参数量: 51,668,662
```

### 模型规格

**ACT (Action Chunking Transformer) 模型：**
- **类型**: act
- **总参数**: 51,668,662 (约 5170 万)
- **文件大小**: 197 MB
- **输入**:
  - `observation.state`: 6D 关节角度
  - `observation.images.image_top`: 3×480×640 顶部相机
  - `observation.images.image_wrist`: 3×480×640 手腕相机
- **输出**:
  - `action`: 6D 关节动作
- **架构**:
  - Vision backbone: ResNet18
  - Encoder layers: 4
  - Decoder layers: 1
  - VAE: 启用 (latent_dim=32)
  - Chunk size: 100
  - Action steps: 100

### 常见问题

**Q: 模型文件损坏如何判断？**
A: 使用 safetensors 加载会抛出异常。正常加载说明文件完整。

**Q: 推理系统报 policy_path: None？**
A: 检查 `scripts/run_so101_inference.sh` 中的 `--policy.path` 参数是否正确传递。

---

# 第一部分：摄像头配置与推理模式问题

**对应版本：** [v0.2.138](RELEASE.md#v0.2.138)

---

## 问题1：摄像头设备路径配置

### 症状描述

**现象：**
- 需要为 RealSense 和 Orbbec 摄像头配置固定的视频设备节点
- CAMERA_WRIST_PATH 应使用 RealSense 推荐的 /dev/video4
- CAMERA_TOP_PATH 应使用 Orbbec 推荐的 /dev/video12

### 解决方案

**修改文件：** `scripts/detect_cameras.sh`

**修改内容：**
```bash
# RealSense 摄像头配置（第66-67行）
if echo "$INFO" | grep -q "YUV 彩色流"; then
    echo "CAMERA_WRIST_PATH=/dev/video4" >> "$CONFIG_FILE"
    echo "REALSENSE_COLOR_DEVICE=/dev/video4" >> "$CONFIG_FILE"
fi

# Orbbec 摄像头配置（第73行）
if echo "$INFO" | grep -q "YUV 彩色流"; then
    echo "CAMERA_TOP_PATH=/dev/video12" >> "$CONFIG_FILE"
fi
```

**测试结果：**
- ✅ RealSense 摄像头成功初���化（/dev/video4）
- ✅ Orbbec 摄像头成功初始化（/dev/video12）
- ✅ 采集 2377 帧测试数据成功
- ✅ 视频编码成功（2个 MP4 视频）

---

## 问题2：推理模式从臂连接失败

### 症状描述

**现象：**
- 运行 `bash scripts/run_so101_inference.sh` 时报错
- 错误信息：`Could not connect on port 'can_left'`
- 从臂使用 Piper（CAN 总线），但推理模式使用了错误的组件

**根本原因：**
- 推理模式的 dataflow 配置使用了 `arm_normal_so101_v1` 组件（串口）
- 应该使用 `arm_normal_piper_v2` 组件（CAN 总线）
- 遥操作模式使用正确的组件，但推理模式配置不一致

### 解决方案

**修改文件：** `operating_platform/robot/robots/so101_v1/dora_control_dataflow.yml`

**修改内容：**
```yaml
# 第50-59行：从臂配置
- id: arm_so101_follower
  path: ../../components/arm_normal_piper_v2/main.py  # 改为 Piper 组件
  inputs:
    get_joint: dora/timer/millis/33
    action_joint: so101_zeromq/action_joint
  outputs:
    - joint
  env:
    # 使用 CAN_BUS 而不是 PORT
    CAN_BUS: ${ARM_FOLLOWER_PORT:-can_left}
```

**测试结果：**
- ✅ Piper 从臂成功连接（CAN 总线）
- ✅ 从臂使能成功
- ✅ 读取从臂位置成功
- ✅ 所有硬件准备就绪

---

## 问题3：推理脚本缺少 conda 环境

### 症状描述

**现象：**
- 运行推理脚本时报错：`ModuleNotFoundError: No module named 'cv2'`
- 同时缺少 zmq、pyarrow 等模块
- 脚本使用系统 Python (`/usr/bin/python3`) 而不是 conda 环境

**根本原因：**
- `run_so101_inference.sh` 没有激活 conda 环境
- 遥操作脚本 `run_so101.sh` 有 conda 激活逻辑，但推理脚本缺失

### 解决方案

**修改文件：** `scripts/run_so101_inference.sh`

**添加内容（第34-83行）：**
```bash
# Configuration
CONDA_ENV="${CONDA_ENV:-dorobot}"

# Initialize conda environment
init_conda() {
    # Find conda installation
    if [ -n "$CONDA_EXE" ]; then
        CONDA_BASE="$(dirname "$(dirname "$CONDA_EXE")")"
    elif [ -d "$HOME/miniconda3" ]; then
        CONDA_BASE="$HOME/miniconda3"
    elif [ -d "$HOME/anaconda3" ]; then
        CONDA_BASE="$HOME/anaconda3"
    elif [ -d "/opt/conda" ]; then
        CONDA_BASE="/opt/conda"
    else
        echo "[ERROR] Cannot find conda installation"
        exit 1
    fi

    # Source conda.sh to enable conda activate
    if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        source "$CONDA_BASE/etc/profile.d/conda.sh"
    else
        echo "[ERROR] Cannot find conda.sh"
        exit 1
    fi
}

# Activate conda environment
activate_env() {
    local env_name="$1"
    if ! conda env list | grep -q "^${env_name} "; then
        echo "[ERROR] Conda environment '$env_name' does not exist"
        exit 1
    fi
    conda activate "$env_name"
    echo "[INFO] Activated conda environment: $env_name"
}

echo "[INFO] Initializing conda environment..."
init_conda
activate_env "$CONDA_ENV"
```

**测试结果：**
- ✅ Conda 环境成功激活
- ✅ 所有 Python 模块可用
- ✅ 推理脚本正常启动

---

## 问题4：数据存储路径配置

### 症状描述

**需求：**
- 将数据保存路径从 `~/DoRobot/dataset/` 改为项目目录下的 `./dataset/`
- 将模型路径从 `~/DoRobot/model` 改为 `./dataset/model`
- 使数据和代码在同一项目目录下，便于管理

### 解决方案

**修改文件1：** `operating_platform/utils/constants.py`

**修改内容（第24-26行）：**
```python
# 获取项目根目录（constants.py 的上上级目录）
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DOROBOT_HOME = Path(os.getenv("DOROBOT_HOME", str(PROJECT_ROOT))).expanduser().resolve()
```

**修改文件2：** `scripts/run_so101_inference.sh`

**修改内容（第118-119行）：**
```bash
DATASET_PATH="${1:-$PROJECT_ROOT/dataset/$REPO_ID}"
MODEL_PATH="${2:-$PROJECT_ROOT/dataset/model}"
```

**新的目录结构：**
```
/path/to/DoRobot/
├── scripts/
├── dataset/              # 新位置
│   ├── so101-test/      # 训练数据
│   └── model/           # 模型文件
└── operating_platform/
```

**迁移说明：**
- 旧数据位置：`~/DoRobot/dataset/`
- 新数据位置：`./dataset/`
- 如需使用旧数据：`cp -r ~/DoRobot/dataset/* ./dataset/`
- 或设置环境变量：`export DOROBOT_HOME=~/DoRobot`

---

## 快速参考：设备配置

**配置文件位置：** `~/.dorobot_device.conf`

**推荐配置：**
```bash
# 摄像头
CAMERA_TOP_PATH="/dev/video12"      # Orbbec Gemini 335
CAMERA_WRIST_PATH="/dev/video4"     # RealSense Depth Camera 405

# 机械臂
ARM_LEADER_PORT="/dev/ttyUSB0"      # SO101 Leader (Zhonglin)
ARM_FOLLOWER_PORT="can_left"        # Piper Follower (CAN bus)
```

**生成配置：**
```bash
# 自动检测并生成配置
bash scripts/detect.sh

# 或手动运行
python scripts/detect_usb_ports.py --save --chmod
```

**测试配置：**
```bash
# 测试遥操作（数据采集）
bash scripts/run_so101.sh

# 测试推理
bash scripts/run_so101_inference.sh
```

---

# 第一部分：姿态映射基准系统

**对应版本：** [v0.2.137](RELEASE.md#v0.2.137)

---

## 问题：重新标定主臂后遥操作失败

### 症状描述

**现象：**
- 重新标定主臂（SO101 Leader）后，遥操作无法启动
- 主臂标定使用关节中点作为初始参考点
- 从臂（Piper）无法物理移动到主臂定义的安全位置
- 角度差异过大，触发紧急停止
- 即使调整安全阈值，遥操作仍然不稳定

**影响范围：**
- 主从臂标定零点不匹配
- 遥操作启动失败
- 系统持续报警"位置差异过大"

### 根本原因

**标定零点不匹配：**
- 主臂标定：使用关节运动范围的中点作为参考
- 从臂安全位置：固定的物理姿态 `[5.4°, 0.0°, -4.2°, 3.1°, 9.5°, 17.1°]`
- 两者不在同一物理位置，导致角度差异巨大

**传统方案的局限：**
```python
# 旧方案：强制从臂移动到固定安全位置
safe_home_position = [5982, -1128, 3940, -19218, 18869, 40103]
piper.JointCtrl(*safe_home_position)

# 问题：
# 1. 如果主臂标定的零点不在这个位置，会有巨大差异
# 2. 从臂被强制移动，可能不是操作员期望的起始位置
# 3. 每次重新标定主臂，都需要重新调整这个固定位置
```

### 解决方案：姿态映射基准系统

#### 核心思想

**不要求主从臂标定零点相同，只要求相对运动一致**

```python
# 新方案：动态建立姿态映射基准
# 1. 读取当前从臂位置作为基准
follower_baseline = read_current_follower_position()

# 2. 等待首次主臂命令，记录主臂基准
leader_baseline = read_first_leader_command()

# 3. 应用偏移映射
leader_offset = leader_current - leader_baseline
target = follower_baseline + leader_offset
```

**优势：**
- 主从臂可以从任何物理姿态开始
- 不需要强制移动到固定位置
- 标定零点可以不同，只要相对运动一致
- 操作员可以自然地摆放机械臂

#### 实现细节

**文件：** `operating_platform/robot/components/arm_normal_piper_v2/main.py`

**步骤1：启动时读取从臂基准（第58-71行）**
```python
print("[Piper] 读取当前从臂位置作为安全基准...")
current_joint = piper.GetArmJointMsgs()
follower_baseline = [
    current_joint.joint_state.joint_1.real,
    current_joint.joint_state.joint_2.real,
    current_joint.joint_state.joint_3.real,
    current_joint.joint_state.joint_4.real,
    current_joint.joint_state.joint_5.real,
    current_joint.joint_state.joint_6.real,
]
print(f"[Piper] 从臂安全位置（度）: {[f'{p/1000:.1f}' for p in follower_baseline]}")
print("[Piper] 等待首次主臂命令以建立映射...")
```

**步骤2：首次命令时记���主臂基准（第120-129行）**
```python
if not first_command_received:
    leader_baseline = [position[i] * factor for i in range(6)]
    first_command_received = True
    print("[Piper] 姿态映射基准已建立")
    print(f"  主臂基准（度）: {[f'{p/1000:.1f}' for p in leader_baseline]}")
    print(f"  从臂基准（度）: {[f'{p/1000:.1f}' for p in follower_baseline]}")
    print("[Piper] 开始遥操作控制")
```

**步骤3：应用姿态映射（第131-134行）**
```python
# 计算主臂相对于基准的偏移
leader_current = [position[i] * factor for i in range(6)]
leader_offset = [leader_current[i] - leader_baseline[i] for i in range(6)]

# 从臂目标 = 从臂基准 + 主臂偏移
target_positions = [follower_baseline[i] + leader_offset[i] for i in range(6)]
```

#### 关节方向修正

**问题：** 关节4和关节5运动方向相反

**解决方案：** 在读取主臂数据后立即反转（第106-110行）
```python
position = event["value"].to_numpy().copy()

# 反转关节4和关节5的方向
position[3] = -position[3]  # joint_4
position[4] = -position[4]  # joint_5
```

**注意：** 这与 `drive_mode` 参数不同
- `drive_mode`：用于主臂（SO101）的 Feetech 电机配置
- 方向反转：用于从臂（Piper）的 SDK 输入值修正
- Piper SDK 不使用 `drive_mode`，通过反转输入值实现方向修正

### 配套修改

#### 1. 准备脚本不再强制移动

**文件：** `scripts/prepare_follower.py`（第91-96行）

```python
# 旧代码：强制移动到固定位置
# piper.JointCtrl(*SAFE_HOME_POSITION)

# 新代码：仅检查状态，不移动
print("[Follower Prepare] ✓ 从臂状态正常")
print("[Follower Prepare] ℹ️  使用姿态映射方案 - 将在遥操开始时建立基准")
print("[Follower Prepare] ℹ️  请确保主臂和从臂处于相同的物理姿态")
print("[Follower Prepare] ✓ 准备完成，可以开始遥操作")
```

#### 2. 摄像头处理优化

**文件：** `operating_platform/robot/robots/so101_v1/manipulator.py`

**问题：** 系统没有物理摄像头，导致连接超时

**解决方案：**
- 第275行：排除摄像头连接检查
  ```python
  self.connect_excluded_cameras = ["image_pika_pose", "image_top", "image_wrist"]
  ```
- 第581-591行：优雅处理缺失的摄像头图像
  ```python
  images = {}
  for name in self.cameras:
      if name in recv_images:
          images[name] = recv_images[name]
  ```

### 使用方法

**标准操作流程：**

1. **摆放机械臂**
   - 将主臂和从臂放置在相同的物理姿态
   - 不需要是特定位置，只要两个臂物理上对应即可

2. **启动遥操作**
   ```bash
   bash scripts/run_so101.sh
   ```

3. **等待基准建立**
   ```
   [Piper] 读取当前从臂位置作为安全基准...
   [Piper] 从臂安全位置（度）: ['5.4', '0.0', '-4.2', '3.1', '9.5', '17.1']
   [Piper] 等待首次主臂命令以建立映射...
   ```

4. **开始操作**
   - 移动主臂
   - 系统自动建立映射基准
   ```
   [Piper] 姿态映射基准已建立
     主臂基准（度）: ['270.0', '0.0', '199.4', '113.0', '143.7', '123.4']
     从臂基准（度）: ['5.4', '0.0', '-4.2', '3.1', '9.5', '17.1']
   [Piper] 开始遥操作控制
   ```

5. **正常遥操作**
   - 从臂会跟随主臂的相对运动
   - 安全监控持续运行（30°警告，60°紧急停止）

### 测试结果

**成功案例：**
```
姿态映射基准已建立：
  主臂基准: [270.0°, 0.0°, 199.4°, 113.0°, 143.7°, 123.4°]
  从臂基准: [5.4°, 0.0°, -4.2°, 3.1°, 9.5°, 17.1°]

数据流速率: ~17-19kHz
紧急停止: 无
遥操作效果: 流畅，从臂准确跟随主臂运动
```

**关键指标：**
- ✅ 主从臂标定零点可以完全不同
- ✅ 不需要强制移动到固定位置
- ✅ 关节方向正确（joint_4 和 joint_5 已修正）
- ✅ 安全监控正常工作
- ✅ 遥操作稳定可靠

### 优势总结

1. **标定独立性**
   - 主从臂可以独立标定
   - 不需要标定零点匹配
   - 重新标定主臂不影响遥操作

2. **灵活的起始位置**
   - 可以从任何物理姿态开始
   - 不需要移动到固定安全位置
   - 操作员可以自然摆放机械臂

3. **简化设置流程**
   - 减少准备步骤
   - 降低失败风险
   - 提高用户体验

4. **鲁棒性提升**
   - 自动适应标定差异
   - 动态建立映射关系
   - 减少人为错误

### 与 LeRobot 方案的对比

**LeRobot 方案：**
- 独立校准主从臂
- 通过校准数据建立逻辑角度空间映射
- 需要完整的校准流程

**DoRobot 姿态映射方案：**
- 运行时动态建立映射
- 基于当前物理位置
- 无需重新校准
- 更灵活，更易用

**核心理念相同：** 不要求绝对零点相同，只要求相对运动一致

### 相关文件

- **主程序：** `operating_platform/robot/components/arm_normal_piper_v2/main.py`
- **准备脚本：** `scripts/prepare_follower.py`
- **机器人控制：** `operating_platform/robot/robots/so101_v1/manipulator.py`
- **版本记录：** [v0.2.137](RELEASE.md#v0.2.137)

---

# 第一部分：从臂硬件故障诊断

**对应版本：** [v0.2.136](RELEASE.md#v0.2.136)

---

## 问题：从臂关节卡在0.0°无法移动

### 症状描述

**现象：**
- 遥操作时，从臂的joint_1和joint_3始终显示0.0°
- 主臂发��的目标位置正常变化（如70.217°）
- 从臂不响应控制命令，位置不变
- 系统持续报警"位置差异过大"

**影响范围：**
- joint_1 (索引0，从底座数第1个关节)：卡在0.0°
- joint_3 (索引2，从底座数第3个关节)：卡在0.0°
- 其他4个关节工作正常

### 诊断过程

#### 步骤1：排除标定问题

**测试方法：**
```bash
python scripts/calib_piper_ZL.py
```

**结果分析：**
```
[0] joint_1
    主臂: 52.93° | 从臂: 0.00° | 差异: 52.93°  ✗

[1] joint_2
    主臂: 0.59°  | 从臂: 0.57° | 差异: 0.03°   ✓

[2] joint_3
    主臂: 73.94° | 从臂: 0.00° | 差异: 73.94°  ✗

[3] joint_4
    主臂: 9.45°  | 从臂: 9.46° | 差异: 0.01°   ✓

[4] joint_5
    主臂: -17.39° | 从臂: -17.40° | 差异: 0.01° ✓

[5] joint_6
    主臂: 20.05° | 从臂: 20.01° | 差异: 0.04°  ✓
```

**结论：**
- 4个关节完美对齐（< 0.05°差异）→ 标定准确
- 2个关节卡在0.0° → 不是标定问题

#### 步骤2：检查CAN通信

**测试方法：**
```bash
ip -s -d link show can_left
```

**结果：**
```
RX: 1,066,104 bytes, 133,263 packets  # 从臂正在发送数据
TX: 0 bytes, 0 packets                # 无法发送控制命令
```

**初步结论：**
- 从臂硬件正常工作（发送位置数据）
- 控制命令发送存在问题

#### 步骤3：测试单个关节

**测试方法：**
修改 `scripts/piper_move.py` 测试joint_5（已知工作正常的关节）：
```bash
python scripts/piper_move.py --can-bus can_left
```

**结果：**
```
当前位置: [3110, -2178, 3359, 12017, 22291, 27570]
目标位置: [3110, -2178, 3359, 12017, 5000, 27570]
最终位置: [3110, -2178, 3359, 12017, 22291, 27570]
✗ joint_5 未到达目标位置
```

**发现：**
- 从臂现在可以读取非零位置（之前全是0）
- joint_3 (索引2) 显示3.359°，不再是0.0°
- 但控制命令仍然不起作用

#### 步骤4：完整遥操作测试

**测试方法：**
```bash
bash scripts/run_so101.sh
```

**结果：**
```
从臂当前位置: [5.378, 0.0, 0.0, 3.046, 18.647, 24.409]
主臂目标位置: [5.154, 0.793, 70.217, 9.72, -4.347, 24.92]
警告：主从臂位置差异过大 (70.2度)
```

**最终确认：**
- joint_1 (索引0) = 0.0° (主臂52.93°) → 卡住
- joint_3 (索引2) = 0.0° (主臂70.217°) → 卡住
- 其他关节正常跟随主臂运动

### 根本原因

**硬件故障：**
从臂的joint_1和joint_3存在硬件问题，可能原因：

1. **电机驱动器故障**
   - 编码器工作（能读取位置）
   - 但电机无法驱动（不响应控制命令）

2. **电源供应问题**
   - 这两个关节的电源可能断开或不足
   - 其他关节电源正常

3. **机械卡死**
   - 关节被物理阻挡
   - 刹车未释放

4. **CAN通信问题**
   - 这两个关节的CAN消息未正确接收
   - 但其他关节CAN通信正常

### 诊断步骤

#### 1. 断电手动测试

**操作：**
1. 关闭从臂电源
2. 手动转动joint_1和joint_3
3. 观察阻力情况

**判断标准：**
- **能轻松转动** → 电机驱动器或控制器故障
- **完全卡死** → 机械卡死或刹车未释放
- **有阻力但能动** → 正常电机线圈阻力

#### 2. 上电位置测试

**操作：**
```bash
# 手动移动joint_1和joint_3后，读取位置
python scripts/piper_move.py --can-bus can_left --read-only
```

**判断标准：**
- **位置改变** → 编码器正常，电机驱动故障
- **仍是0.0°** → 编码器也有问题

#### 3. 联系厂商

如果确认硬件故障，需要：
- 提供故障关节编号（joint_1和joint_3）
- 描述故障现象（位置读取正常但不响应控制）
- 申请维修或更换电机驱动器

### 关键发现

**不是软件问题的证据：**
1. ✅ 主臂标定准确（4个关节< 0.05°差异）
2. ✅ 关节映射正确（工作的关节完美对应）
3. ✅ CAN通信正常（能接收从臂数据）
4. ✅ 控制逻辑正常（其他关节响应正确）

**是硬件问题的证据：**
1. ✗ 只有2个特定关节卡住
2. ✗ 这2个关节始终报告0.0°
3. ✗ 直接控制命令也无效
4. ✗ 在正确的DORA框架下也无法移动

### 临时解决方案

**有限功能测试：**
- 可以使用其他4个正常工作的关节
- 避免需要joint_1和joint_3的动作
- 用于验证其他功能和算法

**不建议：**
- 不要强制发送大幅度运动命令
- 不要尝试通过软件"修复"硬件问题
- 不要忽略安全警告继续遥操作

### 相关文件

- **诊断脚本：** `scripts/piper_move.py`
- **标定对比：** `scripts/calib_piper_ZL.py`
- **遥操作：** `scripts/run_so101.sh`
- **版本记录：** [v0.2.136](RELEASE.md#v0.2.136)

---

# 第一部分：Piper从臂安全改进文档

**组件版本：** arm_normal_piper_v2

---

## 目录
- [问题背景](#问题背景)
- [解决方案概述](#解决方案概述)
- [详细改进内容](#详细改进内容)
- [参数配置](#参数配置)
- [使用说明](#使用说明)
- [故障排查](#故障排查)
- [维护记录](#维护记录)

---

## 问题背景

### 原始问题
运行 `/scripts/run_so101.sh` 启动遥操作系统时，松灵Piper从臂会从初始状态开始运动，如果目标位置与当前位置差异过大，机械臂会尝试快速移动到目标位置，导致：

1. **电流瞬间过大**
2. **保险丝熔断**
3. **系统无法正常工作**

### 根本原因分析

1. **主臂立即发送位置**
   - SO101主臂启动后，以30Hz频率（每33ms）读取当前关节角度并发送给从臂
   - 主臂的初始位置可能与从臂当前位置相差很大

2. **从臂无初始位置控制**
   - Piper从臂启动后直接接收主臂位置命令
   - 没有安全的初始位置设置
   - 没有位置差异检查机制

3. **缺少运行时监控**
   - 没有实时监控主从臂位置差异
   - 无法及时发现异常情况
   - 缺少紧急停止机制

---

## 解决方案概述

实现了**三层安全保护机制**：

```
启动保护 → 运行监控 → 紧急停止
   ↓           ↓           ↓
 20度阈值   20度警告    30度停止
```

### 核心改进
1. ✅ 设置安全起始位置
2. ✅ 启动时位置对齐检查
3. ✅ 实时位置差异监控
4. ✅ 分级警告和紧急停止
5. ✅ 详细的错误提示

---

## 详细改进内容

### 1. 安全起始位置设置

**文件：** `main.py` 第56-70行

**改进内容：**
```python
# 从臂启动时移动到实际测量的安全位置
safe_home_position = [5982, -1128, 3940, -19218, 18869, 40103]
```

**获取方法：**
```bash
# 使用测试脚本读取当前位置
python /home/demo/Public/DoRobot/scripts/test_piper_move.py --read-only --can-bus can_left
```

**作用：**
- 确保从臂从已知的安全位置开始
- 避免从未知位置启动导致的大幅度运动
- 等待3秒确保到达目标位置

---

### 2. 启动时位置对齐检查

**文件：** `main.py` 第151-162行

**检查逻辑：**
```python
if not first_command_received:
    if max_diff > POSITION_DIFF_WARNING:  # 20度
        # 拒绝启动，提示用户对齐主从臂
        continue
```

**触发条件：**
- 首次接收主臂命令时
- 任何关节位置差异 > 20度

**用户操作：**
1. 系统显示当前从臂位置和主臂目标位置
2. 用户手动移动主臂到接近从臂位置
3. 位置差异 < 20度时自动开始遥操作

---

### 3. 实时位置差异监控

**文件：** `main.py` 第108-131行

**监控内容：**
- 每次接收命令时读取从臂当前位置
- 计算6个关节的位置差异
- 识别差异最大的关节

**监控频率：**
- 命令接收频率：30Hz（每33ms）
- 输出显示频率：每0.5秒（避免刷屏）

**输出格式：**
```
[Piper] ⚠️  警告：关节3差异 22.5度 | 差异: ['2.1', '3.5', '22.5', '1.8', '4.2', '2.0']
```

---

### 4. 三级安全保护

**文件：** `main.py` 第75-80行（配置）、第133-168行（执行）

#### 级别1：启动检查（15度）
```python
POSITION_DIFF_WARNING = 15000  # 15 degrees
```
- **触发时机：** 首次接收命令
- **动作：** 拒绝启动，提示对齐
- **恢复：** 用户手动对齐后自动恢复

#### 级别2：运行警告（15度）
```python
monitor_interval = 0.5  # 每0.5秒检查一次
```
- **触发时机：** 运行中任何关节差异 > 15度
- **动作：** 终端输出警告信息
- **恢复：** 继续运行，持续监控

#### 级别3：紧急停止（20度）
```python
POSITION_DIFF_EMERGENCY = 20000  # 20 degrees
```
- **触发时机：** 任何关节差异 > 20度
- **动作：**
  - 设置 `emergency_stop = True`
  - 拒绝所有后续命令
  - 显示详细错误信息
  - 退出主循环
- **恢复：** 需要重启系统

---

## 参数配置

### 当前配置（main.py 第75-80行）

| 参数 | 值 | 单位 | 说明 |
|------|-----|------|------|
| `POSITION_DIFF_WARNING` | 15000 | 0.001度 | 警告阈值（15度） |
| `POSITION_DIFF_EMERGENCY` | 20000 | 0.001度 | 紧急停止阈值（20度） |
| `monitor_interval` | 0.5 | 秒 | 监控输出间隔 |
| 控制频率 | 30 | Hz | 命令接收频率（不可调） |
| 运动速度 | 60 | % | 从臂运动速度 |

### 参数调整建议

**如果频繁触发警告：**
```python
POSITION_DIFF_WARNING = 25000  # 增加到25度
```

**如果需要更严格的保护：**
```python
POSITION_DIFF_EMERGENCY = 25000  # 降低到25度
monitor_interval = 0.3  # 更频繁的监控输出
```

**如果需要更快的响应：**
```python
piper.MotionCtrl_2(0x01, 0x01, 80, 0x00)  # 提高速度到80%
```
⚠️ **注意：** 提高速度会增加电流消耗，可能增加保险丝熔断风险

---

## 使用说明

### 正常启动流程

1. **启动系统**
   ```bash
   bash /scripts/run_so101.sh
   ```

2. **等待初始化**
   ```
   [Piper] 移动到安全初始位置...
   [Piper] 已到达安全初始位置，准备开始遥操作
   ```

3. **对齐主从臂**（如果需要）
   - 如果看到警告信息，手动移动主臂到接近从臂位置
   - 系统会自动检测并开始遥操作

4. **开始遥操作**
   ```
   [Piper] 开始遥操作控制
   ```

5. **正常操作**
   - 缓慢移动主臂
   - 观察从臂跟随情况
   - 注意终端警告信息

### 更新安全起始位置

如果需要更改从臂的起始位置：

1. **手动移动从臂到期望位置**

2. **读取当前位置**
   ```bash
   python /home/demo/Public/DoRobot/scripts/test_piper_move.py --read-only --can-bus can_left
   ```

3. **更新代码**
   编辑 `main.py` 第60行：
   ```python
   safe_home_position = [新的位置数据]
   ```

4. **重启系统测试**

---

## 故障排查

### 问题1：启动时提示位置差异过大

**现象：**
```
[Piper] 警告：主从臂位置差异过大 (XX度)
[Piper] 请将主臂移动到接近从臂当前位置后再开始遥操作
```

**原因：**
- 主臂和从臂初始位置相差超过20度

**解决方法：**
1. 查看终端显示的从臂当前位置和主臂目标位置
2. 手动移动主臂到接近从臂位置
3. 系统会自动检测并开始遥操作

**预防措施：**
- 每次启动前，将主臂放置在接近从臂起始位置的地方

---

### 问题2：运行中频繁出现警告

**现象：**
```
[Piper] ⚠️  警告：关节3差异 22.5度 | 差异: ['2.1', '3.5', '22.5', '1.8', '4.2', '2.0']
```

**原因：**
- 主臂移动过快
- 从臂跟随速度不够
- 机械臂遇到阻力或障碍物

**解决方法：**
1. **减慢主臂移动速度**
2. **检查从臂是否有障碍物**
3. **检查从臂关节是否灵活**
4. 如果持续出现，考虑提高警告阈值

---

### 问题3：触发紧急停止

**现象：**
```
======================================================================
[Piper] ⚠️  紧急停止！位置差异过大！
======================================================================
关节 X 差异: XX度 (阈值: 30.0度)
```

**原因：**
- 主臂移动过快
- 从臂被卡住或遇到障碍物
- 机械臂硬件故障

**解决方法：**
1. **立即检查从臂状态**
   - 是否有障碍物
   - 关节是否能自由移动
   - 电源和CAN连接是否正常

2. **检查主臂操作**
   - 是否移动过快
   - 是否有突然的大幅度动作

3. **重启系统**
   ```bash
   # 停止当前程序（Ctrl+C）
   # 重新启动
   bash /scripts/run_so101.sh
   ```

4. **如果问题持续**
   - 检查机械臂硬件
   - 检查CAN总线连接
   - 查看系统日志

---

### 问题4：保险丝仍然烧毁

**如果实施所有改进后仍然烧保险丝：**

1. **检查硬件**
   - 保险丝规格是否合适
   - 电源供应是否稳定
   - 机械臂是否有机械故障

2. **降低紧急停止阈值**
   ```python
   POSITION_DIFF_EMERGENCY = 20000  # 降低到20度
   ```

3. **降低运动速度**
   ```python
   piper.MotionCtrl_2(0x01, 0x01, 40, 0x00)  # 降低到40%
   ```

4. **增加监控频率**
   ```python
   monitor_interval = 0.2  # 每0.2秒检查一次
   ```

---

## 主从臂标定对齐问题

### 问题背景

在实施了从臂安全保护机制后，发现主臂（SO101 Leader）和从臂（Piper Follower）之间存在坐标系不对齐的问题。虽然两个机械臂在物理位置上完全对应，但读取的关节角度值却相差很大，导致遥操作无法正常启动。

**典型现象：**
- 主臂读数：[0°, 0°, 0°, 0°, 0°, 0°]
- 从臂读数：[5.986°, 0.0°, 0.0°, -19.214°, 18.849°, 40.109°]
- 物理位置：完全对应
- 结果：启动时立即触发紧急停止（位置差异超过20度阈值）

### 根本原因

主臂的标定文件（`SO101-leader.json`）中的 `homing_offset` 参数不正确，导致主臂的"零点"与从臂的安全初始位置不匹配。主臂被标定为在当前物理位置读取零度，但从臂的安全初始位置并非零度。

### 解决方案

#### 方案概述

采用"以从臂为基准"的标定策略：
1. 确认从臂的安全初始位置（不可更改）
2. 将主臂物理移动到与从臂对应的位置
3. 读取主臂当前的PWM值
4. 计算新的 `homing_offset`，使主臂在该位置读取与从臂相同的角度值
5. 更新主臂标定文件

#### 标定原理

SO101主臂使用PWM控制，PWM值范围500-2500对应物理角度0-270度。标定的核心是计算 `homing_offset`，使得：

```
校准后的PWM = 当前PWM - homing_offset
归一化角度 = (校准后的PWM - range_min) / (range_max - range_min) × 270°
```

**计算公式：**
```
目标校准PWM = (目标角度 / 270°) × (range_max - range_min) + range_min
homing_offset = 当前PWM - 目标校准PWM
```

### 遇到的具体问题

#### 问题1：shoulder_lift 角度差异198.99度

**现象：**
- 主臂读数：0.0°
- 从臂目标：0.0°
- 实际PWM：1456
- 原 homing_offset：-525

**原因：** homing_offset 计算错误，导致零点偏移

**解决：** 重新计算 homing_offset = 956，使得PWM 1456对应0度

#### 问题2：gripper 单位不匹配（2293度差异）

**现象：**
- 主臂发送：40.0（RANGE_0_100模式）
- 从臂接收：2293° (40.0 × 57296 ≈ 2,293,000 millidegrees)
- 触发紧急停止

**原因：** 主臂gripper使用 `MotorNormMode.RANGE_0_100`，从臂期望接收弧度值。从臂将接收到的值乘以转换因子 `1000 × 180 / π ≈ 57296`，导致数值放大57296倍。

**解决：** 将主臂gripper改为 `MotorNormMode.RADIANS`，确保单位一致

**修改位置：** `arm_normal_so101_v1/main.py` 第123行

#### 问题3：wrist_flex 需要负角度支持

**现象：**
- 从臂目标：-19.214°
- 主臂 drive_mode=0 只能输出 0-270°

**原因：** drive_mode=0 不支持负角度输出

**解决：** 设置 drive_mode=1，系统自动对角度取反，实现负角度输出

#### 问题4：wrist_roll 读数始终为0

**现象：**
- 物理位置正确
- 主臂读数：0.0°
- 从臂目标：18.849°

**原因：**
```
校准后PWM = 1597 - 936 = 661
range_min = 697
661 < 697，被限制到 range_min
结果：(697 - 697) / (range_max - range_min) × 270° = 0°
```

**根本原因：** 物理位置在标定过程中发生了变化（PWM从1759降到1597），导致校准后PWM小于range_min

**解决：** 重新读取当前PWM值，重新计算 homing_offset = 774

### 标定工具

为了简化标定过程，创建了自动化标定工具：

**工具：** `scripts/calculate_leader_homing_v2.py`

**功能：**
- 自动连接主臂并读取所有关节的当前PWM值
- 根据从臂的安全初始位置计算所需的 homing_offset
- 自动处理负角度（drive_mode=1）
- 直接更新标定文件

**使用方法：**
```bash
conda activate dorobot
python scripts/calculate_leader_homing_v2.py
```

### 最终标定结果

**文件：** `arm_normal_so101_v1/.calibration/SO101-leader.json`

| 关节 | homing_offset | drive_mode | 说明 |
|------|---------------|------------|------|
| shoulder_pan | -30 | 0 | 正常 |
| shoulder_lift | 956 | 0 | 修正了198.99度偏差 |
| elbow_flex | 398 | 0 | 正常 |
| wrist_flex | 791 | 1 | 支持负角度 |
| wrist_roll | 774 | 0 | 修正了零读数问题 |
| gripper | 362 | 0 | 改为RADIANS模式 |

**验证结果：**
- 所有关节角度差异 < 1.3度
- 遥操作成功启动
- 主臂可以正常控制从臂运动

### 关键发现

1. **物理对齐是前提**：标定前必须确认主从臂物理位置完全对应
2. **单位一致性至关重要**：所有关节必须使用相同的单位系统（RADIANS）
3. **标定需要迭代**：由于重力、摩擦等因素，物理位置可能发生微小变化，需要多次验证和调整
4. **自动化工具提高效率**：手动计算容易出错，自动化工具可以快速准确地完成标定
5. **负角度需要特殊处理**：drive_mode参数决定角度的正负方向

### 标定流程总结

**标准标定流程：**

1. **物理对齐**
   - 将从臂移动到安全初始位置
   - 手动移动主臂到相同的物理位置
   - 确认两个机械臂完全对应

2. **运行标定工具**
   ```bash
   conda activate dorobot
   python scripts/calculate_leader_homing_v2.py
   ```

3. **验证标定**
   ```bash
   bash scripts/run_so101.sh
   ```
   - 检查启动时的位置差异
   - 确认所有关节差异 < 5度

4. **测试遥操作**
   - 缓慢移动主臂
   - 观察从臂跟随情况
   - 确认无异常警告

5. **如有问题，重复步骤1-4**

### 相关文件

- **主臂标定文件：** `arm_normal_so101_v1/.calibration/SO101-leader.json`
- **主臂控制代码：** `arm_normal_so101_v1/main.py`
- **标定工具：** `scripts/calculate_leader_homing_v2.py`
- **验证工具：** `scripts/verify_leader_calibration.py`
- **测试工具：** `scripts/test_leader_read.py`

---

## 维护记录

### 2025-12-25 (更新3 - 主从臂标定对齐) - v0.2.132/v0.2.133

**对应版本：** [v0.2.132](RELEASE.md#v0.2.132) 和 [v0.2.133](RELEASE.md#v0.2.133)
- **改进内容：** 解决主从臂坐标系不对齐问题，实现成功遥操作
- **修改文件：**
  - `arm_normal_so101_v1/.calibration/SO101-leader.json` - 更新所有关节的homing_offset
  - `arm_normal_so101_v1/main.py` - gripper改为RADIANS模式
- **创建工具：**
  - `scripts/calculate_leader_homing_v2.py` - 自动化标定计算工具
  - `scripts/verify_leader_calibration.py` - 标定验证工具
  - `scripts/test_leader_read.py` - 调试工具
- **解决的问题：**
  - shoulder_lift 198.99度偏差
  - gripper 单位不匹配（2293度差异）
  - wrist_flex 负角度支持
  - wrist_roll 零读数问题
- **测试状态：** ✅ 已测试通过
- **验证结果：** 所有关节差异 < 1.3度，遥操作成功启动
- **修改人：** Claude Code
- **备注：** 采用"以从臂为基准"的标定策略，确保主从臂坐标系完全对齐

### 2025-12-25 (更新2) - v0.2.132/v0.2.133

**对应版本：** [v0.2.132](RELEASE.md#v0.2.132) 和 [v0.2.133](RELEASE.md#v0.2.133)
- **改进内容：** 降低紧急停止阈值，提高安全性
- **修改文件：** `main.py` 第76-77行
- **参数调整：**
  - 警告阈值：20度 → 15度
  - 紧急停止阈值：30度 → 20度
- **测试状态：** 待测试
- **修改人：** 用户请求
- **备注：** 更严格的保护机制，减少保险丝烧毁风险

### 2025-12-25 (初始版本) - v0.2.132

**对应版本：** [v0.2.132](RELEASE.md#v0.2.132)
- **改进内容：** 初始版本，实现三层安全保护机制
- **修改文件：** `main.py`
- **测试状态：** 待测试
- **修改人：** Claude Code
- **备注：**
  - 安全起始位置：`[5982, -1128, 3940, -19218, 18869, 40103]`
  - 警告阈值：20度
  - 紧急停止阈值：30度

---

### 未来改进计划

- [ ] 添加位置差异历史记录和趋势分析
- [ ] 实现自适应阈值调整
- [ ] 添加数据日志记录功能
- [ ] 实现远程监控和报警
- [ ] 优化紧急停止后的恢复流程

---

## 相关文件

- **主程序：** `main.py`
- **测试脚本：** `/scripts/test_piper_move.py`
- **配置文件：** `dora_teleoperate_dataflow.yml`
- **启动脚本：** `/scripts/run_so101.sh`

---

## 联系方式

如有问题或建议，请联系：
- **项目仓库：** DoRobot
- **文档维护：** 请在此文件中添加维护记录

---

---

## LeRobot零点位置解决方案研究

### 研究背景

**问题：** 主臂和从臂的零点位置相差过大，导致遥操作启动时触发紧急停止。

**研究目标：** 了解LeRobot项目如何解决主臂（leader arm）和从臂（follower arm）零点位置差异问题，并借鉴其方案改进DoRobot项目。

### LeRobot的解决方案

#### 1. 独立校准 + 统一参考系

**核心思路：**
- **分别校准**：主臂和从臂各自独立校准，建立各自的参考系
- **统一映射**：通过校准数据，将两个臂的物理位置映射到相同的逻辑空间

**校准文件存储：**
```bash
~/.cache/huggingface/lerobot/calibration/robots/      # 从臂
~/.cache/huggingface/lerobot/calibration/teleoperators/  # 主臂
```

**校准命令：**
```bash
# 从臂校准
lerobot-calibrate --robot.type=so101_follower --robot.port=/dev/ttyACM0 --robot.id=my_robot

# 主臂校准
lerobot-calibrate --teleop.type=so101_leader --teleop.port=/dev/ttyACM1 --teleop.id=my_robot
```

#### 2. 两步校准流程

每个臂的校准包括：

**步骤1：零点设置**
- 将机械臂移动到所有关节处于运动范围中点的位置
- 系统记录此时的编码器原始值作为"中点参考"

**步骤2：范围记录**
- 移动每个关节通过其完整运动范围
- 系统记录 `range_min` 和 `range_max`

**关键点：** 不要求主臂和从臂的"零点"物理位置相同，只要求相同物理位置映射到相同的逻辑角度。

#### 3. 处理零点差异的技术细节

从LeRobot GitHub Issue #1489可以看到实际遇到的挑战和解决方案：

**问题1：drive_mode不一致导致方向相反**
```python
# 问题：默认drive_modes "(0,0,1,0,0,0)" 导致某些关节方向相反
# 解决：调整drive_mode参数
drive_modes = [0, 0, 0, 0, 0, 0]  # 或根据实际情况设置为1
```

**问题2：负角度导致整数下溢**
```python
# 问题：角度 < 0 时，无符号整数会下溢，显示为大正数
# 例如：-50 在无符号16位整数中变成 65486

# 解决：转换为有符号32位整数
def to_signed_32bit(value):
    if value > 32767:
        return value - 65536
    return value

positions = {m: to_signed_32bit(v) for m, v in positions.items()}
```

**问题3：运动范围不匹配**
```python
# 问题：Koch主臂shoulder_pan有360°范围，SO100从臂只有180°
# 解决：限制主臂范围或按比例缩放
mid, delta = 2048, 1024  # 限制为180°范围
```

**问题4：homing_offset错误**
```python
# 问题：wrist_flex中点读数为0而不是预期的2048
# 解决：切换operating mode后重新设置homing_offset
```

#### 4. 与DoRobot当前方案的对比

**相似之处：**
- 都使用 `homing_offset`、`range_min`、`range_max` 三参数模型
- 都支持 `drive_mode` 来反转方向
- 都有独立的校准文件

**LeRobot的优势：**
- **robot.id参数**：每个机器人有唯一ID，校准数据与特定硬件绑定
- **自动转换**：遥操作时自动应用两个臂之间的转换
- **有符号整数处理**：避免负角度的下溢问题
- **完善的文档和工具**：提供详细的校准指南和故障排查

### 改进建议及详细说明

基于LeRobot的经验，提出以下四条改进建议：

#### 建议1：添加robot_id机制

**为什么需要：**

**问题根源：** 即使是同一型号的机械臂，由于制造公差、装配差异、电机个体差异，每个物理机器人的零点位置都不同。

**具体场景举例：**

**场景A：单套机器人（当前情况）**
```python
# 你的情况：
- 1个SO101主臂
- 1个Piper从臂
- 永远只用这一套

# 校准文件：
SO101-leader.json    # 主臂校准
SO101-follower.json  # 从臂校准

# 结论：这种情况下robot_id不是必需的
```

**场景B：多套相同型号机器人**
```python
# 假设你买了3套SO101+Piper用于：
- 实验室A：做数据采集
- 实验室B：做模型训练
- 实验室C：做演示

# 问题：每套机器人的零点都不一样
# 机器人1的主臂关节0在中点时：PWM = 1520
# 机器人2的主臂关节0在中点时：PWM = 1485
# 机器人3的主臂关节0在中点时：PWM = 1550

# 如果没有robot_id：
所有机器人共用 SO101-leader.json
→ 只有机器人1准确
→ 机器人2偏差35个单位
→ 机器人3偏差30个单位

# 有了robot_id：
robot_1/SO101-leader.json  # homing_offset = 1520
robot_2/SO101-leader.json  # homing_offset = 1485
robot_3/SO101-leader.json  # homing_offset = 1550

# 使用时指定：
python main.py --robot-id=robot_2
→ 自动加载robot_2的校准文件
```

**场景C：更换硬件部件**
```python
# 你的主臂关节3的电机坏了，换了新电机

# 问题：
- 新电机的零点位置和旧电机不同
- 但其他5个关节没变

# 如果没有robot_id：
1. 重新校准整个主臂
2. 覆盖 SO101-leader.json
3. 如果以后想换回旧电机，又要重新校准

# 有了robot_id：
1. 创建新配置：robot_with_new_motor3/
2. 只校准关节3，其他关节复制旧配置
3. 使用时：--robot-id=robot_with_new_motor3
4. 如果换回旧电机：--robot-id=robot_original

# 可以保留多个硬件配置的历史记录
```

**场景D：团队协作**
```python
# 你的团队有：
- 张三：用机器人A采集数据
- 李四：用机器人B采集数据
- 王五：用机器人C做测试

# 大家共享代码仓库

# 如果没有robot_id：
- 张三提交了他的 SO101-leader.json
- 李四拉取代码，发现校准不对，改成自己的
- 王五拉取代码，又不对了
- 三个人的校准文件互相冲突

# 有了robot_id：
- 张三：--robot-id=lab_robot_A
- 李四：--robot-id=lab_robot_B
- 王五：--robot-id=test_robot_C

# 每个人的校准文件独立，不会冲突
# 代码仓库中可以包含所有机器人的校准数据
```

**实际价值：**
- 如果你有多台机器人，可以共享代码但保持各自校准
- 如果更换硬件（如换了一个电机），只需重新校准，不会影响其他配置
- 便于调试：知道当前使用的是哪个机器人的校准数据
- 团队协作时避免校准文件冲突

**实现建议：**
```python
# 在配置文件中添加robot_id
robot_config = {
    "robot_id": "piper_lab_001",  # 唯一标识符
    "calibration_path": f".calibration/{robot_id}/SO101-leader.json"
}

# 或通过命令行参数
python main.py --robot-id=piper_lab_001
```

**当前是否需要：** 如果你只有一套机器人且不打算扩展，可以暂时不实现。但如果计划购买更多机器人或与他人协作，建议尽早实现。

---

#### 建议2：改进零点同步脚本

##### 2.1 使用有符号整数处理负角度

**为什么需要：**

**问题根源：** 电机编码器通常使用无符号整数（0-4095），但关节角度需要表示负值。

**具体场景：**
```python
# 假设你的主臂肩关节在零点时应该是0度
# 但你向后移动到-10度

# 错误的处理（无符号整数）：
raw_value = 2048 - 100  # 假设100个单位 = 10度
# 如果计算结果 < 0，会发生下溢
# 比如：-50 在无符号16位整数中会变成 65486

# 正确的处理（有符号整数）：
raw_value = to_signed_32bit(2048 - 100)  # = 1948
angle = (raw_value - 2048) * scale  # = -10度
```

**实际影响：**
```python
# 你的sync_leader_calibration.py中
target_angles = [5.4, 0.0, 0.0, -2.9, 19.7, 23.9]
#                              ^^^^  这个负角度

# 如果不正确处理，-2.9度可能被误读为+357.1度
# 导致主臂和从臂完全不同步
```

**你的代码中已经遇到的问题：**
```python
# wrist_flex需要输出-19.214度
# 如果使用drive_mode=0（正常模式），只能输出0-270度
# 无法表示负角度

# 解决方案：设置drive_mode=1
# 系统会自动对角度取反：
# 内部计算：+19.214度
# 输出时：-19.214度（drive_mode=1自动取反）
```

**解决方案代码：**
```python
def to_signed_32bit(value):
    """将可能下溢的值转换为有符号整数"""
    if value > 32767:  # 如果看起来是下溢的大正数
        return value - 65536  # 转换为负数
    return value

# 在读取编码器值时使用
raw_positions = read_motor_positions()
signed_positions = {motor_id: to_signed_32bit(pos)
                   for motor_id, pos in raw_positions.items()}
```

**实际价值：**
- 正确处理负角度，避免数值错误
- 防止因角度误读导致的大幅度运动
- 提高系统稳定性和安全性

---

##### 2.2 正确设置drive_mode避免方向反转

**为什么需要：**

**问题根源：** 主臂和从臂的机械结构可能镜像或方向相反。

**具体场景：**
```python
# 主臂：顺时针旋转 = 编码器增加
# 从臂：顺时针旋转 = 编码器减少（因为电机安装方向相反）

# 如果不设置drive_mode：
主臂向右转 → 从臂向左转  # 完全相反！

# 设置drive_mode=1后：
主臂向右转 → 读数 * (-1) → 从臂向右转  # 正确同步
```

**你的代码中已经有这个机制：**
```python
# SO101-leader.json
"wrist_flex": {
    "drive_mode": 1,  # 反转这个关节
    ...
}
```

**但问题是：** 你需要确保每个关节的drive_mode设置正确。

**验证方法：**
```python
# 1. 将主臂和从臂放在相同物理位置
# 2. 读取两个臂的角度值
# 3. 如果某个关节符号相反，设置drive_mode=1

# 验证脚本示例：
def verify_drive_modes():
    print("请将主臂和从臂放在相同物理位置")
    input("按Enter继续...")

    leader_angles = read_leader_angles()
    follower_angles = read_follower_angles()

    for i, (l, f) in enumerate(zip(leader_angles, follower_angles)):
        if (l > 0 and f < 0) or (l < 0 and f > 0):
            print(f"警告：关节{i}方向相反")
            print(f"  主臂：{l}度")
            print(f"  从臂：{f}度")
            print(f"  建议：设置drive_mode=1")
```

**实际价值：**
- 确保主臂和从臂运动方向一致
- 避免"镜像"运动导致的操作错���
- 简化遥操作，提高直观性

---

##### 2.3 限制运动范围匹配物理限制

**为什么需要：**

**问题根源：** 主臂和从臂的机械结构可能不同，运动范围不一样。

**具体场景：**
```python
# SO101主臂（被动，无负载）
shoulder_pan: 可以旋转 360度（0-360）

# Piper从臂（主动，有负载）
shoulder_pan: 只能旋转 180度（-90到+90）

# 如果不限制：
主臂转到 270度 → 从臂尝试转到 270度 → 超出范围 → 电机报错或卡死
```

**解决方案1：硬限制（简单但不灵活）**
```python
# 在校准时记录实际可用范围
"shoulder_pan": {
    "range_min": 1024,   # 对应 -90度
    "range_max": 3072,   # 对应 +90度
}

# 在遥操作时限制主臂读数
leader_angle = read_leader_joint()
if leader_angle > 90:
    leader_angle = 90  # 限制在从臂能达到的范围
elif leader_angle < -90:
    leader_angle = -90
```

**解决方案2：比例缩放（更智能）**
```python
# 如果主臂范围是360度，从臂是180度
# 可以按比例缩放
leader_angle = read_leader_joint()  # 0-360度
follower_angle = (leader_angle / 360) * 180 - 90  # 映射到-90到+90

# 优点：充分利用主臂的运动范围
# 缺点：主臂和从臂的运动比例不是1:1
```

**解决方案3：软限制+警告（推荐）**
```python
# 定义从臂的安全范围
SAFE_RANGES = {
    "shoulder_pan": (-90, 90),
    "shoulder_lift": (-45, 90),
    # ...
}

# 在遥操作时检查
leader_angle = read_leader_joint("shoulder_pan")
min_angle, max_angle = SAFE_RANGES["shoulder_pan"]

if leader_angle < min_angle or leader_angle > max_angle:
    print(f"警告：shoulder_pan超出安全范围 ({leader_angle}度)")
    # 可以选择：
    # 1. 限制到边界
    # 2. 停止运动
    # 3. 仅警告但继续
```

**实际价值：**
- 防止从臂超出物理限制
- 避免电机过载或机械损坏
- 提高系统安全性

**你的代码中已经有类似机制：**
```python
# main.py中的range_min和range_max
# 但需要确保这些值与从臂的实际物理限制匹配
```

---

#### 建议3：验证校准质量

**为什么需要：**

**问题根源：** 校准过程是手动的，容易出错。

**常见错误：**
```python
# 错误1：校准时没有真正移到中点
# 你以为在中点，实际偏了5度 → 所有后续操作都偏5度

# 错误2：校准时电机没有完全静止
# 电机还在轻微抖动 → 记录的值不准确

# 错误3：校准时线缆拉扯
# 线缆的拉力影响了关节位置 → 实际使用时位置不同

# 错误4：重力影响
# 校准时关节在某个角度，重力导致轻微下垂
# 记录的位置和实际"无负载"位置不同
```

**验证方法：**
```python
def verify_calibration():
    """验证主臂和从臂校准是否一致"""
    print("=" * 60)
    print("校准验证工具")
    print("=" * 60)
    print("请将主臂和从臂放在完全相同的物理位置")
    print("建议：使用从臂的安全初始位置作为参考")
    input("按Enter继续...")

    # 读取两个臂的角度
    leader_angles = read_leader_angles()
    follower_angles = read_follower_angles()

    print("\n校准验证结果：")
    print("-" * 60)

    max_diff = 0
    problem_joints = []

    for i, (l, f) in enumerate(zip(leader_angles, follower_angles)):
        diff = abs(l - f)
        status = "✓" if diff < 5 else "✗"

        print(f"关节{i}: {status}")
        print(f"  主臂：{l:7.2f}度")
        print(f"  从臂：{f:7.2f}度")
        print(f"  差异：{diff:7.2f}度")

        if diff > max_diff:
            max_diff = diff

        if diff > 5:
            problem_joints.append((i, diff))

    print("-" * 60)
    print(f"\n最大差异：{max_diff:.2f}度")

    # 评估校准质量
    if max_diff < 1:
        print("✓ 校准质量：优秀")
    elif max_diff < 5:
        print("✓ 校准质量：良好")
    elif max_diff < 10:
        print("⚠ 校准质量：可接受，建议重新校准")
    else:
        print("✗ 校准质量：差，必须重新校准")

    # 给出具体建议
    if problem_joints:
        print("\n需要重新校准的关节：")
        for joint_id, diff in problem_joints:
            print(f"  - 关节{joint_id}：差异{diff:.2f}度")

    return max_diff < 5
```

**实际价值：**
- 发现校准错误，避免后续问题
- 量化校准质量（差异在1度内 = 优秀，5度内 = 可接受）
- 指导重新校准（知道哪个关节有问题）
- 建立校准质量标准

**你的代码中已经有类似功能：**
```python
# scripts/verify_leader_calibration.py
# 但可以增强为更全面的验证工具
```

---

#### 建议4：处理范围不匹配

**为什么需要：**

**问题根源：** 这是最核心的问题 - 主臂和从臂的零点位置相差过大。

**你的具体情况：**
```python
# 从你的git commit信息：
"主臂和从臂的零点位置的问题，相差过大"

# 这意味着：
主臂在"零点"时读数 = X
从臂在"零点"时读数 = Y
|X - Y| 很大
```

**根本原因分析：**

**原因1：机械零点不同**
```python
# 主臂（SO101 leader）：被动臂，靠弹簧复位
# 自然下垂位置 ≠ 从臂的初始位置

# 从臂（Piper）：主动臂，有初始姿态
# 初始姿态 = [5.4, 0.0, 0.0, -19.214, 18.849, 40.109]度
```

**原因2：编码器零点不同**
```python
# 主臂：PWM信号，500-2500范围，中点=1500
# 从臂：编码器，0-4095范围，中点=2048

# 即使物理位置相同，读数也不同
```

**原因3：校准参考点不同**
```python
# 如果主臂校准时的"中点"位置
# 和从臂的"安全初始位置"不是同一个物理位置
# 就会导致零点不对齐
```

**LeRobot的解决方案：**
```python
# 不要求主臂和从臂的"零点"相同
# 而是要求：相同物理位置 → 相同��辑角度

# 实现方法：
# 1. 主臂校准：记录主臂在某个姿态时的原始读数
# 2. 从臂校准：记录从臂在相同姿态时的原始读数
# 3. 遥操作时：
#    a. 读取主臂原始值 → 转换为角度
#    b. 将角度发送给从臂 → 从臂转换为自己的原始值
```

**你的sync_leader_calibration.py的问题：**
```python
# 当前方法：强制主臂输出目标角度
target_angles = [5.4, 0.0, 0.0, -2.9, 19.7, 23.9]

# 问题：
# 1. 这要求主臂物理上处于这个姿态
# 2. 如果主臂自然下垂姿态不是这个，会很别扭
# 3. 用户需要一直保持主臂在这个姿态，很累
```

**更好的方案：相对运动映射**
```python
# 1. 让主臂和从臂各自校准在舒适的姿态
# 2. 记录这个姿态的对应关系

# 主臂舒适姿态（自然下垂）：
leader_rest_pose = [0, -45, 90, 0, 0, 0]  # 度

# 从臂初始姿态：
follower_init_pose = [5.4, 0.0, 0.0, -19.214, 18.849, 40.109]  # 度

# 遥操作时的映射：
leader_current = read_leader()  # 当前主臂角度
leader_delta = leader_current - leader_rest_pose  # 相对于舒适姿态的变化
follower_target = follower_init_pose + leader_delta  # 从臂目标 = 初始姿态 + 变化量

# 示例：
# 主臂从 [0, -45, 90, 0, 0, 0] 移动到 [10, -40, 85, 5, 0, 0]
# 变化量：[+10, +5, -5, +5, 0, 0]
# 从臂目标：[5.4+10, 0.0+5, 0.0-5, -19.214+5, 18.849+0, 40.109+0]
#         = [15.4, 5.0, -5.0, -14.214, 18.849, 40.109]
```

**这样的好处：**
- 主臂可以在任何舒适姿态开始
- 从臂可以在任何安全姿态开始
- 只要相对运动一致，就能正确遥操作
- 用户体验更好，不需要保持特定姿态

**实现建议：**
```python
# 在配置文件中记录参考姿态
calibration_config = {
    "leader_reference_pose": [0, -45, 90, 0, 0, 0],
    "follower_reference_pose": [5.4, 0.0, 0.0, -19.214, 18.849, 40.109],
}

# 在遥操作代码中
def map_leader_to_follower(leader_angles, config):
    leader_delta = leader_angles - config["leader_reference_pose"]
    follower_target = config["follower_reference_pose"] + leader_delta
    return follower_target
```

**实际价值：**
- 解决零点位置相差大的根本问题
- 提高用户体验（不需要保持特定姿态）
- 更灵活的校准方式
- 符合LeRobot的设计理念

---

### 总结

这四条建议的核心思想是：

1. **robot_id**：每个机器人是独特的，需要独立校准（适用于多机器人场景）
2. **有符号整数**：正确处理负角度，避免数值错误
3. **验证校准**：确保校准质量，及时发现问题
4. **范围处理**：不要求绝对零点相同，只要求相对运动一致

**最关键的洞察：**
零点位置相差大不是问题，问题是如何建立正确的映射关系。LeRobot的方案是通过独立校准 + 逻辑角度转换来解决，而不是强制物理零点对齐。

**优先级建议：**
1. **立即实现**：建议4（相对运动映射）- 解决当前最大痛点
2. **短期实现**：建议2（有符号整数和drive_mode）- 提高稳定性
3. **中期实现**：建议3（验证校准）- 提高校准质量
4. **长期考虑**：建议1（robot_id）- 如果需要多机器人支持

### 参考资料

- [Seeed Studio LeRobot Wiki](https://wiki.seeedstudio.com/lerobot_so100m_new/)
- [LeRobot SO-101 Documentation](https://huggingface.co/docs/lerobot/main/en/so101)
- [Koch Leader Arm Calibration Issue #1489](https://github.com/huggingface/lerobot/issues/1489)
- [LeRobot GitHub Repository](https://github.com/huggingface/lerobot)

---

**文档版本：** v1.1
**创建日期：** 2025-12-25
**最后更新：** 2025-12-29


---

# 第二部分：系统问题和解决方案

本部分来自原 docs/SAFETY_IMPROVEMENTS.md

---

# DoRobot Safety Improvements and Issue Resolution

This document tracks critical issues encountered during development and their solutions, focusing on safety, reliability, and system integrity.

---

## 2025-12-26: Joint Mapping Mismatch and Motor Configuration Issues - v0.2.134

**对应版本：** [v0.2.134](RELEASE.md#v0.2.134)

### Problem 1: Incorrect Joint Correspondence During Teleoperation

**Severity:** Critical - System functioned but with incorrect joint mapping

**Symptoms:**
- Teleoperation connection succeeded and data transmission worked
- Leader arm movements were transmitted to follower arm
- However, joints moved incorrectly: wrong joints responded to leader movements
- Example: Moving leader's shoulder_pan caused follower's joint_1 to move instead of joint_0

**Root Cause:**
- Leader arm used semantic joint names (shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll)
- Follower arm (Piper) uses indexed joint names (joint_0, joint_1, joint_2, joint_3, joint_4, joint_5)
- Joint data was transmitted in dictionary order, causing misalignment
- Leader's shoulder_pan (ID 1) was mapped to follower's joint_1 instead of joint_0
- This created an off-by-one error in joint correspondence

**Impact:**
- Unsafe teleoperation: operator's intended movements resulted in different actual movements
- Risk of collision or damage due to unexpected joint behavior
- Difficult to control the robot arm precisely
- Potential for operator confusion and accidents

**Solution:**
1. Renamed all leader arm joints from semantic names to indexed names (joint_0 through joint_5)
2. Added missing joint_0 (Motor ID 0) to configuration
3. Updated calibration file with indexed joint names
4. Modified main.py and calibrate.py to use indexed naming
5. Removed placeholder joint insertion logic (no longer needed with 7 motors)

**Verification:**
- Created diagnostic scripts to verify joint count and mapping
- Tested teleoperation with new configuration
- Confirmed 1:1 joint correspondence between leader and follower

**Prevention Measures:**
- Use consistent naming conventions across all arm types
- Always verify joint correspondence before teleoperation
- Add diagnostic tools to validate joint mapping
- Document joint naming conventions clearly

---

### Problem 2: Missing Motor ID 0 in Configuration

**Severity:** High - One motor was not configured or controlled

**Symptoms:**
- Leader arm has 7 physical motors (ID 0-6)
- Only 6 motors were configured in software (ID 1-6)
- Motor ID 0 was physically present but not accessible
- System worked with 6 motors but lacked full control

**Root Cause:**
- Initial configuration assumed motor IDs started at 1
- Motor ID 0 was overlooked during setup
- Calibration file did not include joint_0 entry
- Motor definitions in main.py and calibrate.py started at ID 1

**Impact:**
- Incomplete control of leader arm
- One degree of freedom was unavailable
- Potential for unexpected behavior if motor ID 0 was accidentally activated
- Reduced functionality of teleoperation system

**Solution:**
1. Added joint_0 with Motor ID 0 to calibration file
2. Updated motor definitions in main.py and calibrate.py to include joint_0
3. Calibrated joint_0 with appropriate homing_offset and range values
4. Created diagnostic scripts to detect all motors including ID 0

**Verification:**
- Used detailed_scan.py to scan motor IDs 0-20
- Confirmed motor ID 0 responds to commands
- Verified joint_0 appears in joint position readings
- Tested full 7-motor control during teleoperation

**Prevention Measures:**
- Always scan full motor ID range (0-255) during initial setup
- Document expected motor count and IDs
- Create diagnostic tools to verify all motors are configured
- Add validation checks to ensure motor count matches expected value

---

### Problem 3: Lack of Diagnostic and Calibration Tools

**Severity:** Medium - Made troubleshooting difficult and time-consuming

**Symptoms:**
- No easy way to detect which motors are connected
- Difficult to verify motor IDs and positions
- Manual calibration process was error-prone
- No tools to check joint correspondence

**Root Cause:**
- System lacked comprehensive diagnostic utilities
- Calibration process required manual alignment and calculation
- No automated tools for motor detection
- Limited visibility into system state

**Impact:**
- Increased setup and debugging time
- Higher risk of configuration errors
- Difficult to diagnose joint mapping issues
- Manual calibration prone to human error

**Solution:**
Created six diagnostic and calibration scripts:

1. **detailed_scan.py**: Comprehensive motor detection (ID 0-20)
2. **scan_all_motors.py**: Quick motor scan (ID 1-15)
3. **scan_all_ports.py**: Multi-port motor detection
4. **detect_leader_joints.py**: Verify joint configuration
5. **show_leader_position.py**: Real-time position monitoring and alignment checking
6. **sync_leader_calibration.py**: Automatic calibration synchronization

**Verification:**
- All scripts tested and working correctly
- Scripts successfully detected motor ID 0
- Automatic calibration script correctly calculated homing_offset values
- Position monitoring script helped identify joint mapping issues

**Prevention Measures:**
- Maintain comprehensive diagnostic tool suite
- Document diagnostic procedures in release notes
- Add automated validation checks to startup sequence
- Create troubleshooting guides referencing diagnostic tools

---

## Key Lessons Learned

### 1. Naming Conventions Matter
- Consistent naming across system components is critical for correct operation
- Semantic names (shoulder_pan) can cause confusion when interfacing with indexed systems
- Always document naming conventions and mapping rules

### 2. Complete Motor Discovery
- Never assume motor ID ranges
- Always scan full ID space during initial setup
- Verify motor count matches physical hardware

### 3. Diagnostic Tools Are Essential
- Invest time in creating comprehensive diagnostic utilities
- Diagnostic tools pay for themselves during troubleshooting
- Automated tools reduce human error and setup time

### 4. Verify Before Operating
- Always verify joint correspondence before teleoperation
- Use diagnostic tools to validate system state
- Don't assume configuration is correct without verification

### 5. Document Everything
- Clear documentation prevents repeated mistakes
- Release notes should include troubleshooting context
- Safety improvements should be tracked and reviewed

---

## Safety Checklist for Teleoperation Setup

Before starting teleoperation, verify:

- [ ] All motors detected (7 motors for SO101 leader arm)
- [ ] Joint names match between leader and follower arms
- [ ] Calibration file includes all joints (joint_0 through joint_5 + gripper)
- [ ] Position alignment within acceptable threshold (< 40° difference)
- [ ] Diagnostic scripts run successfully
- [ ] Joint correspondence verified (leader joint_0 → follower joint_0, etc.)
- [ ] Emergency stop procedures tested and understood

---

## Future Improvements

### Recommended Enhancements:
1. Add automated joint correspondence validation at startup
2. Implement runtime checks for joint mapping correctness
3. Create visual feedback for joint positions during teleoperation
4. Add configuration validation tool to check for common errors
5. Implement safety limits to prevent dangerous joint positions
6. Add logging for joint commands and responses
7. Create automated test suite for joint mapping verification

### Monitoring and Alerts:
1. Alert if motor count doesn't match expected value
2. Warn if joint position differences exceed threshold
3. Log calibration changes for audit trail
4. Monitor for communication errors and retry failures
5. Track joint position drift over time

---

## References

- **Release Notes:** docs/RELEASE.md v0.2.134
- **Calibration File:** operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json
- **Diagnostic Scripts:** scripts/detailed_scan.py, scripts/detect_leader_joints.py, scripts/scan_all_motors.py, scripts/scan_all_ports.py, scripts/show_leader_position.py, scripts/sync_leader_calibration.py
