#!/usr/bin/env python3
"""
Edge encode - Upload raw image datasets to edge server for encoding and training.

Use this when CLOUD=2 data collection succeeded locally but edge upload failed,
or when you want to manually trigger edge encoding for an existing dataset.

Usage:
    # Upload dataset and trigger training
    python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (no training)
    python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection first
    python scripts/edge_encode.py --test-connection

    # Custom repo ID (if different from folder name)
    python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_data --repo-id custom_name

Environment variables (from ~/.dorobot_device.conf):
    EDGE_SERVER_HOST     Edge server IP
    EDGE_SERVER_USER     SSH username
    EDGE_SERVER_PASSWORD SSH password
    EDGE_SERVER_PORT     SSH port (default: 22)
    EDGE_SERVER_PATH     Remote upload path
    API_BASE_URL         API server URL
"""

import os
import sys
import argparse
import logging
import time
import requests
from pathlib import Path

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


# =============================================================================
# Functions borrowed from test_edge_workflow.py (proven working)
# =============================================================================

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
                value = value.strip()

                # Handle quoted values with inline comments
                if value.startswith('"'):
                    end_quote = value.find('"', 1)
                    if end_quote > 0:
                        value = value[1:end_quote]
                    else:
                        value = value.strip('"')
                elif value.startswith("'"):
                    end_quote = value.find("'", 1)
                    if end_quote > 0:
                        value = value[1:end_quote]
                    else:
                        value = value.strip("'")
                else:
                    if "#" in value:
                        value = value.split("#")[0].strip()

                if key not in os.environ:
                    os.environ[key] = value
                    logger.debug(f"  {key}={value}")


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

            if current_status in ("ENCODED", "READY"):
                logger.info("SUCCESS: Encoding completed")
                return True
            elif current_status in ("FAILED", "ERROR", "ENCODING_FAILED"):
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


# =============================================================================
# Main workflow (similar to test_edge_workflow.py but without frame extraction)
# =============================================================================

def run_retry_workflow(
    dataset_path: Path,
    repo_id: str,
    skip_training: bool = False,
) -> bool:
    """Run the edge upload retry workflow"""

    logger.info("\n" + "=" * 60)
    logger.info("Retry Edge Upload Workflow")
    logger.info("=" * 60)
    logger.info(f"Dataset:     {dataset_path}")
    logger.info(f"Repo ID:     {repo_id}")
    logger.info(f"Training:    {'skip' if skip_training else 'enabled'}")
    logger.info("=" * 60)

    # Validate dataset
    if not dataset_path.exists():
        logger.error(f"Dataset path not found: {dataset_path}")
        return False

    # Check for images directory
    images_dir = dataset_path / "images"
    if not images_dir.exists():
        logger.error(f"No 'images' directory found in {dataset_path}")
        logger.error("This script is for raw image datasets (CLOUD=2 mode)")
        return False

    # Count images
    png_count = len(list(images_dir.rglob("*.png")))
    jpg_count = len(list(images_dir.rglob("*.jpg")))
    image_count = png_count + jpg_count

    if image_count == 0:
        logger.error(f"No images found in {images_dir}")
        return False

    # Calculate total size
    total_size = sum(f.stat().st_size for f in dataset_path.rglob("*") if f.is_file())

    logger.info(f"\nDataset info:")
    logger.info(f"  Images:   {image_count} ({png_count} PNG, {jpg_count} JPG)")
    logger.info(f"  Size:     {total_size / 1024 / 1024:.2f} MB")

    # Step 1: Upload to edge server
    logger.info("\n[Step 1/3] Uploading to edge server...")
    if not upload_to_edge(dataset_path, repo_id):
        logger.error("Upload failed")
        return False

    # Step 2: Notify edge server to encode
    logger.info("\n[Step 2/3] Triggering encoding on edge server...")
    encode_ok = notify_edge_and_encode(repo_id)
    if not encode_ok:
        logger.error("Encoding notification failed")

    # Step 3: Trigger training
    train_ok = True
    if not skip_training:
        logger.info("\n[Step 3/3] Triggering cloud training...")
        train_ok = trigger_training(repo_id)
        if not train_ok:
            logger.error("Training trigger failed")
    else:
        logger.info("\n[Step 3/3] Skipping training (--skip-training)")

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


def main():
    parser = argparse.ArgumentParser(
        description="Retry edge upload for raw image datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Upload and trigger training
    python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (skip training)
    python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection first
    python scripts/edge_encode.py --test-connection

    # Custom repo ID
    python scripts/edge_encode.py --dataset /path/to/data --repo-id my_custom_name
        """,
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        help="Path to dataset directory with raw images",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        help="Repository ID (default: folder name from --dataset)",
    )
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip training trigger (just upload + encode)",
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Only test SSH and API connections",
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

    # Upload requires dataset
    if not args.dataset:
        parser.error("--dataset is required (or use --test-connection)")

    # Resolve dataset path
    dataset_path = args.dataset.expanduser().resolve()

    # Use folder name as repo_id if not specified
    repo_id = args.repo_id or dataset_path.name

    # Run workflow
    success = run_retry_workflow(
        dataset_path=dataset_path,
        repo_id=repo_id,
        skip_training=args.skip_training,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
