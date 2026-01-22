# 主臂协议切换指南：从众灵到 Feetech

本文档记录了将 SO101 主臂从众灵（Zhonglin）协议切换到 Feetech 协议所需的所有修改。

## 修改概述

主臂协议切换涉及以下几个方面：
1. 代码层面：添加协议选择逻辑和 Feetech 协议支持
2. 标定文件：更新主臂标定参数
3. 配置文件：更新数据流配置
4. 电机总线：添加 RADIANS 归一化模式支持

---

## 1. 代码修改

### 1.1 添加协议选择环境变量

**文件：** `operating_platform/robot/components/arm_normal_so101_v1/main.py`

**修改位置：** 第 48 行

```python
# 添加新的环境变量
MOTOR_PROTOCOL = os.getenv("MOTOR_PROTOCOL", "auto")  # auto, feetech, zhonglin
```

**说明：**
- `auto`（默认）：根据 ARM_ROLE 自动选择（leader 用 zhonglin，follower 用 feetech）
- `feetech`：显式使用 Feetech 协议
- `zhonglin`：显式使用众灵协议

### 1.2 协议选择逻辑

**文件：** `operating_platform/robot/components/arm_normal_so101_v1/main.py`

**修改位置：** 第 111-165 行

```python
# 确定使用的协议
use_protocol = MOTOR_PROTOCOL
if use_protocol == "auto":
    use_protocol = "zhonglin" if ARM_ROLE == "leader" else "feetech"

# 根据协议选择电机总线
if use_protocol == "zhonglin":
    # 众灵 ASCII 协议（ZP10D 控制器）- 原始 SO101 主臂
    arm_bus = ZhonglinMotorsBus(
        port=PORT,
        motors={
            "joint_0": Motor(0, "zhonglin", MotorNormMode.RADIANS),
            "joint_1": Motor(1, "zhonglin", MotorNormMode.RADIANS),
            "joint_2": Motor(2, "zhonglin", MotorNormMode.RADIANS),
            "joint_3": Motor(3, "zhonglin", MotorNormMode.RADIANS),
            "joint_4": Motor(4, "zhonglin", MotorNormMode.RADIANS),
            "joint_5": Motor(5, "zhonglin", MotorNormMode.RADIANS),
            "gripper": Motor(6, "zhonglin", MotorNormMode.RADIANS),
        },
        calibration=arm_calibration,
        baudrate=115200,
    )
elif use_protocol == "feetech":
    if ARM_ROLE == "leader":
        # Feetech 协议主臂（新配置）
        # 主臂输出弧度值，用于与 Piper 从臂兼容
        arm_bus = FeetechMotorsBus(
            port=PORT,
            motors={
                "joint_0": Motor(0, "sts3215", MotorNormMode.RADIANS),
                "joint_1": Motor(1, "sts3215", MotorNormMode.RADIANS),
                "joint_2": Motor(2, "sts3215", MotorNormMode.RADIANS),
                "joint_3": Motor(3, "sts3215", MotorNormMode.RADIANS),
                "joint_4": Motor(4, "sts3215", MotorNormMode.RADIANS),
                "joint_5": Motor(5, "sts3215", MotorNormMode.RADIANS),
                "gripper": Motor(6, "sts3215", MotorNormMode.RADIANS),
            },
            calibration=arm_calibration,
        )
    else:
        # Feetech 协议从臂（原始配置）
        arm_bus = FeetechMotorsBus(
            port=PORT,
            motors={
                "joint_0": Motor(0, "sts3215", norm_mode_body),
                "joint_1": Motor(1, "sts3215", norm_mode_body),
                "joint_2": Motor(2, "sts3215", norm_mode_body),
                "joint_3": Motor(3, "sts3215", norm_mode_body),
                "joint_4": Motor(4, "sts3215", norm_mode_body),
                "joint_5": Motor(5, "sts3215", norm_mode_body),
                "gripper": Motor(6, "sts3215", MotorNormMode.RANGE_0_100),
            },
            calibration=arm_calibration,
        )
else:
    raise ValueError(f"Unknown MOTOR_PROTOCOL: {use_protocol}. Use 'auto', 'feetech', or 'zhonglin'")
```

**关键变化：**
- 主臂使用 `MotorNormMode.RADIANS` 输出弧度值
- 电机 ID 使用 0-based 索引（joint_0 的 ID 为 0）
- 关节命名标准化为 `joint_0` 到 `joint_5`

### 1.3 电机 ID 索引修正

**文件：** `operating_platform/robot/components/arm_normal_so101_v1/main.py`

