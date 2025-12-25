# SO101 机械臂组件

## 概述

本组件用于控制 SO101 系列机械臂，支持作为主臂（Leader）或从臂（Follower）使用。主要用于遥操作场景，其中 SO101 主臂通过 Zhonglin ASCII 协议读取关节位置，并通过 DORA 数据流框架将数据传输给从臂执行。

## 硬件规格

### 主臂（Leader Arm）
- **型号**: SO101
- **控制器**: ZP10D
- **通信协议**: Zhonglin ASCII 协议
- **接口**: 串口（USB 转串口）
- **波特率**: 115200
- **关节数量**: 6 个关节 + 1 个夹爪
  - shoulder_pan（肩部旋转）
  - shoulder_lift（肩部抬升）
  - elbow_flex（肘部弯曲）
  - wrist_flex（腕部弯曲）
  - wrist_roll（腕部旋转）
  - gripper（夹爪）
- **编码器**: PWM 值范围 500-2500（对应 0-270 度）
- **工作模式**: 被动读取（无力矩控制）

### 从臂（Follower Arm）
- **型号**: Piper
- **通信协议**: CAN 总线
- **接口**: CAN 接口
- **工作模式**: 主动控制（位置控制）

## 遥操作原理

### 数据流架构

```
主臂硬件 → Zhonglin 协议读取 → 标定转换 → 标准关节角度
                                              ↓
                                         DORA 传输 (PyArrow)
                                              ↓
从臂硬件 ← Piper CAN 协议 ← 单位转换 ← 接收关节角度
```

### 工作流程

1. **主臂数据采集** (30Hz)
   - 通过 Zhonglin ASCII 协议读取 6 个关节的 PWM 值
   - 使用标定数据将 PWM 值转换为标准化角度（弧度或度）
   - 输出格式: `[j1, j2, j3, j4, j5, j6]`

2. **数据传输**
   - 使用 DORA 框架的 PyArrow 进行零拷贝数据传输
   - 主臂输出 `joint` → 从臂输入 `action_joint`
   - 传输延迟: ~10-20ms

3. **从臂执行**
   - 接收标准化角度数据
   - 转换为 Piper 协议要求的单位（0.001 度）
   - 通过 CAN 总线发送给从臂执行
   - 执行频率: 30Hz（限流保护）

### 关节映射

主臂和从臂通过 **电机 ID 顺序** 直接对应：

| 电机 ID | 主臂关节 | 从臂关节 | 数组索引 |
|---------|----------|----------|----------|
| 1 | shoulder_pan | joint_1 | [0] |
| 2 | shoulder_lift | joint_2 | [1] |
| 3 | elbow_flex | joint_3 | [2] |
| 4 | wrist_flex | joint_4 | [3] |
| 5 | wrist_roll | joint_5 | [4] |
| 6 | gripper | joint_6 | [5] |

**注意**: 这是 1:1 直接映射，没有复杂的坐标变换，假设主从臂的运动学结构相同或兼容。

## 为什么需要标定

### 标定的作用

1. **零点校准**
   - 不同机械臂的机械装配存在误差
   - 标定设置统一的零点参考，确保主从臂姿态一致

2. **运动范围映射**
   - 原始 PWM 值（500-2500）→ 标准化角度（度或弧度）
   - 记录每个关节的物理运动范围（range_min, range_max）
   - 防止关节超限，保护机械结构

3. **数据标准化**
   - 将不同协议的原始数据转换为统一格式
   - 便于主从臂之间的数据交换
   - 支持不同型号机械臂的互操作

### 标定数据格式

标定文件保存在 `.calibration/SO101-leader.json`，包含每个关节的：

```json
{
    "shoulder_pan": {
        "id": 1,
        "drive_mode": 0,
        "homing_offset": -1894,    // 零点偏移量
        "range_min": 771,           // 最小 PWM 值
        "range_max": 3484           // 最大 PWM 值
    },
    ...
}
```

### 标定公式

```python
# 标准化（读取时）
normalized_angle = ((pwm_value - range_min) / (range_max - range_min)) * angle_range

# 反标准化（写入时）
pwm_value = (normalized_angle / angle_range) * (range_max - range_min) + range_min
```

