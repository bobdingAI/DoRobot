#!/usr/bin/env python3
"""
USB Device Port Detection Utility

Detects USB video and serial devices and shows their persistent paths.
Use persistent paths in YAML config to ensure ports don't change between
episodes or when cables are reconnected.

Usage:
    python scripts/detect_usb_ports.py                 # Show all devices
    python scripts/detect_usb_ports.py --yaml          # Output YAML snippet
    python scripts/detect_usb_ports.py --save          # Save config to ~/.dorobot_device.conf
    python scripts/detect_usb_ports.py --save --chmod  # Save config and set permissions
    python scripts/detect_usb_ports.py --chmod         # Just set permissions (chmod 777)
    python scripts/detect_usb_ports.py --watch         # Monitor device changes
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
    print("TIP: Run 'bash scripts/detect.sh' to save device config.")
    print("     Config uses short paths (/dev/videoX) for reliability.")
    print("     Re-run detect.sh if devices are reconnected to different ports.")
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


def set_device_permissions(video_devices: list, serial_devices: list):
    """
    Set chmod 777 on all detected devices and default device paths using sudo.
    Also adds user to dialout group for serial port access.
    """
    devices_to_chmod = []

    # Always include default device paths (even if not detected)
    default_devices = [
        "/dev/video0",
        "/dev/video2",
        "/dev/ttyACM0",
        "/dev/ttyACM1",
    ]

    for dev_path in default_devices:
        if dev_path not in devices_to_chmod:
            devices_to_chmod.append(dev_path)

    # Collect detected video device paths
    for dev in video_devices:
        if dev["path"] not in devices_to_chmod:
            devices_to_chmod.append(dev["path"])

    # Collect detected serial device paths
    for dev in serial_devices:
        if dev["path"] not in devices_to_chmod:
            devices_to_chmod.append(dev["path"])

    print(f"\n{'=' * 70}")
    print("Setting device permissions...")
    print(f"{'=' * 70}")

    # Step 1: Add user to dialout group for serial port access
    print("\n[1/2] Adding user to dialout group for serial port access...")
    try:
        user = os.environ.get("USER", "")
        if user:
            cmd = ["sudo", "usermod", "-aG", "dialout", user]
            print(f"Running: sudo usermod -aG dialout {user}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"User '{user}' added to dialout group.")
                print("Note: You may need to log out and log back in for group changes to take effect.")
            else:
                print(f"Warning: usermod failed: {result.stderr}")
        else:
            print("Warning: Could not determine current user.")
    except Exception as e:
        print(f"Error adding user to dialout group: {e}")

    # Step 2: Set chmod 777 on devices
    print("\n[2/2] Setting chmod 777 on devices...")

    # Filter to existing devices only
    existing_devices = [d for d in devices_to_chmod if os.path.exists(d)]

    if not existing_devices:
        print("No existing device paths found.")
        print(f"{'=' * 70}\n")
        return

    print(f"Devices to chmod ({len(existing_devices)}):")
    for dev in existing_devices:
        print(f"  - {dev}")

    # Run sudo chmod 777
    try:
        cmd = ["sudo", "chmod", "777"] + existing_devices
        print(f"\nRunning: sudo chmod 777 <devices>")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            print("Permissions set successfully!")
        else:
            print(f"Warning: chmod failed: {result.stderr}")
    except Exception as e:
        print(f"Error setting permissions: {e}")

    print(f"{'=' * 70}\n")


def save_device_config(video_devices: list, serial_devices: list, output_path: str = None, set_chmod: bool = False):
    """
    Save device configuration to a shell config file.

    This creates a file that can be sourced by run_so101.sh to set
    device paths automatically.

    Uses DETECTED device paths (not hardcoded defaults). This ensures
    the config matches actual hardware even if devices are on different ports.

    Device mapping:
    - First video capture device = Top camera
    - Second video capture device = Wrist camera
    - First serial device = Leader arm
    - Second serial device = Follower arm
    """
    if output_path is None:
        output_path = os.path.expanduser("~/.dorobot_device.conf")

    # Use detected device paths, fall back to defaults if not found
    camera_top = video_devices[0]["path"] if len(video_devices) > 0 else "/dev/video0"
    camera_wrist = video_devices[1]["path"] if len(video_devices) > 1 else "/dev/video2"
    arm_leader = serial_devices[0]["path"] if len(serial_devices) > 0 else "/dev/ttyACM0"
    arm_follower = serial_devices[1]["path"] if len(serial_devices) > 1 else "/dev/ttyACM1"

    # Build config content with DETECTED paths
    lines = [
        "# DoRobot Device Configuration",
        "# Generated by: python scripts/detect_usb_ports.py --save",
        f"# Generated on: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "#",
        "# This file is automatically sourced by run_so101.sh",
        "# Regenerate with: bash scripts/detect.sh",
        "#",
        "# NOTE: Paths are based on DETECTED devices at generation time.",
        "#       Re-run 'bash scripts/detect.sh' if devices change ports.",
        "",
        "# === Camera Configuration ===",
        f"# Top camera (detected: {video_devices[0]['path'] if len(video_devices) > 0 else 'NOT FOUND'})",
        f'CAMERA_TOP_PATH="{camera_top}"',
        "",
        f"# Wrist camera (detected: {video_devices[1]['path'] if len(video_devices) > 1 else 'NOT FOUND'})",
        f'CAMERA_WRIST_PATH="{camera_wrist}"',
        "",
        "# === Arm Configuration ===",
        f"# Leader arm (detected: {serial_devices[0]['path'] if len(serial_devices) > 0 else 'NOT FOUND'})",
        f'ARM_LEADER_PORT="{arm_leader}"',
        "",
        f"# Follower arm (detected: {serial_devices[1]['path'] if len(serial_devices) > 1 else 'NOT FOUND'})",
        f'ARM_FOLLOWER_PORT="{arm_follower}"',
        "",
    ]

    # Show all detected devices for reference
    lines.append("# === All Detected Devices ===")

    if video_devices:
        for i, dev in enumerate(video_devices):
            model = dev.get("model", "Camera")
            lines.append(f"# Video[{i}]: {dev['path']} - {model}")
    else:
        lines.append("# No video devices detected")

    if serial_devices:
        for i, dev in enumerate(serial_devices):
            model = dev.get("model", "Serial device")
            lines.append(f"# Serial[{i}]: {dev['path']} - {model}")
    else:
        lines.append("# No serial devices detected")

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

    # Set permissions if requested
    if set_chmod:
        set_device_permissions(video_devices, serial_devices)

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
    parser.add_argument(
        "--chmod",
        action="store_true",
        help="Set chmod 777 on detected devices (requires sudo)",
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
            save_device_config(video, serial, args.output, set_chmod=args.chmod)
        elif args.chmod:
            # Just chmod without saving
            set_device_permissions(video, serial)
        elif args.yaml:
            print_yaml_snippet(video, serial)
        else:
            print_devices(video, serial)


if __name__ == "__main__":
    main()
