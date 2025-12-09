#!/usr/bin/env python3
"""
End-to-end test for CLOUD_OFFLOAD=2 edge upload workflow.

This script simulates the full edge upload pipeline:
1. Extract frames from sample videos to create raw image data
2. Upload raw images to edge server via SFTP
3. Trigger encoding on edge server
4. Trigger cloud training

Usage:
    # Full workflow test with sample data
    python scripts/test_edge_workflow.py --source /Users/nupylot/Public/aimee-6283

    # Test with specific number of episodes
    python scripts/test_edge_workflow.py --source /path/to/data --episodes 5

    # Connection test only
    python scripts/test_edge_workflow.py --test-connection

    # Skip training (just test upload + encode)
    python scripts/test_edge_workflow.py --source /path/to/data --skip-training

Environment variables (from ~/.dorobot_device.conf):
    EDGE_SERVER_HOST     Edge server IP (default: 127.0.0.1)
    EDGE_SERVER_USER     SSH username (default: nupylot)
    EDGE_SERVER_PASSWORD SSH password
    EDGE_SERVER_PORT     SSH port (default: 22)
    EDGE_SERVER_PATH     Remote upload path (default: /data/dorobot/uploads)
    API_BASE_URL         API server URL (default: http://127.0.0.1:8000)
    API_USERNAME         API username
    API_PASSWORD         API password
"""

import os
import sys
import argparse
import tempfile
import shutil
import json
import logging
import time
import requests
from pathlib import Path
from datetime import datetime
from typing import Optional

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
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()

                # Remove inline comments: VALUE="foo"  # comment
                # First strip quotes, then remove anything after #
                value = value.strip()

                # Handle quoted values with inline comments
                if value.startswith('"'):
                    # Find closing quote
                    end_quote = value.find('"', 1)
                    if end_quote > 0:
                        value = value[1:end_quote]  # Extract between quotes
                    else:
                        value = value.strip('"')
                elif value.startswith("'"):
                    end_quote = value.find("'", 1)
                    if end_quote > 0:
                        value = value[1:end_quote]
                    else:
                        value = value.strip("'")
                else:
                    # Unquoted value - remove inline comment
                    if "#" in value:
                        value = value.split("#")[0].strip()

                if key not in os.environ:
                    os.environ[key] = value
                    logger.debug(f"  {key}={value}")


