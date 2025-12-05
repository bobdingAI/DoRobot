#!/usr/bin/env python3
"""
USB Device Port Detection Utility

Detects USB video and serial devices and shows their persistent paths.
Use persistent paths in YAML config to ensure ports don't change between
episodes or when cables are reconnected.

Usage:
    python scripts/detect_usb_ports.py           # Show all devices
    python scripts/detect_usb_ports.py --yaml    # Output YAML snippet
    python scripts/detect_usb_ports.py --save    # Save config to ~/.dorobot_device.conf
    python scripts/detect_usb_ports.py --watch   # Monitor device changes
"""

import argparse
import glob
import os
import subprocess
import sys
import time
from pathlib import Path


def get_device_info(device_path: str) -> dict:
    """Get information about a device using udevadm."""
    info = {"path": device_path, "by_path": None, "by_id": None, "model": None}

    try:
        result = subprocess.run(
            ["udevadm", "info", "--query=all", "--name=" + device_path],
            capture_output=True,
            text=True,
            timeout=5,
        )

        for line in result.stdout.splitlines():
            if "ID_PATH=" in line:
                info["by_path"] = line.split("=", 1)[1].strip()
            elif "ID_MODEL=" in line:
                info["model"] = line.split("=", 1)[1].strip()
            elif "ID_SERIAL=" in line:
                info["by_id"] = line.split("=", 1)[1].strip()

    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return info


