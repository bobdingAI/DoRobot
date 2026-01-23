#!/bin/bash
# Monitor CAN traffic on both buses to see which one is receiving commands

echo "开始监控 CAN 流量..."
echo "按 Ctrl+C 停止"
echo ""

# 记录初始统计
echo "=== 初始状态 ==="
echo "can_left TX:"
ip -s link show can_left | grep "TX:" -A1 | tail -1
echo "can_right TX:"
ip -s link show can_right | grep "TX:" -A1 | tail -1
echo ""

sleep 5

echo "=== 5秒后状态 ==="
echo "can_left TX:"
ip -s link show can_left | grep "TX:" -A1 | tail -1
echo "can_right TX:"
ip -s link show can_right | grep "TX:" -A1 | tail -1
echo ""

echo "如果 TX packets 数量增加，说明该接口正在发送命令"