## 环境设置

### 1. 激活 Conda 环境

```bash
conda activate dorobot
```

### 2. 设置串口环境变量

查找主臂串口设备：

```bash
# 查看所有串口设备
ls -la /dev/serial/by-path/

# 或查看 USB 串口
ls /dev/ttyUSB* /dev/ttyACM*
```

设置环境变量：

```bash
# 使用持久化路径（推荐）
export ARM_LEADER_PORT="/dev/serial/by-path/pci-0000:00:14.0-usb-0:2:1.0-port0"

# 或使用简单路径
export ARM_LEADER_PORT="/dev/ttyUSB0"
```

### 3. 检查串口权限

```bash
# 添加用户到 dialout 组（需要重新登录生效）
sudo usermod -a -G dialout $USER

# 或临时修改权限
sudo chmod 666 $ARM_LEADER_PORT
```

## 主臂标定流程

### 准备工作

1. 确保主臂已连接并上电
2. 确保串口设备可访问
3. 激活 conda 环境并设置环境变量

### 标定步骤

#### 1. 进入组件目录

```bash
cd /home/demo/Public/DoRobot/operating_platform/robot/components/arm_normal_so101_v1
```

#### 2. 运行标定程序

```bash
dora run dora_calibrate_leader.yml
```

#### 3. 设置零点（按 'm' 键）

程序启动后会显示：

```
================================================================================
CALIBRATION SETUP - SO101-leader
================================================================================

Current joint positions (live update):
Move SO101-leader to the middle of its range of motion and press key 'm'...
================================================================================
```

**操作**:
- 手动将主臂移动到一个**舒适、对称的姿态**
- 建议姿态：手臂向前伸展，肘部微弯，手腕水平
- 各关节应大约在其物理运动范围的中间
- 按 **'m'** 键设置零点

#### 4. 记录运动范围（移动关节）

按 'm' 键后，屏幕会显示实时更新的表格：

```
====================================================================================================
Joint           Current    Min        Max        Range
----------------------------------------------------------------------------------------------------
shoulder_pan    1523       1200       1850       650
shoulder_lift   1456       1100       1800       700
elbow_flex      1612       1300       1900       600
wrist_flex      1389       1150       1750       600
wrist_roll      1701       1400       2000       600
gripper         2145       1900       2300       400
====================================================================================================
Move each joint through its full range. Press 'e' to finish.
```

**操作**:
- **依次移动每个关节**到其最大和最小位置
- 观察表格中的 **Min**、**Max** 和 **Range** 值变化
- 确保每个关节的 Range 值合理（通常 500-1500 之间）
- 移动顺序建议：
  1. shoulder_pan（肩部旋转）：左右旋转到极限
  2. shoulder_lift（肩部抬���）：上下移动到极限
  3. elbow_flex（肘部弯曲）：伸直和弯曲到极限
  4. wrist_flex（腕部弯曲）：上下弯曲到极限
  5. wrist_roll（腕部旋转）：左右旋转到极限
  6. gripper（夹爪）：完全打开和关闭

#### 5. 完成标定（按 'e' 键）

确认所有关节都已移动到极限位置后，按 **'e'** 键。

程序会显示：

```
[Zhonglin] Recording completed
Calibration saved to .calibration/SO101-leader.json
Calibrate Finish, Press "CTRL + C" to stop Dora dataflow
```

#### 6. 退出程序

按 **Ctrl+C** 停止程序。

### 验证标定

查看标定文件：

```bash
cat .calibration/SO101-leader.json
```

检查每个关节的 `range_min` 和 `range_max` 是否合理。

## 运行遥操作

### 1. 设置环境变量

```bash
# 主臂串口
export ARM_LEADER_PORT="/dev/ttyUSB0"

# 从臂 CAN 总线（如果使用 Piper 从臂）
export ARM_FOLLOWER_PORT="can0"

# 摄像头（可选）
export CAMERA_TOP_PATH="0"
export CAMERA_WRIST_PATH="2"
```

### 2. 启动遥操作