def is_video_capture_device(dev_path: str) -> bool:
    """Check if device is a video capture device using v4l2-ctl or ioctl."""
    # Method 1: Try v4l2-ctl (most reliable)
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--device=" + dev_path, "--all"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Check if it's a capture device (has video capture capability)
        if "Video Capture" in result.stdout:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Method 2: Check udevadm for ID_V4L_CAPABILITIES
    try:
        result = subprocess.run(
            ["udevadm", "info", "--query=all", "--name=" + dev_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Look for capture capability
        if "ID_V4L_CAPABILITIES=:capture:" in result.stdout:
            return True
        # Also check if it's a video4linux device at all
        if "ID_V4L_VERSION" in result.stdout:
            # Assume it's a capture device if no specific capability info
            # but skip if it looks like a metadata device
            dev_num = dev_path.replace("/dev/video", "")
            if dev_num.isdigit():
                # On many systems, even numbered devices are capture, odd are metadata
                # But this isn't always true, so we include all if we can't determine
                return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Method 3: Fallback - just check if device exists and is accessible
    try:
        if os.path.exists(dev_path) and os.access(dev_path, os.R_OK):
            return True
    except Exception:
        pass

    return False


def find_video_devices() -> list:
    """Find all video capture devices."""
    devices = []

    # Check /dev/video* devices
    for dev in sorted(glob.glob("/dev/video*")):
        try:
            # Use v4l2/udevadm to check if it's a capture device (doesn't require OpenCV)
            if not is_video_capture_device(dev):
                continue

            info = get_device_info(dev)
            info["type"] = "video"

            # Find corresponding by-path symlink
            by_path_dir = Path("/dev/v4l/by-path")
            if by_path_dir.exists():
                for link in by_path_dir.iterdir():
                    if link.resolve() == Path(dev).resolve():
                        info["by_path_link"] = str(link)
                        break

            devices.append(info)
        except Exception:
            pass

    return devices


def find_serial_devices() -> list:
    """Find all serial devices (for robot arms)."""
    devices = []

    # Check /dev/ttyACM* and /dev/ttyUSB* devices
    for pattern in ["/dev/ttyACM*", "/dev/ttyUSB*"]:
        for dev in sorted(glob.glob(pattern)):
            info = get_device_info(dev)
            info["type"] = "serial"

            # Find corresponding by-path symlink
            by_path_dir = Path("/dev/serial/by-path")
            if by_path_dir.exists():
                for link in by_path_dir.iterdir():
                    if link.resolve() == Path(dev).resolve():
                        info["by_path_link"] = str(link)
                        break

            # Find by-id symlink (more descriptive)
            by_id_dir = Path("/dev/serial/by-id")
            if by_id_dir.exists():
                for link in by_id_dir.iterdir():
                    if link.resolve() == Path(dev).resolve():
                        info["by_id_link"] = str(link)
                        break

            devices.append(info)

    return devices


def print_devices(video_devices: list, serial_devices: list):
    """Print device information in human-readable format."""
    print("\n" + "=" * 70)
    print("USB Device Detection - Persistent Port Configuration")
    print("=" * 70)

    print("\n--- VIDEO DEVICES (Cameras) ---")
    if not video_devices:
        print("  No video devices found")
    else:
        for dev in video_devices:
            print(f"\n  Device: {dev['path']}")
            if dev.get("model"):
                print(f"    Model: {dev['model']}")
            if dev.get("by_path_link"):
                print(f"    Persistent path: {dev['by_path_link']}")
                print(f"    (Use this path in YAML for stable configuration)")
            elif dev.get("by_path"):
                print(f"    USB path ID: {dev['by_path']}")

    print("\n--- SERIAL DEVICES (Robot Arms) ---")
    if not serial_devices:
        print("  No serial devices found")
    else:
        for dev in serial_devices:
            print(f"\n  Device: {dev['path']}")
            if dev.get("model"):
                print(f"    Model: {dev['model']}")
            if dev.get("by_path_link"):
                print(f"    Persistent path: {dev['by_path_link']}")
                print(f"    (Use this path in YAML for stable configuration)")
            if dev.get("by_id_link"):
                print(f"    By-ID path: {dev['by_id_link']}")

    print("\n" + "=" * 70)
    print("TIP: Use persistent paths (by-path) in your YAML config.")
    print("     These paths are based on USB port location, not enumeration order.")
    print("=" * 70 + "\n")


def print_yaml_snippet(video_devices: list, serial_devices: list):
    """Print YAML configuration snippet."""
    print("\n# === YAML Configuration Snippet ===")
    print("# Copy these paths to your dora_teleoperate_dataflow.yml")
    print("#")
    print("# Paths are based on USB topology and will remain stable")
    print("# even when devices are reconnected or system reboots.")
    print()

    camera_idx = 0
    camera_names = ["camera_top", "camera_wrist", "camera_wrist2"]

    for dev in video_devices:
        name = camera_names[camera_idx] if camera_idx < len(camera_names) else f"camera_{camera_idx}"
        path = dev.get("by_path_link") or dev["path"]

        print(f"  - id: {name}")
        print(f"    path: ../../components/camera_opencv/main.py")
        print(f"    inputs:")
        print(f"      tick: dora/timer/millis/33")
        print(f"    outputs:")
        print(f"      - image")
        print(f"    env:")
        print(f"      CAPTURE_PATH: \"{path}\"  # {dev['path']}" + (f" - {dev.get('model', 'Camera')}" if dev.get('model') else ""))
        print(f"      IMAGE_WIDTH: 640")
        print(f"      IMAGE_HEIGHT: 480")
        print()
        camera_idx += 1

    arm_configs = [
        ("arm_so101_leader", "leader", "SO101-leader"),
        ("arm_so101_follower", "follower", "SO101-follower"),
    ]

    for idx, dev in enumerate(serial_devices):
        if idx >= len(arm_configs):
            break
        node_id, role, name = arm_configs[idx]
        path = dev.get("by_path_link") or dev.get("by_id_link") or dev["path"]

        print(f"  - id: {node_id}")
        print(f"    path: ../../components/arm_normal_so101_v1/main.py")
        print(f"    inputs:")
        print(f"      get_joint: dora/timer/millis/33")
        if role == "follower":
            print(f"      action_joint: arm_so101_leader/joint")
            print(f"      action_joint_ctrl: so101_zeromq/action_joint")
        print(f"    outputs:")
        print(f"      - joint")
        print(f"    env:")
        print(f"      GET_DEVICE_FROM: PORT")
        print(f"      PORT: \"{path}\"  # {dev['path']}" + (f" - {dev.get('model', 'Arm')}" if dev.get('model') else ""))
        print(f"      ARM_NAME: {name}")
        print(f"      ARM_ROLE: {role}")
        print(f"      CALIBRATION_DIR: ../../components/arm_normal_so101_v1/.calibration/")
        print()


def save_device_config(video_devices: list, serial_devices: list, output_path: str = None):
    """
    Save device configuration to a shell config file.

    This creates a file that can be sourced by run_so101.sh to set
    persistent device paths automatically.
    """
    if output_path is None:
        output_path = os.path.expanduser("~/.dorobot_device.conf")

    # Build config content
    lines = [
        "# DoRobot Device Configuration",
        "# Generated by: python scripts/detect_usb_ports.py --save",
        f"# Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "#",
        "# This file is automatically sourced by run_so101.sh",
        "# Regenerate with: python scripts/detect_usb_ports.py --save",
        "",
        "# === Camera Configuration ===",
    ]

    camera_vars = ["CAMERA_TOP_PATH", "CAMERA_WRIST_PATH", "CAMERA_WRIST2_PATH"]
    for idx, dev in enumerate(video_devices):
        if idx >= len(camera_vars):
            break
        var_name = camera_vars[idx]
        path = dev.get("by_path_link") or dev["path"]
        model = dev.get("model", "Camera")
        lines.append(f"# {dev['path']} - {model}")
        lines.append(f'{var_name}="{path}"')
        lines.append("")

    # Fill remaining camera vars with comments
    for idx in range(len(video_devices), len(camera_vars)):
        var_name = camera_vars[idx]
        lines.append(f"# {var_name} - No device detected")
        lines.append(f"# {var_name}=\"\"")
        lines.append("")

    lines.append("# === Arm Configuration ===")

    arm_vars = [
        ("ARM_LEADER_PORT", "Leader arm"),
        ("ARM_FOLLOWER_PORT", "Follower arm"),
        ("ARM_LEADER2_PORT", "Leader arm 2"),
        ("ARM_FOLLOWER2_PORT", "Follower arm 2"),
    ]

    for idx, dev in enumerate(serial_devices):
        if idx >= len(arm_vars):
            break
        var_name, description = arm_vars[idx]
        path = dev.get("by_path_link") or dev.get("by_id_link") or dev["path"]
        model = dev.get("model", "Serial device")
        lines.append(f"# {dev['path']} - {model} ({description})")
        lines.append(f'{var_name}="{path}"')
        lines.append("")

    # Fill remaining arm vars with comments
    for idx in range(len(serial_devices), len(arm_vars)):
        var_name, description = arm_vars[idx]
        lines.append(f"# {var_name} - No device detected ({description})")
        lines.append(f"# {var_name}=\"\"")
        lines.append("")

    # Write file
    content = "\n".join(lines)

    with open(output_path, "w") as f:
        f.write(content)

    print(f"\n{'=' * 70}")
    print("Device configuration saved!")
    print(f"{'=' * 70}")
    print(f"\nConfig file: {output_path}")
    print("\nContents:")
    print("-" * 40)
    print(content)
    print("-" * 40)
    print(f"\nThis file will be automatically loaded by run_so101.sh")
    print(f"To regenerate: python scripts/detect_usb_ports.py --save")
    print(f"{'=' * 70}\n")

    return output_path


def watch_devices():
    """Monitor device changes in real-time."""
    print("\nWatching for USB device changes... (Ctrl+C to stop)\n")

    last_video = []
    last_serial = []

    while True:
        video = find_video_devices()
        serial = find_serial_devices()

        video_paths = {d["path"] for d in video}
        serial_paths = {d["path"] for d in serial}
        last_video_paths = {d["path"] for d in last_video}
        last_serial_paths = {d["path"] for d in last_serial}

        # Check for changes
        added_video = video_paths - last_video_paths
        removed_video = last_video_paths - video_paths
        added_serial = serial_paths - last_serial_paths
        removed_serial = last_serial_paths - serial_paths

        timestamp = time.strftime("%H:%M:%S")

        for path in added_video:
            dev = next((d for d in video if d["path"] == path), None)
            if dev:
                persistent = dev.get("by_path_link") or "N/A"
                print(f"[{timestamp}] + VIDEO ADDED: {path} -> {persistent}")

        for path in removed_video:
            print(f"[{timestamp}] - VIDEO REMOVED: {path}")

        for path in added_serial:
            dev = next((d for d in serial if d["path"] == path), None)
            if dev:
                persistent = dev.get("by_path_link") or dev.get("by_id_link") or "N/A"
                print(f"[{timestamp}] + SERIAL ADDED: {path} -> {persistent}")

        for path in removed_serial:
            print(f"[{timestamp}] - SERIAL REMOVED: {path}")

        last_video = video
        last_serial = serial

        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(
        description="Detect USB devices and show persistent port paths",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python detect_usb_ports.py           # Show all devices
  python detect_usb_ports.py --yaml    # Output YAML config snippet
  python detect_usb_ports.py --save    # Save config to ~/.dorobot_device.conf
  python detect_usb_ports.py --watch   # Monitor device changes

Use persistent paths in your config to ensure devices stay at the
same paths even when:
  - Starting new recording episodes
  - Reconnecting USB cables
  - Rebooting the system

Workflow for stable ports:
  1. Connect all devices (cameras, arms) in desired order
  2. Run: python scripts/detect_usb_ports.py --save
  3. Config saved to ~/.dorobot_device.conf
  4. run_so101.sh will automatically use these paths
        """,
    )
    parser.add_argument(
        "--yaml",
        action="store_true",
        help="Output YAML configuration snippet",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save device config to ~/.dorobot_device.conf (auto-loaded by run_so101.sh)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output path for --save (default: ~/.dorobot_device.conf)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Monitor device changes in real-time",
    )

    args = parser.parse_args()

    if sys.platform != "linux":
        print("Warning: This script is designed for Linux.")
        print("On macOS, device paths are typically stable, but there's no")
        print("equivalent to /dev/v4l/by-path or /dev/serial/by-path.")
        print()

    if args.watch:
        watch_devices()
    else:
        video = find_video_devices()
        serial = find_serial_devices()

        if args.save:
            save_device_config(video, serial, args.output)
        elif args.yaml:
            print_yaml_snippet(video, serial)
        else:
            print_devices(video, serial)


if __name__ == "__main__":
    main()
