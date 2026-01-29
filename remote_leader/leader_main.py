#!/usr/bin/env python3
"""
SO101 Leader Arm - Zenoh Publisher

This is the main entry point for the distributed SO101 leader arm system.
It reads joint positions from the leader arm and publishes them over Zenoh
for the follower system to receive.

Usage:
    # Basic usage (auto-detect port and calibration)
    python leader_main.py

    # With explicit configuration
    ARM_LEADER_PORT=/dev/ttyACM0 ZENOH_LISTEN=tcp/0.0.0.0:7447 python leader_main.py

    # Connect to a specific follower
    ZENOH_CONNECT=tcp/192.168.1.101:7447 python leader_main.py

Environment Variables:
    DOROBOT_SYSTEM_ID  - System identifier (default: "so101")
    ARM_LEADER_PORT    - Serial port for leader arm (default: auto-detect)
    ARM_NAME           - Arm name for calibration (default: "SO101-leader")
    CALIBRATION_DIR    - Calibration directory (default: "./.calibration/")
    ZENOH_LISTEN       - Zenoh listen endpoint (default: "tcp/0.0.0.0:7447")
    ZENOH_CONNECT      - Zenoh connect endpoint (optional)
    PUBLISH_RATE_HZ    - Joint publishing rate (default: 30)
"""

import os
import sys
import time
import signal
import argparse
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from arm_driver import LeaderArmDriver, find_arm_port, find_calibration_file, MOTOR_NAMES
from zenoh_publisher import LeaderZenohPublisher, LeaderConfig
from messages import SystemState, JointFlags


# =============================================================================
# Configuration
# =============================================================================

def get_config() -> dict:
    """Get configuration from environment variables."""
    return {
        "system_id": os.getenv("DOROBOT_SYSTEM_ID", "so101"),
        "arm_port": os.getenv("ARM_LEADER_PORT"),
        "arm_name": os.getenv("ARM_NAME", "SO101-leader"),
        "calibration_dir": os.getenv("CALIBRATION_DIR", "./.calibration/"),
        "zenoh_listen": os.getenv("ZENOH_LISTEN", "tcp/0.0.0.0:7447"),
        "zenoh_connect": os.getenv("ZENOH_CONNECT"),
        "publish_rate_hz": int(os.getenv("PUBLISH_RATE_HZ", "30")),
    }


# =============================================================================
# Global state for cleanup
# =============================================================================

_arm_driver: LeaderArmDriver = None
_zenoh_publisher: LeaderZenohPublisher = None
_running = True


def cleanup():
    """Cleanup resources on exit."""
    global _arm_driver, _zenoh_publisher

    print("\n[Leader] Cleaning up...")

    if _zenoh_publisher is not None:
        _zenoh_publisher.disconnect()
        _zenoh_publisher = None

    if _arm_driver is not None:
        _arm_driver.disconnect()
        _arm_driver = None


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global _running
    print(f"\n[Leader] Received signal {signum}")
    _running = False


# =============================================================================
# Main
# =============================================================================

