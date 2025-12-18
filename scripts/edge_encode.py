#!/usr/bin/env python3
"""
Edge encode - Full workflow: Upload -> Encode -> Train -> Download Model

This script handles the complete edge workflow:
1. Upload raw image dataset to edge server via SFTP
2. Trigger encoding on edge server
3. Trigger cloud training
4. Wait for training completion (showing transaction ID)
5. Download trained model to local path

The script will NOT exit until training completes and model is downloaded.
Multiple instances can run in parallel for different datasets (isolated by username).

Designed for shared edge servers - use edge.sh wrapper for easier invocation:

    scripts/edge.sh -u <username> -p <password> -d <dataset_path> [options]

Direct usage:
    # Full workflow (via environment variables)
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (no training)
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --test-connection

Output:
    Default model path: {dataset_path}/model/

Environment variables:
    API_USERNAME         API username for authentication and path isolation (REQUIRED)
    API_PASSWORD         API password for authentication (REQUIRED for training)
    API_BASE_URL         API server URL (default: http://127.0.0.1:8000)
    EDGE_SERVER_HOST     Edge server IP (default: 127.0.0.1)
    EDGE_SERVER_USER     SSH username
    EDGE_SERVER_PASSWORD SSH password
    EDGE_SERVER_PORT     SSH port (default: 22)
    EDGE_SERVER_PATH     Remote upload path (default: /uploaded_data)

Upload path structure: {EDGE_SERVER_PATH}/{API_USERNAME}/{REPO_ID}/
    This isolates uploads by user to avoid conflicts on shared API servers.
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
    logger.info(f"  API User: {config.api_username}")
    logger.info(f"  Upload:   {config.remote_path}/{config.api_username}/<repo_id>/")
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

    # Full upload path includes username for multi-user isolation
    upload_path = config.get_upload_path(repo_id)

    logger.info("=" * 60)
    logger.info("Edge Upload")
    logger.info(f"  Local:  {dataset_path}")
    logger.info(f"  Remote: {config.user}@{config.host}:{upload_path}/")
    logger.info(f"  API User: {config.api_username}")
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


def trigger_training(repo_id: str) -> tuple:
    """
    Trigger cloud training via edge server or direct API.

    Returns:
        (success: bool, transaction_id: str or None)
    """
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
    success, transaction_id = uploader.trigger_training(repo_id)
    if success:
        logger.info("SUCCESS: Training triggered via edge server")
        if transaction_id:
            logger.info(f"Transaction ID: {transaction_id}")
        return True, transaction_id

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
            transaction_id = data.get("transaction_id")
            logger.info(f"SUCCESS: Training started - {data}")
            if transaction_id:
                logger.info(f"Transaction ID: {transaction_id}")
            return True, transaction_id
        else:
            logger.error(f"FAILED: API returned {response.status_code}: {response.text}")
            return False, None

    except requests.exceptions.ConnectionError:
        logger.error(f"FAILED: Cannot connect to API at {api_url}")
        return False, None
    except Exception as e:
        logger.error(f"FAILED: {e}")
        return False, None


def wait_training_and_download(
    repo_id: str,
    transaction_id: str,
    local_model_path: Path,
    timeout_minutes: int = 120,
) -> bool:
    """
    Wait for training completion and download model to local path.

    Args:
        repo_id: Dataset repository ID
        transaction_id: Training transaction ID from API
        local_model_path: Local path to save model (e.g., dataset_path/model)
        timeout_minutes: Timeout for training completion (default 120 min)

    Returns:
        True if training completed and model downloaded successfully
    """
    from operating_platform.core.edge_upload import EdgeUploader, EdgeConfig

    config = EdgeConfig.from_env()
    uploader = EdgeUploader(config)

    logger.info("\n" + "=" * 60)
    logger.info("Waiting for Training Completion")
    logger.info("=" * 60)
    logger.info(f"  Repo ID:        {repo_id}")
    logger.info(f"  Transaction ID: {transaction_id}")
    logger.info(f"  Output Model:   {local_model_path}")
    logger.info(f"  Timeout:        {timeout_minutes} minutes")
    logger.info("=" * 60)

    # Poll for training status
    poll_interval = 15  # seconds
    start_time = time.time()
    timeout_seconds = timeout_minutes * 60

    last_status = ""
    while (time.time() - start_time) < timeout_seconds:
        elapsed = int(time.time() - start_time)
        elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"

        status = uploader.get_status(repo_id)
        current_status = status.get("status", "UNKNOWN")
        progress = status.get("progress", "")
        model_path = status.get("model_path")

        # Only log if status changed
        status_str = f"{current_status} {progress}"
        if status_str != last_status:
            logger.info(f"[{elapsed_str}] Status: {current_status} {progress}")
            last_status = status_str

        if current_status == "COMPLETED":
            logger.info(f"\nTraining completed in {elapsed_str}")
            if model_path:
                logger.info(f"Remote model path: {model_path}")

                # Download model
                logger.info("\n" + "=" * 60)
                logger.info("Downloading Trained Model")
                logger.info("=" * 60)

                def progress_cb(p):
                    logger.info(f"  Download: {p}")

                if uploader.download_model(model_path, str(local_model_path), progress_cb):
                    logger.info(f"\nModel downloaded to: {local_model_path}")
                    uploader.close()
                    return True
                else:
                    logger.error("Model download failed")
                    uploader.close()
                    return False
            else:
                logger.warning("Training completed but no model path returned")
                uploader.close()
                return False

        elif current_status in ("FAILED", "ERROR", "CANCELLED"):
            error = status.get("error", "Unknown error")
            logger.error(f"\nTraining failed: {error}")
            uploader.close()
            return False

        time.sleep(poll_interval)

    logger.error(f"\nTraining timeout after {timeout_minutes} minutes")
    uploader.close()
    return False


# =============================================================================
# Main workflow (similar to test_edge_workflow.py but without frame extraction)
# =============================================================================

def run_retry_workflow(
    dataset_path: Path,
    repo_id: str,
    skip_training: bool = False,
    skip_upload: bool = False,
    download_only: bool = False,
    model_output_path: Path = None,
    timeout_minutes: int = 120,
) -> bool:
    """
    Run the edge upload retry workflow.

    Args:
        dataset_path: Path to dataset with raw images
        repo_id: Repository ID for the dataset
        skip_training: If True, skip training (just upload + encode)
        skip_upload: If True, skip upload and encoding notification
        download_only: If True, skip upload and training trigger, just download
        model_output_path: Path to save model (default: dataset_path/model)
        timeout_minutes: Training timeout in minutes (default: 120)

    Returns:
        True if workflow completed successfully
    """
    # download_only implies skip_upload and we definitely want Step 4
    if download_only:
        skip_upload = True
        skip_training = False # We want the "Wait and Download" step

    # Default model output to dataset_path/model
    if model_output_path is None:
        model_output_path = dataset_path / "model"

    logger.info("\n" + "=" * 60)
    logger.info("Edge Upload Workflow")
    logger.info("=" * 60)
    logger.info(f"Dataset:     {dataset_path}")
    logger.info(f"Repo ID:     {repo_id}")
    logger.info(f"Upload:      {'skip' if skip_upload else 'enabled'}")
    logger.info(f"Training:    {'skip' if skip_training or download_only else 'enabled'}")
    if not skip_training:
        logger.info(f"Model out:   {model_output_path}")
        logger.info(f"Timeout:     {timeout_minutes} minutes")
    logger.info("=" * 60)

    # Validate dataset (only if upload is enabled)
    if not skip_upload:
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
    encode_ok = True
    if not skip_upload:
        logger.info("\n[Step 1/4] Uploading to edge server...")
        if not upload_to_edge(dataset_path, repo_id):
            logger.error("Upload failed")
            return False

        # Step 2: Notify edge server to encode
        logger.info("\n[Step 2/4] Triggering encoding on edge server...")
        encode_ok = notify_edge_and_encode(repo_id)
        if not encode_ok:
            logger.error("Encoding notification failed")
    else:
        logger.info("\n[Step 1 & 2/4] Skipping upload and encoding notification")

    # Step 3: Trigger training
    train_ok = True
    transaction_id = "MANUAL_RESUME" # Placeholder for manual resume
    if not skip_training and not download_only:
        logger.info("\n[Step 3/4] Triggering cloud training...")
        train_ok, transaction_id = trigger_training(repo_id)
        if not train_ok:
            logger.error("Training trigger failed")
    elif download_only:
        logger.info("\n[Step 3/4] Skipping training trigger (download only mode)")
    else:
        logger.info("\n[Step 3/4] Skipping training (--skip-training)")

    # Step 4: Wait for training and download model
    download_ok = True
    if not skip_training and train_ok:
        logger.info("\n[Step 4/4] Waiting for training and downloading model...")
        download_ok = wait_training_and_download(
            repo_id=repo_id,
            transaction_id=transaction_id if transaction_id else "UNKNOWN",
            local_model_path=model_output_path,
            timeout_minutes=timeout_minutes,
        )
        if not download_ok:
            logger.error("Training/download failed")
    else:
        logger.info("\n[Step 4/4] Skipping (training not triggered)")

    # Report final status
    from operating_platform.core.edge_upload import EdgeConfig
    config = EdgeConfig.from_env()
    upload_path = config.get_upload_path(repo_id)

    logger.info("\n" + "=" * 60)
    if encode_ok and train_ok and download_ok:
        logger.info("WORKFLOW COMPLETED SUCCESSFULLY")
        logger.info("=" * 60)
        logger.info(f"Repo ID:     {repo_id}")
        logger.info(f"API User:    {config.api_username}")
        logger.info(f"Edge path:   {upload_path}/")
        if not skip_training:
            logger.info(f"Model path:  {model_output_path}")
        return True
    elif encode_ok and skip_training:
        logger.info("UPLOAD COMPLETED (training skipped)")
        logger.info("=" * 60)
        logger.info(f"Repo ID:     {repo_id}")
        logger.info(f"API User:    {config.api_username}")
        logger.info(f"Edge path:   {upload_path}/")
        return True
    else:
        logger.error("WORKFLOW FAILED")
        logger.info("=" * 60)
        logger.info(f"Repo ID:     {repo_id}")
        logger.info(f"API User:    {config.api_username}")
        logger.info(f"Edge path:   {upload_path}/")
        if not encode_ok:
            logger.error("  - Encoding step failed")
        if not train_ok:
            logger.error("  - Training trigger failed")
        if not download_ok and not skip_training:
            logger.error("  - Model download failed")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Edge upload for raw image datasets - upload, encode, train, and download model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Recommended: Use edge.sh wrapper for easier invocation:
    scripts/edge.sh -u <username> -p <password> -d <dataset_path> [options]

Direct usage (set API_USERNAME and API_PASSWORD environment variables):
    # Full workflow: upload -> encode -> train -> download model
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id

    # Upload only (skip training)
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --dataset ~/DoRobot/dataset/my_repo_id --skip-training

    # Test connection
    API_USERNAME=alice API_PASSWORD=alice123 \\
        python scripts/edge_encode.py --test-connection

Output:
    By default, trained model is downloaded to: {dataset_path}/model/

Notes:
    - API_USERNAME and API_PASSWORD are required for multi-user isolation
    - Script will NOT exit until training completes and model is downloaded
    - Multiple users can run in parallel (isolated by username)
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
        "--skip-upload",
        action="store_true",
        help="Skip upload and encoding notification",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Skip upload and training trigger, just download model",
    )
    parser.add_argument(
        "--model-output",
        type=Path,
        help="Path to save trained model (default: {dataset_path}/model/)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Training timeout in minutes (default: 120)",
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

    # Resolve model output path
    model_output_path = None
    if args.model_output:
        model_output_path = args.model_output.expanduser().resolve()

    # Run workflow
    success = run_retry_workflow(
        dataset_path=dataset_path,
        repo_id=repo_id,
        skip_training=args.skip_training,
        skip_upload=args.skip_upload,
        download_only=args.download_only,
        model_output_path=model_output_path,
        timeout_minutes=args.timeout,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
