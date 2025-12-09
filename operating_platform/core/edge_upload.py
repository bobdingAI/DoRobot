#!/usr/bin/env python3
"""
Edge Upload module for DoRobot.

Handles uploading dataset to local edge server (API server) via rsync.
The edge server then encodes videos and uploads to cloud for training.

This is CLOUD_OFFLOAD=2 mode - faster than direct cloud upload because:
1. LAN transfer is ~50x faster than WAN
2. Client doesn't wait for encoding
3. Edge server has better CPU for encoding

Usage:
    from operating_platform.core.edge_upload import EdgeUploader

    uploader = EdgeUploader()
    if uploader.connect():
        uploader.sync_dataset("/path/to/dataset")
        uploader.trigger_training()
"""

import os
import subprocess
import logging
import time
import threading
import requests
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable

# Default configuration - can be overridden via environment variables
DEFAULT_EDGE_HOST = os.environ.get("EDGE_SERVER_HOST", "192.168.1.100")
DEFAULT_EDGE_USER = os.environ.get("EDGE_SERVER_USER", "dorobot")
DEFAULT_EDGE_PORT = int(os.environ.get("EDGE_SERVER_PORT", "22"))
DEFAULT_EDGE_PATH = os.environ.get("EDGE_SERVER_PATH", "/data/dorobot/uploads")
DEFAULT_EDGE_API_URL = os.environ.get("EDGE_API_URL", "http://192.168.1.100:8000")


def log(message: str):
    """Print timestamped log messages"""
    logging.info(f"[EdgeUpload] {message}")


@dataclass
class EdgeConfig:
    """Edge server configuration"""
    host: str = DEFAULT_EDGE_HOST
    user: str = DEFAULT_EDGE_USER
    port: int = DEFAULT_EDGE_PORT
    remote_path: str = DEFAULT_EDGE_PATH
    api_url: str = DEFAULT_EDGE_API_URL
    ssh_key: Optional[str] = None  # Path to SSH private key

    @classmethod
    def from_env(cls) -> "EdgeConfig":
        """Create config from environment variables"""
        return cls(
            host=os.environ.get("EDGE_SERVER_HOST", DEFAULT_EDGE_HOST),
            user=os.environ.get("EDGE_SERVER_USER", DEFAULT_EDGE_USER),
            port=int(os.environ.get("EDGE_SERVER_PORT", str(DEFAULT_EDGE_PORT))),
            remote_path=os.environ.get("EDGE_SERVER_PATH", DEFAULT_EDGE_PATH),
            api_url=os.environ.get("EDGE_API_URL", DEFAULT_EDGE_API_URL),
            ssh_key=os.environ.get("EDGE_SERVER_KEY"),
        )


