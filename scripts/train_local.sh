#!/bin/bash

# DoRobot 本地训练脚本
# 使用方法: bash scripts/train_local.sh [数据集路径]

set -e  # 遇到错误立即退出

# ==================== 配置参数 ====================

# 数据集路径（可通过命令行参数传入）
DATASET_PATH=${1:-"/home/demo/Public/DoRobot/dataset/so101-test"}

# 训练参数
POLICY_TYPE="act"                    # 策略类型: act, diffusion, tdmpc, vqbet
STEPS=500                            # 总训练步数
BATCH_SIZE=16                        # 批次大小
SAVE_FREQ=250                        # 每N步保存checkpoint
EVAL_FREQ=250                        # 每N步评估一次
LOG_FREQ=200                         # 每N步记录日志
NUM_WORKERS=4                        # 数据加载线程数
LEARNING_RATE=0.001                  # 学习率

# 输出目录（固定路径）
OUTPUT_DIR="/home/demo/Public/DoRobot/dataset/model"

# 设备配置
DEVICE="cuda"                        # cuda, cpu, npu

# WandB配置（可选）
USE_WANDB=false                      # 是否使用WandB记录
WANDB_PROJECT="dorobot-training"
WANDB_ENTITY=""                      # 留空使用默认

# ==================== 环境检查 ====================

echo "=========================================="
echo "DoRobot 本地训练脚本"
echo "=========================================="
echo ""

# 检查conda环境
if [[ -z "${CONDA_DEFAULT_ENV}" ]]; then
    echo "❌ 错误: 未激活conda环境"
    echo "请先运行: conda activate dorobot"
    exit 1
fi

echo "✅ Conda环境: ${CONDA_DEFAULT_ENV}"

# 检查数据集路径
if [[ ! -d "${DATASET_PATH}" ]]; then
    echo "❌ 错误: 数据集路径不存在: ${DATASET_PATH}"
    echo "使用方法: bash scripts/train_local.sh <数据集路径>"
    exit 1
fi

echo "✅ 数据集路径: ${DATASET_PATH}"

# 检查GPU（如果使用CUDA）
if [[ "${DEVICE}" == "cuda" ]]; then
    if command -v nvidia-smi &> /dev/null; then
        echo "✅ GPU状态:"
        nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader
    else
        echo "⚠️  警告: 未检测到NVIDIA GPU，将使用CPU训练"
        DEVICE="cpu"
    fi
fi

echo ""
echo "=========================================="
echo "训练配置"
echo "=========================================="
echo "策略类型:     ${POLICY_TYPE}"
echo "训练步数:     ${STEPS}"
echo "批次大小:     ${BATCH_SIZE}"
echo "保存频率:     每 ${SAVE_FREQ} 步"
echo "评估频率:     每 ${EVAL_FREQ} 步"
echo "学习率:       ${LEARNING_RATE}"
echo "设备:         ${DEVICE}"
echo "输出目录:     ${OUTPUT_DIR}"
echo "=========================================="
echo ""

# 等待用户确认
read -p "按Enter键开始训练，或Ctrl+C取消... " -r
echo ""

# ==================== 开始训练 ====================

echo "🚀 开始训练..."
echo ""

# 构建训练命令
TRAIN_CMD="python operating_platform/core/train.py \
    --dataset.repo_id=${DATASET_PATH} \
    --policy.type=${POLICY_TYPE} \
    --policy.device=${DEVICE} \
    --steps=${STEPS} \
    --batch_size=${BATCH_SIZE} \
    --save_freq=${SAVE_FREQ} \
    --eval_freq=${EVAL_FREQ} \
    --log_freq=${LOG_FREQ} \
    --num_workers=${NUM_WORKERS} \
    --output_dir=${OUTPUT_DIR}"

# 添加优化器配置
if [[ -n "${LEARNING_RATE}" ]]; then
    TRAIN_CMD="${TRAIN_CMD} \
    --optimizer.lr=${LEARNING_RATE}"
fi

# 添加WandB配置
if [[ "${USE_WANDB}" == "true" ]]; then
    TRAIN_CMD="${TRAIN_CMD} \
    --wandb.enable=true \
    --wandb.project=${WANDB_PROJECT}"

    if [[ -n "${WANDB_ENTITY}" ]]; then
        TRAIN_CMD="${TRAIN_CMD} \
    --wandb.entity=${WANDB_ENTITY}"
    fi
else
    TRAIN_CMD="${TRAIN_CMD} \
    --wandb.enable=false"
fi

# 执行训练
echo "执行命令:"
echo "${TRAIN_CMD}"
echo ""

eval ${TRAIN_CMD}

# ==================== 训练完成 ====================

if [[ $? -eq 0 ]]; then
    echo ""
    echo "=========================================="
    echo "✅ 训练完成！"
    echo "=========================================="
    echo "模型保存位置: ${OUTPUT_DIR}"
    echo ""
    echo "Checkpoint位置:"
    find ${OUTPUT_DIR} -name "pretrained_model" -type d 2>/dev/null || echo "  未找到checkpoint"
    echo ""
    echo "使用模型进行推理:"
    echo "  python operating_platform/core/eval.py --policy.path=${OUTPUT_DIR}/checkpoints/last/pretrained_model"
    echo "=========================================="
else
    echo ""
    echo "=========================================="
    echo "❌ 训练失败"
    echo "=========================================="
    exit 1
fi