def main():
    global _arm_driver, _zenoh_publisher, _running

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SO101 Leader Arm - Zenoh Publisher")
    parser.add_argument("--port", "-p", help="Serial port for leader arm")
    parser.add_argument("--calibration", "-c", help="Path to calibration file")
    parser.add_argument("--zenoh-listen", help="Zenoh listen endpoint")
    parser.add_argument("--zenoh-connect", help="Zenoh connect endpoint")
    parser.add_argument("--rate", "-r", type=int, help="Publishing rate in Hz")
    parser.add_argument("--system-id", help="System identifier")
    args = parser.parse_args()

    # Get configuration
    config = get_config()

    # Override with command line arguments
    if args.port:
        config["arm_port"] = args.port
    if args.calibration:
        config["calibration_dir"] = str(Path(args.calibration).parent)
        config["arm_name"] = Path(args.calibration).stem
    if args.zenoh_listen:
        config["zenoh_listen"] = args.zenoh_listen
    if args.zenoh_connect:
        config["zenoh_connect"] = args.zenoh_connect
    if args.rate:
        config["publish_rate_hz"] = args.rate
    if args.system_id:
        config["system_id"] = args.system_id

    print("=" * 60)
    print("SO101 Leader Arm - Zenoh Publisher")
    print("=" * 60)
    print(f"System ID:      {config['system_id']}")
    print(f"Zenoh Listen:   {config['zenoh_listen']}")
    print(f"Publish Rate:   {config['publish_rate_hz']} Hz")
    print("=" * 60)

    # Find arm port if not specified
    arm_port = config["arm_port"]
    if not arm_port:
        arm_port = find_arm_port()
        if not arm_port:
            print("[Leader] ERROR: Could not find arm port. Specify with --port or ARM_LEADER_PORT")
            sys.exit(1)
    print(f"[Leader] Using arm port: {arm_port}")

    # Find calibration file
    calibration_path = find_calibration_file(config["arm_name"])
    if not calibration_path:
        # Try in calibration_dir
        calibration_path = str(Path(config["calibration_dir"]) / f"{config['arm_name']}.json")
    print(f"[Leader] Using calibration: {calibration_path}")

    # Initialize arm driver
    print("\n[Leader] Initializing arm driver...")
    _arm_driver = LeaderArmDriver(
        port=arm_port,
        calibration_path=calibration_path
    )

    if not _arm_driver.connect():
        print("[Leader] ERROR: Failed to connect to arm")
        sys.exit(1)

    # Initialize Zenoh publisher
    print("\n[Leader] Initializing Zenoh publisher...")
    zenoh_config = LeaderConfig(
        system_id=config["system_id"],
        zenoh_listen=config["zenoh_listen"],
        zenoh_connect=[config["zenoh_connect"]] if config["zenoh_connect"] else None,
        heartbeat_rate_hz=1.0,
        enable_multicast=True
    )
    _zenoh_publisher = LeaderZenohPublisher(zenoh_config)

    if not _zenoh_publisher.connect():
        print("[Leader] ERROR: Failed to connect to Zenoh")
        cleanup()
        sys.exit(1)

    # Publish calibration
    print("\n[Leader] Publishing calibration...")
    calibration = _arm_driver.get_calibration()
    if calibration:
        _zenoh_publisher.publish_calibration(calibration, config["arm_name"])

    # Set state to active
    _zenoh_publisher.set_state(SystemState.ACTIVE)

    # Main loop
    print("\n" + "=" * 60)
    print(f"[Leader] Starting teleoperation at {config['publish_rate_hz']} Hz")
    print("[Leader] Press Ctrl+C to stop")
    print("=" * 60 + "\n")

    period = 1.0 / config["publish_rate_hz"]
    sequence = 0
    last_status_time = time.time()
    status_interval = 5.0  # Print status every 5 seconds

    try:
        while _running:
            loop_start = time.perf_counter()

            try:
                # Read joint positions
                positions = _arm_driver.read_normalized_positions()

                # Publish to Zenoh
                _zenoh_publisher.publish_joint_state(
                    positions,
                    flags=JointFlags.NORMALIZED | JointFlags.DEGREES_MODE | JointFlags.CALIBRATED
                )

                sequence += 1

                # Periodic status update
                if time.time() - last_status_time >= status_interval:
                    status = _zenoh_publisher.get_connection_status()
                    pos_str = ", ".join(f"{p:6.1f}" for p in positions)
                    print(f"[Leader] seq={sequence}, fps={status['fps']:.1f}, pos=[{pos_str}]")
                    last_status_time = time.time()

            except Exception as e:
                print(f"[Leader] Error in main loop: {e}")
                time.sleep(0.1)
                continue

            # Rate limiting
            elapsed = time.perf_counter() - loop_start
            if elapsed < period:
                time.sleep(period - elapsed)

    except Exception as e:
        print(f"[Leader] Fatal error: {e}")

    finally:
        cleanup()
        print("[Leader] Shutdown complete")


if __name__ == "__main__":
    main()
