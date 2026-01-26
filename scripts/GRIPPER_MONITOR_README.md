# 夹爪状态监控脚本使用说明

## 脚本功能

`monitor_gripper_correlation.py` 是一个用于监控主臂和从臂夹爪状态相关性的诊断工具，专门用于调试夹爪在运动范围过半时松开的问题。

## 主要特性

1. **实时监控**：以 20Hz 的频率采样主臂和从臂夹爪的状态
2. **多维度数据**：
   - PWM 原始值
   - 归一化值 (0-100%)
   - 在标定范围内的百分比位置
   - PWM 差异和归一化差异
   - 速度和负载信息

3. **异常检测**：
   - 检测夹爪运动范围过半的时刻
   - 检测突然松开事件（归一化值突然减小）
   - 检测主从臂之间的大偏差
   - 检测 PWM 溢出风险

4. **数据记录**：自动保存 CSV 格式的日志文件，便于后续分析

## 使用方法

### 基本用法

```bash
cd /home/demo/Public/DoRobot
python scripts/monitor_gripper_correlation.py
```

### 指定串口

```bash
python scripts/monitor_gripper_correlation.py \
    --leader-port /dev/ttyACM0 \
    --follower-port /dev/ttyUSB0
```

### 指定日志文件

```bash
python scripts/monitor_gripper_correlation.py \
    --log gripper_debug_20260126.csv
```

## 输出说明

### 控制台输出

实时显示以下信息：

```
时间戳    | 主臂PWM | 主臂% | 主臂范围% | 从臂目标 | 从臂实际 | 从臂% | 从臂范围% | PWM差 | 归一化差 | 事件
```

- **时间戳**：当前时间（精确到毫秒）
- **主臂PWM**：主臂夹爪的原始 PWM 值
- **主臂%**：主臂夹爪的归一化值（0-100%）
- **主臂范围%**：主臂在标定范围内的位置百分比
- **从臂目标**：根据主臂计算出的从臂目标 PWM 值
- **从臂实际**：从臂夹爪的实际 PWM 值
- **从臂%**：从臂夹爪的归一化值（0-100%）
- **从臂范围%**：从臂在标定范围内的位置百分比
- **PWM差**：从臂实际值与目标值的差异
- **归一化差**：主从臂归一化值的差异
- **事件**：检测到的异常事件

### 事件类型

- `[主臂过半]`：主臂夹爪运动范围超过 50%
- `[从臂过半]`：从臂夹爪运动范围超过 50%
- `[从臂突然松开 -XX.X%]`：从臂归一化值突然减小
- `[主臂突然松开 -XX.X%]`：主臂归一化值突然减小
- `[大偏差 XXX]`：主从臂 PWM 差异超过 100
- `[溢出风险 目标=XXXX]`：目标 PWM 值超过 4095

### CSV 日志文件

日志文件包含以下列：

1. `timestamp`：Unix 时间戳
2. `leader_pwm`：主臂 PWM 值
3. `leader_norm`：主臂归一化值
4. `leader_range_pct`：主臂范围百分比
5. `follower_target_pwm`：从臂目标 PWM
6. `follower_actual_pwm`：从臂实际 PWM
7. `follower_norm`：从臂归一化值
8. `follower_range_pct`：从臂范围百分比
9. `pwm_diff`：PWM 差异
10. `norm_diff`：归一化差异
11. `leader_velocity`：主臂速度
12. `follower_velocity`：从臂速度
13. `leader_load`：主臂负载
14. `follower_load`：从臂负载
15. `event`：事件描述

## 调试步骤

1. **启动监控脚本**：
   ```bash
   python scripts/monitor_gripper_correlation.py
   ```

2. **操作夹爪**：
   - 缓慢地闭合主臂夹爪
   - 观察控制台输出，特别关注"过半"和"突然松开"事件
   - 注意从臂夹爪是否在某个特定位置松开

3. **分析日志**：
   - 使用 Excel、Python pandas 或其他工具打开 CSV 文件
   - 绘制主臂和从臂归一化值的时间序列图
   - 查找异常点和模式

4. **常见问题排查**：
   - **溢出问题**：如果看到 `[溢出风险]` 事件，说明从臂目标 PWM 超过 4095，需要调整标定参数
   - **映射问题**：如果主从臂归一化值差异很大，检查标定文件中的 `range_min` 和 `range_max`
   - **硬件问题**：如果从臂在特定位置总是松开，可能是机械限位或舵机问题

## 数据分析示例

使用 Python 分析日志：

```python
import pandas as pd
import matplotlib.pyplot as plt

# 读取日志
df = pd.read_csv('gripper_monitor_20260126_123456.csv')

# 绘制主从臂归一化值对比
plt.figure(figsize=(12, 6))
plt.plot(df['timestamp'], df['leader_norm'], label='Leader', alpha=0.7)
plt.plot(df['timestamp'], df['follower_norm'], label='Follower', alpha=0.7)
plt.xlabel('Time')
plt.ylabel('Normalized Value (%)')
plt.title('Leader vs Follower Gripper Position')
plt.legend()
plt.grid(True)
plt.show()

# 查找突然松开的时刻
anomalies = df[df['event'].str.contains('突然松开', na=False)]
print("检测到的异常事件：")
print(anomalies[['timestamp', 'leader_norm', 'follower_norm', 'event']])
```

## 注意事项

1. 确保主臂和从臂都已正确连接
2. 确保标定文件存在且正确
3. 监控过程中不要断开串口连接
4. 按 Ctrl+C 可以安全退出监控

## 故障排除

### 串口连接失败

```bash
# 检查串口设备
ls -l /dev/ttyACM* /dev/ttyUSB*

# 添加用户到 dialout 组
sudo usermod -aG dialout $USER
# 重新登录后生效
```

### 标定文件未找到

确保标定文件存在：
```bash
ls -l operating_platform/robot/components/arm_normal_so101_v1/.calibration/
```

### 权限问题

```bash
chmod +x scripts/monitor_gripper_correlation.py
```