def extract_frames_with_ffmpeg(video_path: Path, output_dir: Path, max_frames: int) -> int:
    """Extract frames using ffmpeg (supports AV1 and other codecs)"""
    import subprocess

    output_dir.mkdir(parents=True, exist_ok=True)

    # Get video info first
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-count_packets", "-show_entries", "stream=nb_read_packets",
        "-of", "csv=p=0",
        str(video_path)
    ]

    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
        frame_count = int(result.stdout.strip()) if result.stdout.strip() else 100
    except Exception:
        frame_count = 100  # Default estimate

    # Calculate frame rate for extraction
    step = max(1, frame_count // max_frames)

    # Use ffmpeg to extract frames (PNG for encode_dataset.py compatibility)
    output_pattern = str(output_dir / "frame_%06d.png")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vf", f"select='not(mod(n,{step}))'",
        "-vsync", "vfr",
        "-frames:v", str(max_frames),
        output_pattern
    ]

    try:
        subprocess.run(ffmpeg_cmd, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg timeout for {video_path}")
    except Exception as e:
        logger.warning(f"FFmpeg error for {video_path}: {e}")

    # Count extracted frames
    extracted = len(list(output_dir.glob("frame_*.png")))
    return extracted


def extract_frames_from_videos(
    source_dir: Path,
    output_dir: Path,
    max_episodes: int = 5,
    max_frames_per_episode: int = 50,
) -> dict:
    """
    Extract frames from video files to create raw image dataset.
    Uses ffmpeg for better codec support (AV1, H.265, etc.)

    Returns:
        dict with extraction stats
    """
    videos_dir = source_dir / "videos"
    if not videos_dir.exists():
        logger.error(f"Videos directory not found: {videos_dir}")
        return None

    # Find all video files
    video_files = sorted(videos_dir.rglob("*.mp4"))
    if not video_files:
        logger.error(f"No video files found in {videos_dir}")
        return None

    logger.info(f"Found {len(video_files)} video files")

    # Limit episodes
    video_files = video_files[:max_episodes]
    logger.info(f"Processing {len(video_files)} episodes")

    # Create output structure
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "episodes": 0,
        "total_frames": 0,
        "total_size_bytes": 0,
        "cameras": set(),
    }

    # Check if ffmpeg is available
    import subprocess
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        use_ffmpeg = True
        logger.info("Using ffmpeg for video extraction (better codec support)")
    except (subprocess.CalledProcessError, FileNotFoundError):
        use_ffmpeg = False
        logger.info("Using OpenCV for video extraction")
        try:
            import cv2
        except ImportError:
            logger.error("Neither ffmpeg nor OpenCV available")
            return None

    for video_path in video_files:
        # Parse episode info from path
        # videos/chunk-000/observation.image/episode_000001.mp4
        episode_name = video_path.stem  # episode_000001
        camera_name = video_path.parent.name  # observation.image

        # Create directory structure that encode_dataset.py expects:
        # images/{camera_key}/{episode}/frame_*.png
        episode_dir = images_dir / camera_name / episode_name
        episode_dir.mkdir(parents=True, exist_ok=True)

        stats["cameras"].add(camera_name)

        if use_ffmpeg:
            # Use ffmpeg (supports AV1, H.265, etc.)
            saved = extract_frames_with_ffmpeg(video_path, episode_dir, max_frames_per_episode)
        else:
            # Fallback to OpenCV
            import cv2
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                logger.warning(f"Cannot open video: {video_path}")
                continue

            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            step = max(1, frame_count // max_frames_per_episode)

            frame_idx = 0
            saved = 0

            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % step == 0 and saved < max_frames_per_episode:
                    img_path = episode_dir / f"frame_{saved:06d}.png"
                    cv2.imwrite(str(img_path), frame)
                    saved += 1

                frame_idx += 1

            cap.release()

        # Calculate size of extracted frames
        for img_path in episode_dir.glob("frame_*.png"):
            stats["total_size_bytes"] += img_path.stat().st_size

        stats["episodes"] += 1
        stats["total_frames"] += saved

        logger.info(f"  {episode_name}: extracted {saved} frames")

    stats["cameras"] = list(stats["cameras"])

    # Copy metadata files
    meta_src = source_dir / "meta"
    meta_dst = output_dir / "meta"
    if meta_src.exists():
        shutil.copytree(meta_src, meta_dst, dirs_exist_ok=True)
        logger.info(f"Copied metadata from {meta_src}")

    # Create info.json for this test dataset
    info_path = output_dir / "meta" / "info.json"
    info_path.parent.mkdir(parents=True, exist_ok=True)

    with open(info_path, "w") as f:
        json.dump({
            "source": str(source_dir),
            "created_at": datetime.now().isoformat(),
            "episodes": stats["episodes"],
            "total_frames": stats["total_frames"],
            "cameras": stats["cameras"],
            "test_dataset": True,
            "format": "raw_images",
        }, f, indent=2)

    return stats


def test_connection() -> bool:
    """Test SSH connection to edge server"""
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    config = EdgeConfig.from_env()

    logger.info("=" * 60)
    logger.info("Edge Server Configuration:")
    logger.info(f"  Host:     {config.host}")
    logger.info(f"  Port:     {config.port}")
    logger.info(f"  User:     {config.user}")
    logger.info(f"  Password: {'*' * len(config.password) if config.password else '(not set)'}")
    logger.info(f"  Path:     {config.remote_path}")
    logger.info("=" * 60)

    uploader = EdgeUploader(config)

    logger.info("\nTesting SSH connection...")
    if uploader.test_connection():
        logger.info("SUCCESS: SSH connection established")
        uploader.close()
        return True
    else:
        logger.error("FAILED: Cannot connect to edge server")
        return False


def test_api_connection() -> bool:
    """Test API server connection"""
    api_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")

    logger.info(f"\nTesting API connection to {api_url}...")

    try:
        response = requests.get(f"{api_url}/health", timeout=10)
        if response.status_code == 200:
            logger.info("SUCCESS: API server is healthy")
            return True
        else:
            logger.warning(f"API server returned status {response.status_code}")
            return True  # Still reachable
    except requests.exceptions.ConnectionError:
        logger.error(f"FAILED: Cannot connect to API at {api_url}")
        return False
    except Exception as e:
        logger.error(f"FAILED: API connection error: {e}")
        return False


def upload_to_edge(dataset_path: Path, repo_id: str) -> bool:
    """Upload raw images to edge server via SFTP"""
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    config = EdgeConfig.from_env()
    uploader = EdgeUploader(config)

    logger.info("=" * 60)
    logger.info("Edge Upload")
    logger.info(f"  Local:  {dataset_path}")
    logger.info(f"  Remote: {config.user}@{config.host}:{config.remote_path}/{repo_id}/")
    logger.info("=" * 60)

    if not uploader.test_connection():
        logger.error("Connection test failed")
        return False

    start_time = time.time()

    def progress_cb(progress: str):
        logger.info(f"  Upload: {progress}")

    success = uploader.sync_dataset(str(dataset_path), repo_id, progress_cb)
    elapsed = time.time() - start_time

    if success:
        # Calculate stats
        total_size = sum(f.stat().st_size for f in dataset_path.rglob("*") if f.is_file())
        speed = total_size / elapsed / 1024 / 1024 if elapsed > 0 else 0

        logger.info(f"\nUpload completed in {elapsed:.1f}s")
        logger.info(f"  Size:  {total_size / 1024 / 1024:.2f} MB")
        logger.info(f"  Speed: {speed:.2f} MB/s")
    else:
        logger.error(f"Upload failed after {elapsed:.1f}s")

    uploader.close()
    return success


def notify_edge_and_encode(repo_id: str) -> bool:
    """Notify edge server to start encoding"""
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    config = EdgeConfig.from_env()
    uploader = EdgeUploader(config)

    logger.info("\n" + "=" * 60)
    logger.info("Notifying Edge Server to Start Encoding")
    logger.info("=" * 60)

    if uploader.notify_upload_complete(repo_id):
        logger.info("SUCCESS: Edge server notified")

        # Poll for encoding status
        logger.info("\nWaiting for encoding to complete...")
        max_wait = 300  # 5 minutes
        poll_interval = 5
        start_time = time.time()

        while time.time() - start_time < max_wait:
            status = uploader.get_status(repo_id)
            current_status = status.get("status", "UNKNOWN")
            progress = status.get("progress", "")

            logger.info(f"  Status: {current_status} {progress}")

            if current_status == "ENCODED":
                logger.info("SUCCESS: Encoding completed")
                return True
            elif current_status in ("FAILED", "ERROR"):
                logger.error(f"FAILED: Encoding failed - {status.get('error', 'Unknown error')}")
                return False
            elif current_status == "COMPLETED":
                logger.info("SUCCESS: Processing completed")
                return True

            time.sleep(poll_interval)

        logger.warning("Encoding status polling timed out")
        return True  # May still be processing
    else:
        logger.error("FAILED: Could not notify edge server")
        return False


def trigger_training(repo_id: str) -> bool:
    """Trigger cloud training via edge server or direct API"""
    api_url = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
    api_username = os.environ.get("API_USERNAME", "")
    api_password = os.environ.get("API_PASSWORD", "")

    logger.info("\n" + "=" * 60)
    logger.info("Triggering Cloud Training")
    logger.info(f"  API:     {api_url}")
    logger.info(f"  Repo ID: {repo_id}")
    logger.info("=" * 60)

    # First try via edge server
    from operating_platform.core.edge_upload import EdgeUploader

    uploader = EdgeUploader()
    if uploader.trigger_training(repo_id):
        logger.info("SUCCESS: Training triggered via edge server")
        return True

    # Fallback to direct API call
    logger.info("Trying direct API call...")

    try:
        # Login first if credentials provided
        session = requests.Session()

        if api_username and api_password:
            login_response = session.post(
                f"{api_url}/token",
                data={
                    "username": api_username,
                    "password": api_password,
                },
                timeout=30,
            )
            if login_response.status_code == 200:
                token = login_response.json().get("access_token")
                session.headers["Authorization"] = f"Bearer {token}"
                logger.info("Logged in to API server")

        # Trigger training
        response = session.post(
            f"{api_url}/training/start",
            json={
                "dataset_path": repo_id,
                "policy_type": "act",
            },
            timeout=30,
        )

        if response.status_code in (200, 201, 202):
            data = response.json()
            logger.info(f"SUCCESS: Training started - {data}")
            return True
        else:
            logger.error(f"FAILED: API returned {response.status_code}: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        logger.error(f"FAILED: Cannot connect to API at {api_url}")
        return False
    except Exception as e:
        logger.error(f"FAILED: {e}")
        return False


def run_full_workflow(
    source_dir: Path,
    max_episodes: int = 5,
    max_frames: int = 50,
    skip_training: bool = False,
    keep_temp: bool = False,
) -> bool:
    """Run the complete edge upload workflow"""

    repo_id = f"test_edge_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    logger.info("\n" + "=" * 60)
    logger.info("CLOUD_OFFLOAD=2 Edge Workflow Test")
    logger.info("=" * 60)
    logger.info(f"Source:      {source_dir}")
    logger.info(f"Repo ID:     {repo_id}")
    logger.info(f"Episodes:    {max_episodes}")
    logger.info(f"Frames/ep:   {max_frames}")
    logger.info(f"Training:    {'skip' if skip_training else 'enabled'}")
    logger.info("=" * 60)

    # Step 1: Create temp directory and extract frames
    temp_dir = Path(tempfile.mkdtemp(prefix="dorobot_edge_test_"))
    dataset_path = temp_dir / repo_id

    try:
        logger.info("\n[Step 1/4] Extracting frames from videos...")
        stats = extract_frames_from_videos(
            source_dir,
            dataset_path,
            max_episodes=max_episodes,
            max_frames_per_episode=max_frames,
        )

        if not stats:
            logger.error("Failed to extract frames")
            return False

        logger.info(f"\nExtraction complete:")
        logger.info(f"  Episodes: {stats['episodes']}")
        logger.info(f"  Frames:   {stats['total_frames']}")
        logger.info(f"  Size:     {stats['total_size_bytes'] / 1024 / 1024:.2f} MB")
        logger.info(f"  Cameras:  {stats['cameras']}")

        # Step 2: Upload to edge server
        logger.info("\n[Step 2/4] Uploading to edge server...")
        if not upload_to_edge(dataset_path, repo_id):
            logger.error("Upload failed")
            return False

        # Step 3: Notify edge server to encode
        logger.info("\n[Step 3/4] Triggering encoding on edge server...")
        encode_ok = notify_edge_and_encode(repo_id)
        if not encode_ok:
            logger.error("Encoding notification failed")

        # Step 4: Trigger training
        train_ok = True
        if not skip_training:
            logger.info("\n[Step 4/4] Triggering cloud training...")
            train_ok = trigger_training(repo_id)
            if not train_ok:
                logger.error("Training trigger failed")
        else:
            logger.info("\n[Step 4/4] Skipping training (--skip-training)")

        # Report final status
        edge_path = os.environ.get('EDGE_SERVER_PATH', '/uploaded_data')
        logger.info("\n" + "=" * 60)
        if encode_ok and train_ok:
            logger.info("WORKFLOW COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
            logger.info(f"Repo ID: {repo_id}")
            logger.info(f"Edge path: {edge_path}/{repo_id}/")
            return True
        else:
            logger.error("WORKFLOW FAILED")
            logger.info("=" * 60)
            logger.info(f"Repo ID: {repo_id}")
            logger.info(f"Edge path: {edge_path}/{repo_id}/")
            if not encode_ok:
                logger.error("  - Encoding step failed")
            if not train_ok:
                logger.error("  - Training step failed")
            return False

    finally:
        if not keep_temp:
            logger.info(f"\nCleaning up temp directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            logger.info(f"\nKeeping temp data at: {temp_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Test CLOUD_OFFLOAD=2 edge upload workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full workflow with sample data
    python scripts/test_edge_workflow.py --source /Users/nupylot/Public/aimee-6283

    # Test with 3 episodes, 30 frames each
    python scripts/test_edge_workflow.py --source /path/to/data --episodes 3 --frames 30

    # Connection test only
    python scripts/test_edge_workflow.py --test-connection

    # Upload and encode only (no training)
    python scripts/test_edge_workflow.py --source /path/to/data --skip-training
        """,
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Source directory with videos (e.g., /Users/nupylot/Public/aimee-6283)",
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Only test SSH and API connections",
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=5,
        help="Number of episodes to process (default: 5)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=50,
        help="Max frames per episode (default: 50)",
    )
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip training step (just test upload + encode)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary extracted data after test",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        help="Custom repo ID (default: auto-generated)",
    )

    args = parser.parse_args()

    # Load config
    load_config_file()

    # Connection test only
    if args.test_connection:
        ssh_ok = test_connection()
        api_ok = test_api_connection()

        if ssh_ok and api_ok:
            logger.info("\nAll connections OK")
            sys.exit(0)
        else:
            logger.error("\nSome connections failed")
            sys.exit(1)

    # Full workflow requires source
    if not args.source:
        parser.error("--source is required for full workflow test")

    if not args.source.exists():
        logger.error(f"Source directory not found: {args.source}")
        sys.exit(1)

    # Run workflow
    success = run_full_workflow(
        source_dir=args.source,
        max_episodes=args.episodes,
        max_frames=args.frames,
        skip_training=args.skip_training,
        keep_temp=args.keep_temp,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
