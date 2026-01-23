#!/usr/bin/env python3
"""
DoRobot 简易训练脚本
使用方法: python scripts/train_simple.py --dataset <数据集路径>
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def check_environment():
    """检查训练环境"""
    print("=" * 50)
    print("环境检查")
    print("=" * 50)

    # 检查conda环境
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    if not conda_env:
        print("❌ 错误: 未激活conda环境")
        print("请先运行: conda activate dorobot")
        sys.exit(1)
    print(f"✅ Conda环境: {conda_env}")

    # 检查GPU
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print(f"✅ GPU: {result.stdout.strip()}")
            return "cuda"
        else:
            print("⚠️  未检测到GPU，将使用CPU训练")
            return "cpu"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("⚠️  未检测到GPU，将使用CPU训练")
        return "cpu"


def main():
    parser = argparse.ArgumentParser(description="DoRobot 本地训练脚本")

    # 必需参数
    parser.add_argument("--dataset", required=True, help="数据集路径")

    # 训练参数
    parser.add_argument("--policy", default="act", choices=["act", "diffusion", "tdmpc", "vqbet"],
                        help="策略类型 (默认: act)")
    parser.add_argument("--steps", type=int, default=10000,
                        help="训练步数 (默认: 10000)")
    parser.add_argument("--batch-size", type=int, default=16,
                        help="批次大小 (默认: 16)")
    parser.add_argument("--save-freq", type=int, default=5000,
                        help="保存频率 (默认: 5000)")
    parser.add_argument("--eval-freq", type=int, default=5000,
                        help="评估频率 (默认: 5000)")
    parser.add_argument("--log-freq", type=int, default=200,
                        help="日志频率 (默认: 200)")
    parser.add_argument("--lr", type=float, default=0.001,
                        help="学习率 (默认: 0.001)")
    parser.add_argument("--num-workers", type=int, default=4,
                        help="数据加载线程数 (默认: 4)")

    # 输出配置
    parser.add_argument("--output-dir", default=None,
                        help="输出目录 (默认: 自动生成)")
    parser.add_argument("--device", default=None, choices=["cuda", "cpu", "npu"],
                        help="设备 (默认: 自动检测)")

    # WandB配置
    parser.add_argument("--wandb", action="store_true",
                        help="启用WandB日志")
    parser.add_argument("--wandb-project", default="dorobot-training",
                        help="WandB项目名称")
    parser.add_argument("--wandb-entity", default="",
                        help="WandB实体名称")

    args = parser.parse_args()

    # 检查环境
    device = args.device if args.device else check_environment()

    # 检查数据集
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"❌ 错误: 数据集路径不存在: {dataset_path}")
        sys.exit(1)
    print(f"✅ 数据集: {dataset_path}")
    print()

    # 生成输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = Path(f"outputs/train/{args.policy}_{timestamp}")

    # 显示配置
    print("=" * 50)
    print("训练配置")
    print("=" * 50)
    print(f"策略类型:     {args.policy}")
    print(f"训练步数:     {args.steps:,}")
    print(f"批次大小:     {args.batch_size}")
    print(f"保存频率:     每 {args.save_freq:,} 步")
    print(f"评估频率:     每 {args.eval_freq:,} 步")
    print(f"学习率:       {args.lr}")
    print(f"设备:         {device}")
    print(f"输出目录:     {output_dir}")
    print(f"WandB:        {'启用' if args.wandb else '禁用'}")
    print("=" * 50)
    print()

    # 构建训练命令
    cmd = [
        "python", "operating_platform/core/train.py",
        f"--dataset.repo_id={dataset_path}",
        f"--policy.type={args.policy}",
        f"--policy.device={device}",
        f"--steps={args.steps}",
        f"--batch_size={args.batch_size}",
        f"--save_freq={args.save_freq}",
        f"--eval_freq={args.eval_freq}",
        f"--log_freq={args.log_freq}",
        f"--num_workers={args.num_workers}",
        f"--output_dir={output_dir}",
        f"--optimizer.lr={args.lr}",
    ]

    # WandB配置
    if args.wandb:
        cmd.extend([
            "--wandb.enable=true",
            f"--wandb.project={args.wandb_project}",
        ])
        if args.wandb_entity:
            cmd.append(f"--wandb.entity={args.wandb_entity}")
    else:
        cmd.append("--wandb.enable=false")

    # 显示命令
    print("🚀 执行训练命令:")
    print(" ".join(cmd))
    print()

    # 执行训练
    try:
        result = subprocess.run(cmd)

        if result.returncode == 0:
            print()
            print("=" * 50)
            print("✅ 训练完成！")
            print("=" * 50)
            print(f"模型保存位置: {output_dir}")
            print()

            # 查找checkpoint
            checkpoint_dirs = list(output_dir.glob("**/pretrained_model"))
            if checkpoint_dirs:
                print("Checkpoint位置:")
                for ckpt in checkpoint_dirs:
                    print(f"  {ckpt}")
                print()
                print("使用模型进行推理:")
                print(f"  python operating_platform/core/eval.py --policy.path={checkpoint_dirs[-1]}")
            print("=" * 50)
        else:
            print()
            print("=" * 50)
            print("❌ 训练失败")
            print("=" * 50)
            sys.exit(1)

    except KeyboardInterrupt:
        print()
        print("⚠️  训练被用户中断")
        sys.exit(1)


if __name__ == "__main__":
    main()