```bash
cd /home/demo/Public/DoRobot/operating_platform/robot/robots/so101_v1
dora run dora_teleoperate_dataflow.yml
```

### 3. 操作主臂

- 手动移动主臂，从臂会实时跟随
- 观察从臂是否准确复现主臂的动作
- 如果动作不准确，可能需要重新标定

### 4. 停止遥操作

按 **Ctrl+C** 停止程序。

## 故障排除

### 问题 1: 找不到串口设备

**错误信息**: `FileNotFoundError: [Errno 2] No such file or directory: '/dev/ttyUSB0'`

**解决方法**:
```bash
# 查找实际的串口设备
ls /dev/ttyUSB* /dev/ttyACM*

# 或使用持久化路径
ls -la /dev/serial/by-path/

# 更新环境变量
export ARM_LEADER_PORT="/dev/ttyUSB1"  # 使用实际设备
```

### 问题 2: 串口权限不足

**错误信息**: `PermissionError: [Errno 13] Permission denied: '/dev/ttyUSB0'`

**解决方法**:
```bash
# 方法 1: 添加用户到 dialout 组（永久）
sudo usermod -a -G dialout $USER
# 需要重新登录

# 方法 2: 临时修改权限
sudo chmod 666 /dev/ttyUSB0
```

### 问题 3: 标定数据不合理

**症状**: Range 值过小（<100）或过大（>2000）

**解决方法**:
- 重新标定，确保每个关节都移动到物理极限
- 检查机械臂是否有机械卡顿
- 确认 PWM 范围设置正确（500-2500）

### 问题 4: 从臂不跟随主臂

**可能原因**:
1. 标定数据不正确 → 重新标定
2. 从臂未连接 → 检查 CAN 总线连接
3. 数据流配置错误 → 检查 `dora_teleoperate_dataflow.yml`

### 问题 5: 缺少 Python 依赖

**错误信息**: `ModuleNotFoundError: No module named 'pyarrow'`

**解决方法**:
```bash
# 确保激活了正确的 conda 环境
conda activate dorobot

# 检查 pyarrow 是否安装
python -c "import pyarrow; print(pyarrow.__version__)"
```

## 文件说明

- `main.py` - 主程序，支持主臂和从臂模式
- `calibrate.py` - 标定程序
- `keybord.py` - 键盘输入节点（用于标定）
- `dora_calibrate_leader.yml` - 标定数据流配置
- `motors/zhonglin.py` - Zhonglin 协议驱动
- `motors/feetech/` - Feetech 协议驱动（用于从臂）
- `.calibration/` - 标定数据目录
  - `SO101-leader.json` - 主臂标定数据
  - `SO101-follower.json` - 从臂标定数据（如果使用 SO101 作为从臂）

## 技术细节

### Zhonglin ASCII 协议

主臂使用 Zhonglin ASCII 协议通信，主要命令：

```
#001PRAD!  - 读取 ID=1 电机的位置（返回 PWM 值）
#001P1500T1000!  - 设置 ID=1 电机到 PWM=1500，时间 1000ms
#000PVER!  - 查询版本
```

响应格式: `P1523` (PWM 值为 1523)

### 数据转换

```python
# PWM → 角度
angle = (pwm_value - pwm_min) / (pwm_max - pwm_min) * angle_range

# 角度 → 弧度（用于从臂）
radians = angle * (π / 180)

# 弧度 → Piper 单位（0.001 度）
piper_value = radians * (180 / π) * 1000
```

### 性能指标

- **采样频率**: 30 Hz
- **传输延迟**: 10-20 ms
- **端到端延迟**: 60-100 ms
- **位置精度**: ±1 度

## 参考资料

- [DORA 框架文档](https://github.com/dora-rs/dora)
- [Zhonglin 舵机手册](https://www.zhonglin-servo.com/)
- [Piper 机械臂文档](https://github.com/agilexrobotics/piper_sdk)

## 维护记录

- 2025-12-25: 添加 Zhonglin 主臂标定支持
- 2025-12-25: 改进标定界面，添加实时数值显示
- 2025-12-25: 创建 README 文档

## 联系方式

如有问题，请联系项目维护者或提交 Issue。
