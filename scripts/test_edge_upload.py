#!/usr/bin/env python3
"""
Test script for edge upload functionality (CLOUD=2 mode).

This script simulates an edge upload by:
1. Creating test image data (or using existing dataset)
2. Testing SSH/SFTP connection to edge server
3. Uploading test data
4. Verifying upload success

Usage:
    # Test with synthetic data
    python scripts/test_edge_upload.py

    # Test with existing dataset
    python scripts/test_edge_upload.py --dataset /path/to/dataset

    # Connection test only
    python scripts/test_edge_upload.py --test-connection

Environment variables (from ~/.dorobot_device.conf):
    EDGE_SERVER_HOST     Edge server IP (default: 127.0.0.1)
    EDGE_SERVER_USER     SSH username (default: nupylot)
    EDGE_SERVER_PASSWORD SSH password
    EDGE_SERVER_PORT     SSH port (default: 22)
    EDGE_SERVER_PATH     Remote upload path (default: /data/dorobot/uploads)
"""

import os
import sys
import argparse
import tempfile
import shutil
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


def load_config_file():
    """Load configuration from ~/.dorobot_device.conf"""
    config_path = Path.home() / ".dorobot_device.conf"

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}")
        logger.info("Using default/environment values")
        return

    logger.info(f"Loading config from: {config_path}")

    with open(config_path, "r") as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Parse KEY="value" or KEY=value
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                # Only set if not already in environment (env takes precedence)
                if key not in os.environ:
                    os.environ[key] = value
                    logger.debug(f"  Set {key}={value[:20]}..." if len(value) > 20 else f"  Set {key}={value}")


def create_test_dataset(output_dir: Path, num_episodes: int = 2, frames_per_episode: int = 10):
    """Create synthetic test dataset with images"""
    logger.info(f"Creating test dataset with {num_episodes} episodes, {frames_per_episode} frames each")

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        logger.error("NumPy and Pillow required. Install with: pip install numpy pillow")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)

    # Create images directory structure (similar to edge upload format)
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Create metadata file
    meta_dir = output_dir / "meta"
    meta_dir.mkdir(exist_ok=True)

    total_frames = 0

    for ep in range(num_episodes):
        episode_dir = images_dir / f"episode_{ep:06d}"
        episode_dir.mkdir(exist_ok=True)

        # Create camera subdirectories
        for cam in ["observation.image.camera_top", "observation.image.camera_wrist"]:
            cam_dir = episode_dir / cam
            cam_dir.mkdir(exist_ok=True)

            for frame in range(frames_per_episode):
                # Create random test image (480x640 RGB)
                img_array = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

                # Add frame number as text overlay (simple pattern)
                # Put episode/frame info in corner pixels
                img_array[0, 0] = [ep, frame, 255]  # Marker pixel

                img = Image.fromarray(img_array)
                img_path = cam_dir / f"frame_{frame:06d}.jpg"
                img.save(img_path, quality=85)
                total_frames += 1

    # Create simple metadata file
    import json
    meta_path = meta_dir / "info.json"
    with open(meta_path, "w") as f:
        json.dump({
            "num_episodes": num_episodes,
            "frames_per_episode": frames_per_episode,
            "total_frames": total_frames,
            "cameras": ["camera_top", "camera_wrist"],
            "created_at": datetime.now().isoformat(),
            "test_dataset": True,
        }, f, indent=2)

    logger.info(f"Created test dataset: {total_frames} frames in {output_dir}")
    return True