class EdgeUploader:
    """
    Handles uploading dataset to edge server via rsync.

    Workflow:
    1. Test SSH connection to edge server
    2. rsync dataset directory to edge server
    3. Notify edge server to start encoding + cloud upload
    4. Optionally wait for training completion
    """

    def __init__(self, config: Optional[EdgeConfig] = None):
        self.config = config or EdgeConfig.from_env()
        self._connected = False

    def test_connection(self) -> bool:
        """Test SSH connection to edge server"""
        log(f"Testing connection to {self.config.user}@{self.config.host}:{self.config.port}...")

        ssh_cmd = self._build_ssh_cmd(["echo", "SSH OK"])

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and "SSH OK" in result.stdout:
                log("SSH connection successful")
                self._connected = True
                return True
            else:
                log(f"SSH connection failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            log("SSH connection timeout")
            return False
        except Exception as e:
            log(f"SSH connection error: {e}")
            return False

    def _build_ssh_cmd(self, remote_cmd: list[str]) -> list[str]:
        """Build SSH command with proper options"""
        cmd = ["ssh"]

        # Add SSH key if specified
        if self.config.ssh_key:
            key_path = os.path.expanduser(self.config.ssh_key)
            if os.path.exists(key_path):
                cmd.extend(["-i", key_path])

        # Add port
        cmd.extend(["-p", str(self.config.port)])

        # Add options for non-interactive use
        cmd.extend([
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
        ])

        # Add user@host
        cmd.append(f"{self.config.user}@{self.config.host}")

        # Add remote command
        cmd.extend(remote_cmd)

        return cmd

    def _build_rsync_cmd(self, local_path: str, remote_subpath: str = "") -> list[str]:
        """Build rsync command"""
        cmd = [
            "rsync",
            "-avz",  # archive, verbose, compress
            "--progress",
            "--partial",  # Keep partial files for resume
            "--delete",  # Delete files on dest that don't exist on source
        ]

        # Add SSH options
        ssh_opts = f"ssh -p {self.config.port}"
        ssh_opts += " -o StrictHostKeyChecking=no"
        ssh_opts += " -o UserKnownHostsFile=/dev/null"

        if self.config.ssh_key:
            key_path = os.path.expanduser(self.config.ssh_key)
            if os.path.exists(key_path):
                ssh_opts += f" -i {key_path}"

        cmd.extend(["-e", ssh_opts])

        # Source path (ensure trailing slash for directory contents)
        local_path = str(local_path).rstrip("/") + "/"
        cmd.append(local_path)

        # Destination path
        remote_path = self.config.remote_path
        if remote_subpath:
            remote_path = f"{remote_path}/{remote_subpath}"
        dest = f"{self.config.user}@{self.config.host}:{remote_path}/"
        cmd.append(dest)

        return cmd

    def create_remote_directory(self, subpath: str = "") -> bool:
        """Create directory on edge server"""
        remote_path = self.config.remote_path
        if subpath:
            remote_path = f"{remote_path}/{subpath}"

        log(f"Creating remote directory: {remote_path}")

        ssh_cmd = self._build_ssh_cmd(["mkdir", "-p", remote_path])

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                log("Remote directory created")
                return True
            else:
                log(f"Failed to create directory: {result.stderr}")
                return False

        except Exception as e:
            log(f"Error creating remote directory: {e}")
            return False

    def sync_dataset(
        self,
        local_path: str,
        repo_id: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Sync dataset to edge server using rsync.

        Args:
            local_path: Local dataset path
            repo_id: Dataset repository ID (used as subdirectory on edge)
            progress_callback: Optional callback for progress updates

        Returns:
            True if sync successful
        """
        log(f"Syncing dataset to edge server...")
        log(f"  Local: {local_path}")
        log(f"  Remote: {self.config.user}@{self.config.host}:{self.config.remote_path}/{repo_id}/")

        # Create remote directory
        if not self.create_remote_directory(repo_id):
            return False

        # Build rsync command
        rsync_cmd = self._build_rsync_cmd(local_path, repo_id)

        log(f"Running: {' '.join(rsync_cmd[:5])}...")  # Don't log full command (may have secrets)

        start_time = time.time()

        try:
            # Run rsync with real-time output
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            last_progress = ""
            for line in process.stdout:
                line = line.strip()
                if line:
                    # Parse progress from rsync output
                    if "%" in line:
                        last_progress = line
                        if progress_callback:
                            progress_callback(line)
                    elif "sent" in line.lower() or "total" in line.lower():
                        log(line)

            process.wait()

            elapsed = time.time() - start_time

            if process.returncode == 0:
                log(f"Sync completed in {elapsed:.1f}s")
                return True
            else:
                log(f"Sync failed with exit code {process.returncode}")
                return False

        except Exception as e:
            log(f"Sync error: {e}")
            return False

    def notify_upload_complete(self, repo_id: str) -> bool:
        """
        Notify edge server that upload is complete.
        This triggers encoding and cloud upload.
        """
        log(f"Notifying edge server: upload complete for {repo_id}")

        try:
            response = requests.post(
                f"{self.config.api_url}/edge/upload-complete",
                json={
                    "repo_id": repo_id,
                    "dataset_path": f"{self.config.remote_path}/{repo_id}",
                },
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                log(f"Edge server acknowledged: {data.get('message', 'OK')}")
                return True
            else:
                log(f"Edge server error: {response.status_code} - {response.text}")
                return False

        except requests.exceptions.ConnectionError:
            log(f"Cannot connect to edge API at {self.config.api_url}")
            return False
        except Exception as e:
            log(f"Error notifying edge server: {e}")
            return False

    def get_status(self, repo_id: str) -> dict:
        """Get encoding/upload status from edge server"""
        try:
            response = requests.get(
                f"{self.config.api_url}/edge/status/{repo_id}",
                timeout=30,
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {"status": "UNKNOWN", "error": response.text}

        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def trigger_training(self, repo_id: str) -> bool:
        """Trigger cloud training via edge server"""
        log(f"Triggering cloud training for {repo_id}")

        try:
            response = requests.post(
                f"{self.config.api_url}/edge/train",
                json={"repo_id": repo_id},
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                log(f"Training triggered: {data.get('message', 'OK')}")
                return True
            else:
                log(f"Failed to trigger training: {response.status_code}")
                return False

        except Exception as e:
            log(f"Error triggering training: {e}")
            return False

    def poll_training_status(
        self,
        repo_id: str,
        timeout_minutes: int = 60,
        poll_interval: int = 10,
        status_callback: Optional[Callable[[str, str], None]] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Poll training status until completion.

        Returns:
            (success, model_path) tuple
        """
        log(f"Monitoring training (timeout: {timeout_minutes} min)...")

        start_time = time.time()
        timeout_seconds = timeout_minutes * 60

        while (time.time() - start_time) < timeout_seconds:
            status = self.get_status(repo_id)

            current_status = status.get("status", "UNKNOWN")
            progress = status.get("progress", "")

            if status_callback:
                status_callback(current_status, progress)
            else:
                log(f"Status: {current_status}, Progress: {progress}")

            if current_status == "COMPLETED":
                model_path = status.get("model_path")
                log(f"Training completed! Model path: {model_path}")
                return True, model_path
            elif current_status in ("FAILED", "ERROR"):
                error = status.get("error", "Unknown error")
                log(f"Training failed: {error}")
                return False, None

            time.sleep(poll_interval)

        log("Training monitoring timeout")
        return False, None


class EdgeUploadThread(threading.Thread):
    """
    Background thread for edge upload.
    Allows recording to continue while upload happens.
    """

    def __init__(
        self,
        local_path: str,
        repo_id: str,
        config: Optional[EdgeConfig] = None,
        trigger_training: bool = True,
    ):
        super().__init__(daemon=True)
        self.local_path = local_path
        self.repo_id = repo_id
        self.config = config
        self.trigger_training = trigger_training

        self.success = False
        self.error_message = None
        self.current_status = "INITIALIZING"
        self.current_progress = ""
        self.completed = threading.Event()

    def run(self):
        try:
            uploader = EdgeUploader(self.config)

            # Test connection
            self.current_status = "CONNECTING"
            if not uploader.test_connection():
                self.error_message = "Cannot connect to edge server"
                self.current_status = "FAILED"
                return

            # Sync dataset
            self.current_status = "UPLOADING"

            def progress_cb(progress: str):
                self.current_progress = progress

            if not uploader.sync_dataset(self.local_path, self.repo_id, progress_cb):
                self.error_message = "Dataset sync failed"
                self.current_status = "FAILED"
                return

            # Notify edge server
            self.current_status = "NOTIFYING"
            if not uploader.notify_upload_complete(self.repo_id):
                self.error_message = "Failed to notify edge server"
                self.current_status = "FAILED"
                return

            # Optionally trigger training
            if self.trigger_training:
                self.current_status = "TRIGGERING_TRAINING"
                uploader.trigger_training(self.repo_id)

            self.success = True
            self.current_status = "COMPLETED"

        except Exception as e:
            self.success = False
            self.error_message = str(e)
            self.current_status = "ERROR"
            log(f"Edge upload thread error: {e}")
        finally:
            self.completed.set()

    def wait_for_completion(self, timeout: float = None) -> bool:
        """Wait for upload to complete"""
        return self.completed.wait(timeout=timeout)

    def get_status(self) -> dict:
        """Get current upload status"""
        return {
            "status": self.current_status,
            "progress": self.current_progress,
            "success": self.success,
            "error": self.error_message,
            "completed": self.completed.is_set(),
        }


def run_edge_upload(
    dataset_path: str,
    repo_id: str,
    trigger_training: bool = True,
    wait_for_training: bool = False,
    timeout_minutes: int = 60,
    status_callback: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    Convenience function to run edge upload workflow.

    Args:
        dataset_path: Local path to dataset
        repo_id: Dataset repository ID
        trigger_training: Whether to trigger cloud training after upload
        wait_for_training: Whether to wait for training completion
        timeout_minutes: Training timeout in minutes
        status_callback: Optional callback(status, progress)

    Returns:
        True if upload (and optionally training) successful
    """
    uploader = EdgeUploader()

    # Test connection
    if not uploader.test_connection():
        log("Cannot connect to edge server")
        return False

    # Sync dataset
    def progress_cb(progress: str):
        if status_callback:
            status_callback("UPLOADING", progress)

    if not uploader.sync_dataset(dataset_path, repo_id, progress_cb):
        log("Dataset sync failed")
        return False

    # Notify edge server
    if not uploader.notify_upload_complete(repo_id):
        log("Failed to notify edge server")
        return False

    # Trigger training
    if trigger_training:
        if not uploader.trigger_training(repo_id):
            log("Failed to trigger training")
            return False

        # Wait for training if requested
        if wait_for_training:
            success, _ = uploader.poll_training_status(
                repo_id,
                timeout_minutes=timeout_minutes,
                status_callback=status_callback,
            )
            return success

    return True