**修改位置：** 第 194、202 行

```python
# 修改前（1-based 索引）
goal_pos = {key: position[motor.id - 1] for key, motor in arm_bus.motors.items()}

# 修改后（0-based 索引）
goal_pos = {key: position[motor.id] for key, motor in arm_bus.motors.items()}
```

**说明：** 统一使用 0-based 索引，与电机 ID 定义保持一致。

### 1.4 RADIANS 归一化模式支持

**文件：** `operating_platform/robot/components/arm_normal_so101_v1/motors/motors_bus.py`

**修改位置：** 第 802-806 行（_normalize 函数）

```python
elif self.motors[motor].norm_mode is MotorNormMode.RADIANS:
    mid = (min_ + max_) / 2
    max_res = self.model_resolution_table[self._id_to_model(id_)] - 1
    import math
    radians = (val - mid) * 2 * math.pi / max_res
    normalized_values[id_] = -radians if drive_mode else radians
```

**修改位置：** 第 839-843 行（_unnormalize 函数）

```python
elif self.motors[motor].norm_mode is MotorNormMode.RADIANS:
    val = -val if drive_mode else val
    mid = (min_ + max_) / 2
    max_res = self.model_resolution_table[self._id_to_model(id_)] - 1
    import math
    unnormalized_values[id_] = int((val * max_res / (2 * math.pi)) + mid)
```

**说明：**
- 添加了 RADIANS 模式的位置转换逻辑
- 支持 drive_mode 反转（用于方向校正）
- 同时修改了 DEGREES 模式以支持 drive_mode

---

## 2. 标定文件修改

### 2.1 主臂标定文件

**文件：** `operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json`

**关键变化：**
1. 关节命名从描述性名称改为编号：`joint_0` 到 `joint_5`
2. 电机 ID 改为 0-based：joint_0 的 ID 为 0
3. 更新各关节的标定参数（range_min, range_max, homing_offset）

**示例结构：**
```json
{
    "joint_0": {
        "id": 0,
        "drive_mode": 0,
        "homing_offset": -50,
        "range_min": 1871,
        "range_max": 2222
    },
    "joint_1": {
        "id": 1,
        "drive_mode": 0,
        "homing_offset": 120,
        "range_min": 871,
        "range_max": 3022
    },
    ...
}
```

### 2.2 标定步骤

使用新的标定脚本进行 Feetech 主臂标定：

```bash
python scripts/calib_feetech_leader.py
```

**标定流程：**
1. 连接 Feetech 主臂
2. 运行标定脚本
3. 按照提示移动各关节到极限位置
4. 标定数据自动保存到 `.calibration/SO101-leader.json`

---

## 3. 配置文件修改

### 3.1 数据流配置

**文件：** `operating_platform/robot/robots/so101_v1/dora_teleoperate_dataflow.yml`

**修改位置：** 第 63-76 行

```yaml
- id: arm_so101_leader
  path: ../../components/arm_normal_so101_v1/main.py
  inputs:
    get_joint: dora/timer/millis/33
  outputs:
    - joint
  env:
    GET_DEVICE_FROM: PORT
    PORT: ${ARM_LEADER_PORT:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}
    ARM_NAME: SO101-leader
    ARM_ROLE: leader
    MOTOR_PROTOCOL: feetech  # 显式指定使用 Feetech 协议
    CALIBRATION_DIR: ../../components/arm_normal_so101_v1/.calibration/
```

**关键变化：**
- 添加 `MOTOR_PROTOCOL: feetech` 环境变量
- 更新串口路径（根据实际硬件调整）

### 3.2 机器人配置

**文件：** `operating_platform/robot/robots/configs.py`

**修改位置：** 第 545-560 行

```python
leader_arms: dict[str, MotorsBusConfig] = field(
    default_factory=lambda: {
        "main": FeetechMotorsBusConfig(
            port="/dev/ttyACM0",
            motors={
                # name: (index, model)
                "joint_0": [0, "sts3215"],
                "joint_1": [1, "sts3215"],
                "joint_2": [2, "sts3215"],
                "joint_3": [3, "sts3215"],
                "joint_4": [4, "sts3215"],
                "joint_5": [5, "sts3215"],
                "gripper": [6, "sts3215"],
            },
        ),
    }
)
```

**关键变化：**
- 关节命名标准化为 `joint_0` 到 `joint_5`
- 电机索引改为 0-based
- 电机型号统一为 `sts3215`

---

## 4. 从臂方向校正

### 4.1 Piper 从臂方向反转

**文件：** `operating_platform/robot/components/arm_normal_piper_v2/main.py`