def extract_frames_from_videos(video_dir: Path, output_dir: Path, max_frames: int = 20):
    """Extract frames from existing video files for testing"""
    try:
        import cv2
    except ImportError:
        logger.warning("OpenCV not available, skipping video extraction")
        return False

    video_files = list(video_dir.rglob("*.mp4"))
    if not video_files:
        logger.warning(f"No video files found in {video_dir}")
        return False

    logger.info(f"Found {len(video_files)} video files, extracting frames...")

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images" / "episode_000000"
    images_dir.mkdir(parents=True, exist_ok=True)

    total_frames = 0

    for video_path in video_files[:2]:  # Limit to 2 videos
        cam_name = video_path.stem
        cam_dir = images_dir / f"observation.image.{cam_name}"
        cam_dir.mkdir(exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        step = max(1, frame_count // max_frames)

        frame_idx = 0
        saved = 0
        while cap.isOpened() and saved < max_frames:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                img_path = cam_dir / f"frame_{saved:06d}.jpg"
                cv2.imwrite(str(img_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                saved += 1
                total_frames += 1

            frame_idx += 1

        cap.release()
        logger.info(f"  Extracted {saved} frames from {video_path.name}")

    logger.info(f"Total frames extracted: {total_frames}")
    return True


def test_connection():
    """Test SSH connection to edge server"""
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    config = EdgeConfig.from_env()

    logger.info("=" * 50)
    logger.info("Edge Server Configuration:")
    logger.info(f"  Host:     {config.host}")
    logger.info(f"  Port:     {config.port}")
    logger.info(f"  User:     {config.user}")
    logger.info(f"  Password: {'*' * len(config.password) if config.password else '(not set)'}")
    logger.info(f"  Path:     {config.remote_path}")
    logger.info("=" * 50)

    uploader = EdgeUploader(config)

    logger.info("\nTesting SSH connection...")
    if uploader.test_connection():
        logger.info("SUCCESS: SSH connection established")

        # Test directory creation
        logger.info("\nTesting remote directory creation...")
        test_dir = f"test_connection_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if uploader.create_remote_directory(test_dir):
            logger.info(f"SUCCESS: Created remote directory: {config.remote_path}/{test_dir}")

            # Clean up test directory
            try:
                uploader._exec_remote_command(f"rmdir '{config.remote_path}/{test_dir}'")
                logger.info("Cleaned up test directory")
            except Exception:
                pass
        else:
            logger.error("FAILED: Could not create remote directory")
            return False

        uploader.close()
        return True
    else:
        logger.error("FAILED: Cannot connect to edge server")
        logger.info("\nTroubleshooting tips:")
        logger.info("  1. Check that the edge server is running and accessible")
        logger.info("  2. Verify EDGE_SERVER_HOST is correct")
        logger.info("  3. Verify EDGE_SERVER_PASSWORD is correct")
        logger.info("  4. Check firewall settings on port 22")
        return False


def test_upload(dataset_path: Path, repo_id: str = None):
    """Test uploading a dataset to edge server"""
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    if repo_id is None:
        repo_id = f"test_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    config = EdgeConfig.from_env()
    uploader = EdgeUploader(config)

    logger.info("=" * 50)
    logger.info("Edge Upload Test")
    logger.info(f"  Local path:  {dataset_path}")
    logger.info(f"  Repo ID:     {repo_id}")
    logger.info(f"  Remote dest: {config.user}@{config.host}:{config.remote_path}/{repo_id}/")
    logger.info("=" * 50)

    # Test connection first
    if not uploader.test_connection():
        logger.error("Connection test failed")
        return False

    # Upload dataset
    logger.info("\nStarting upload...")
    start_time = datetime.now()

    def progress_cb(progress: str):
        logger.info(f"  Progress: {progress}")

    success = uploader.sync_dataset(str(dataset_path), repo_id, progress_cb)

    elapsed = (datetime.now() - start_time).total_seconds()

    if success:
        logger.info(f"\nSUCCESS: Upload completed in {elapsed:.1f}s")
        logger.info(f"Data uploaded to: {config.host}:{config.remote_path}/{repo_id}/")

        # Calculate upload size
        total_size = sum(f.stat().st_size for f in dataset_path.rglob("*") if f.is_file())
        speed = total_size / elapsed / 1024 / 1024 if elapsed > 0 else 0
        logger.info(f"Upload size: {total_size / 1024 / 1024:.2f} MB")
        logger.info(f"Upload speed: {speed:.2f} MB/s")
    else:
        logger.error(f"\nFAILED: Upload failed after {elapsed:.1f}s")

    uploader.close()
    return success


def main():
    parser = argparse.ArgumentParser(description="Test edge upload functionality")
    parser.add_argument(
        "--dataset",
        type=Path,
        help="Path to existing dataset to upload (default: create synthetic data)",
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Only test SSH connection, don't upload",
    )
    parser.add_argument(
        "--extract-from",
        type=Path,
        help="Extract frames from videos in this directory for testing",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        help="Repository ID for the upload (default: auto-generated)",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=2,
        help="Number of test episodes to create (default: 2)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=10,
        help="Number of frames per episode (default: 10)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary test data after upload",
    )

    args = parser.parse_args()

    # Load config file first
    load_config_file()

    # Connection test only
    if args.test_connection:
        success = test_connection()
        sys.exit(0 if success else 1)

    # Determine dataset path
    temp_dir = None
    dataset_path = args.dataset

    if dataset_path is None:
        # Create temporary test data
        temp_dir = Path(tempfile.mkdtemp(prefix="dorobot_test_"))
        dataset_path = temp_dir / "test_dataset"

        if args.extract_from:
            # Extract frames from existing videos
            if not extract_frames_from_videos(args.extract_from, dataset_path, max_frames=args.frames):
                # Fall back to synthetic data
                logger.info("Falling back to synthetic test data")
                if not create_test_dataset(dataset_path, args.episodes, args.frames):
                    logger.error("Failed to create test dataset")
                    sys.exit(1)
        else:
            # Create synthetic test data
            if not create_test_dataset(dataset_path, args.episodes, args.frames):
                logger.error("Failed to create test dataset")
                sys.exit(1)

    # Run upload test
    try:
        success = test_upload(dataset_path, args.repo_id)
    finally:
        # Clean up temp directory unless --keep-temp
        if temp_dir and not args.keep_temp:
            logger.info(f"Cleaning up temp directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
        elif temp_dir:
            logger.info(f"Keeping temp data at: {temp_dir}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
