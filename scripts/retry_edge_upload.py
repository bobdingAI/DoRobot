#!/usr/bin/env python3
"""
Retry edge upload for existing raw image datasets.

Use this when CLOUD=2 data collection succeeded locally but edge upload failed.
This script uploads existing raw images to edge server for encoding and training.

Usage:
    # Upload dataset and trigger training
    python scripts/retry_edge_upload.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (no training)
    python scripts/retry_edge_upload.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection first
    python scripts/retry_edge_upload.py --test-connection

    # Custom repo ID (if different from folder name)
    python scripts/retry_edge_upload.py --dataset ~/DoRobot/dataset/my_data --repo-id custom_name

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


def load_config_file():
    """Load configuration from ~/.dorobot_device.conf"""
    config_path = Path.home() / ".dorobot_device.conf"

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}")
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


def test_connection() -> bool:
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
        logger.info("SUCCESS: SSH connection OK")
        uploader.close()
        return True
    else:
        logger.error("FAILED: Cannot connect to edge server")
        return False


def retry_upload(dataset_path: Path, repo_id: str, skip_training: bool = False) -> bool:
    """
    Retry uploading raw images to edge server.

    Args:
        dataset_path: Local path to dataset with raw images
        repo_id: Repository ID for edge server
        skip_training: If True, skip training trigger
    """
    from operating_platform.core.edge_upload import run_edge_upload, EdgeConfig

    # Validate dataset path
    if not dataset_path.exists():
        logger.error(f"Dataset path not found: {dataset_path}")
        return False

    # Check for images directory (raw images)
    images_dir = dataset_path / "images"
    if not images_dir.exists():
        logger.error(f"No 'images' directory found in {dataset_path}")
        logger.error("This script is for raw image datasets (CLOUD=2 mode)")
        return False

    # Count images
    image_count = len(list(images_dir.rglob("*.png"))) + len(list(images_dir.rglob("*.jpg")))
    if image_count == 0:
        logger.error(f"No images found in {images_dir}")
        return False

    # Get config for display
    config = EdgeConfig.from_env()

    logger.info("=" * 50)
    logger.info("Retry Edge Upload")
    logger.info("=" * 50)
    logger.info(f"Dataset:     {dataset_path}")
    logger.info(f"Repo ID:     {repo_id}")
    logger.info(f"Images:      {image_count}")
    logger.info(f"Edge Server: {config.user}@{config.host}:{config.port}")
    logger.info(f"Remote Path: {config.remote_path}/{repo_id}/")
    logger.info(f"Training:    {'skip' if skip_training else 'enabled'}")
    logger.info("=" * 50)

    # Run upload
    logger.info("\nStarting upload...")

    success = run_edge_upload(
        dataset_path=str(dataset_path),
        repo_id=repo_id,
        trigger_training=not skip_training,
        wait_for_training=False,  # Edge server handles training async
    )

    if success:
        logger.info("=" * 50)
        logger.info("UPLOAD COMPLETED SUCCESSFULLY")
        logger.info("=" * 50)
        logger.info(f"Edge server will encode videos and start training")
        logger.info(f"Monitor progress at: {config.api_url}/edge/status/{repo_id}")
    else:
        logger.error("=" * 50)
        logger.error("UPLOAD FAILED")
        logger.error("=" * 50)
        logger.error("Check edge server connection and try again")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="Retry edge upload for raw image datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Upload and trigger training
    python scripts/retry_edge_upload.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (skip training)
    python scripts/retry_edge_upload.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection
    python scripts/retry_edge_upload.py --test-connection

    # Custom repo ID
    python scripts/retry_edge_upload.py --dataset /path/to/data --repo-id my_custom_name
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
        help="Only test SSH connection to edge server",
    )

    args = parser.parse_args()

    # Load config
    load_config_file()

    # Connection test only
    if args.test_connection:
        success = test_connection()
        sys.exit(0 if success else 1)

    # Upload requires dataset
    if not args.dataset:
        parser.error("--dataset is required (or use --test-connection)")

    # Resolve dataset path
    dataset_path = args.dataset.expanduser().resolve()

    # Use folder name as repo_id if not specified
    repo_id = args.repo_id or dataset_path.name

    # Run upload
    success = retry_upload(
        dataset_path=dataset_path,
        repo_id=repo_id,
        skip_training=args.skip_training,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