**修改位置：** 第 106-112 行

```python
position = event["value"].to_numpy().copy()

# Invert joints for direction compensation
position[0] = -position[0]  # joint_0
position[1] = -position[1]  # joint_1
position[2] = -position[2]  # joint_2
position[3] = -position[3]  # joint_3
position[5] = -position[5]  # joint_5
```

**说明：**
- 由于机械安装方向差异，需要反转部分关节的运动方向
- joint_0, joint_1, joint_2, joint_3, joint_5 需要反转
- joint_4 和 gripper 不需要反转

---

## 5. 切换步骤总结

### 5.1 硬件准备

1. 将主臂从众灵控制器更换为 Feetech STS3215 舵机
2. 连接主臂到计算机（USB 转串口）
3. 记录串口设备路径（如 `/dev/ttyACM0`）

### 5.2 软件配置

1. **运行标定脚本：**
   ```bash
   python scripts/calib_feetech_leader.py
   ```

2. **更新数据流配置：**
   编辑 `dora_teleoperate_dataflow.yml`，设置：
   ```yaml
   MOTOR_PROTOCOL: feetech
   PORT: /dev/ttyACM0  # 根据实际路径调整
   ```

3. **验证标定文件：**
   检查 `.calibration/SO101-leader.json` 是否正确生成

4. **启动遥操作：**
   ```bash
   bash scripts/run_so101.sh
   ```

### 5.3 测试验证

1. **关节运动测试：**
   - 移动主臂各关节，观察从臂是否同步跟随
   - 检查运动方向是否正确

2. **运动范围测试：**
   - 测试各关节的最大和最小位置
   - 确认不会超出安全范围

3. **夹爪测试：**
   - 测试夹爪开合动作
   - 确认力度控制正常

---

## 6. 协议对比

| 特性 | 众灵（Zhonglin） | Feetech |
|------|-----------------|---------|
| 通信协议 | ASCII | 二进制 |
| 波特率 | 115200 | 1000000（默认） |
| 控制器 | ZP10D | STS3215 舵机 |
| 输出模式 | 弧度 | 可配置（弧度/角度/范围） |
| 电机 ID | 0-based | 0-based |
| 适用场景 | 原始 SO101 主臂 | 新主臂/从臂配置 |

---

## 7. 故障排查

### 7.1 主臂无响应

**可能原因：**
- 串口路径错误
- 波特率不匹配
- 电机未上电

**解决方法：**
```bash
# 检查串口设备
ls -l /dev/ttyACM*

# 测试串口通信
python -c "import serial; s=serial.Serial('/dev/ttyACM0', 1000000); print('OK')"
```

### 7.2 运动方向错误

**可能原因：**
- 标定文件中的 drive_mode 设置不正确
- Piper 从臂的方向反转逻辑缺失

**解决方法：**
1. 检查 `SO101-leader.json` 中的 `drive_mode` 值
2. 检查 `arm_normal_piper_v2/main.py` 中的方向反转代码

### 7.3 关节抖动

**可能原因：**
- 传感器噪声
- PID 参数不合适

**解决方法：**
- 已在 v0.2.141 中通过低通滤波器和死区控制解决
- 参考 `docs/RELEASE.md` 中的 v0.2.141 说明

---

## 8. 相关文件清单

### 8.1 修改的文件

- `operating_platform/robot/components/arm_normal_so101_v1/main.py`
- `operating_platform/robot/components/arm_normal_so101_v1/motors/motors_bus.py`
- `operating_platform/robot/components/arm_normal_piper_v2/main.py`
- `operating_platform/robot/components/arm_normal_so101_v1/.calibration/SO101-leader.json`
- `operating_platform/robot/robots/configs.py`
- `operating_platform/robot/robots/so101_v1/dora_teleoperate_dataflow.yml`

### 8.2 新增的文件

- `scripts/calib_feetech_leader.py` - Feetech 主臂标定脚本
- `README-sun.md` - 标定说明文档
- `docs/Leader_arm_switch.md` - 本文档

### 8.3 删除的文件

- `scripts/find_can_pot.sh` - 已废弃的 CAN 端口检测脚本

---

## 9. 版本信息

**版本：** v0.2.142
**日期：** 2026-01-22
**作者：** DoRobot Team
**相关版本：** v0.2.141（抖动问题修复）

---

## 10. 参考资料

- [Feetech STS3215 舵机手册](https://www.feetechrc.com/)
- [DoRobot 发布说明](./RELEASE.md)
- [SO101 机械臂文档](../README.md)
