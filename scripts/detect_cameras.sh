#!/bin/bash

OUTPUT_FILE="camera_detail.txt"
CONFIG_FILE="$HOME/.dorobot_device.conf"

# 清空文件
> "$OUTPUT_FILE"
> "$CONFIG_FILE"

echo "========================================" | tee -a "$OUTPUT_FILE"
echo "摄像头视频节点检测报告" | tee -a "$OUTPUT_FILE"
echo "检测时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$OUTPUT_FILE"
echo "========================================" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

# 存储设备信息
declare -A realsense_devices
declare -A orbbec_devices

# 检测所有视频设备
for dev in /dev/video*; do
    [ -c "$dev" ] || continue

    DEV_NUM=$(echo "$dev" | grep -o '[0-9]\+$')
    CARD_TYPE=$(v4l2-ctl -d "$dev" --all 2>&1 | grep "Card type" | sed 's/.*: //')

    # 获取格式信息
    if v4l2-ctl -d "$dev" --all 2>&1 | grep -q "Format Video Capture"; then
        PIXEL_FORMAT=$(v4l2-ctl -d "$dev" --all 2>&1 | grep "Pixel Format" | sed 's/.*: //' | tr -d '\n')
        RESOLUTION=$(v4l2-ctl -d "$dev" --all 2>&1 | grep "Width/Height" | sed 's/.*: //' | tr '/' 'x')

        # 判断数据流类型
        if echo "$PIXEL_FORMAT" | grep -q "Z16"; then
            STREAM_TYPE="深度流"
            DESC="深度数据，每个像素16位表示距离"
        elif echo "$PIXEL_FORMAT" | grep -q "GREY"; then
            STREAM_TYPE="红外流"
            DESC="灰度红外图像"
        elif echo "$PIXEL_FORMAT" | grep -q "YUYV"; then
            STREAM_TYPE="YUV 彩色流"
            DESC="标准 YUV 彩色图像（推荐使用）"
        elif echo "$PIXEL_FORMAT" | grep -q "BA81"; then
            STREAM_TYPE="Bayer 彩色"
            DESC="原始 Bayer 格式彩色数据"
        elif echo "$PIXEL_FORMAT" | grep -q "Y8"; then
            STREAM_TYPE="红外流"
            DESC="8位灰度红外图像"
        else
            STREAM_TYPE="其他"
            DESC="其他格式数据流"
        fi

        INFO="$dev|$STREAM_TYPE|$PIXEL_FORMAT|$RESOLUTION|$DESC"
    elif v4l2-ctl -d "$dev" --all 2>&1 | grep -q "Metadata Capture"; then
        PREV_DEV=$((DEV_NUM - 1))
        INFO="$dev|元数据|UVCH (Metadata)|-|video$PREV_DEV 的元数据（时间戳等）"
    else
        continue
    fi

    # 分类存储
    if echo "$CARD_TYPE" | grep -qi "realsense"; then
        realsense_devices[$DEV_NUM]="$INFO"
        # 保存彩色流配置
        if echo "$INFO" | grep -q "YUV 彩色流"; then
            echo "CAMERA_WRIST_PATH=/dev/video4" >> "$CONFIG_FILE"
            echo "REALSENSE_COLOR_DEVICE=/dev/video4" >> "$CONFIG_FILE"
        fi
    elif echo "$CARD_TYPE" | grep -qi "orbbec\|gemini"; then
        orbbec_devices[$DEV_NUM]="$INFO"
        # 保存彩色流配置
        if echo "$INFO" | grep -q "YUV 彩色流"; then
            echo "CAMERA_TOP_PATH=/dev/video12" >> "$CONFIG_FILE"
        fi
    fi
done

# 输出 RealSense 表格
if [ ${#realsense_devices[@]} -gt 0 ]; then
    {
        echo "## Intel RealSense 深度相机"
        echo ""
        echo "| 设备节点        | 数据流类型   | 格式                          | 分辨率    | 说明                                 |"
        echo "|-----------------|--------------|-------------------------------|-----------|--------------------------------------|"

        for key in $(echo "${!realsense_devices[@]}" | tr ' ' '\n' | sort -n); do
            IFS='|' read -r dev stream_type format resolution desc <<< "${realsense_devices[$key]}"
            printf "| %-15s | %-12s | %-29s | %-9s | %-36s |\n" "$dev" "$stream_type" "$format" "$resolution" "$desc"
        done
        echo ""
    } | tee -a "$OUTPUT_FILE"
fi

# 输出 Orbbec 表格
if [ ${#orbbec_devices[@]} -gt 0 ]; then
    {
        echo "## Orbbec Gemini 335 深度相机"
        echo ""
        echo "| 设备节点        | 数据流类型   | 格式                          | 分辨率    | 说明                                 |"
        echo "|-----------------|--------------|-------------------------------|-----------|--------------------------------------|"

        for key in $(echo "${!orbbec_devices[@]}" | tr ' ' '\n' | sort -n); do
            IFS='|' read -r dev stream_type format resolution desc <<< "${orbbec_devices[$key]}"
            printf "| %-15s | %-12s | %-29s | %-9s | %-36s |\n" "$dev" "$stream_type" "$format" "$resolution" "$desc"
        done
        echo ""
    } | tee -a "$OUTPUT_FILE"
fi

echo "========================================" | tee -a "$OUTPUT_FILE"
echo "配置文件已保存到: $CONFIG_FILE" | tee -a "$OUTPUT_FILE"
echo "详细信息已保存到: $OUTPUT_FILE" | tee -a "$OUTPUT_FILE"
