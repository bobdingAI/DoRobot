#!/usr/bin/env python3
"""
Edge Upload module for DoRobot.

Handles uploading dataset to local edge server (API server) via SFTP/rsync.
The edge server then encodes videos and uploads to cloud for training.

This is CLOUD_OFFLOAD=2 mode - faster than direct cloud upload because:
1. LAN transfer is ~50x faster than WAN
2. Client doesn't wait for encoding
3. Edge server has better CPU for encoding

Usage:
    from operating_platform.core.edge_upload import EdgeUploader

    uploader = EdgeUploader()
    if uploader.test_connection():
        uploader.sync_dataset("/path/to/dataset", "repo_id")
        uploader.trigger_training("repo_id")

Supports both SSH key and password authentication (password via paramiko).
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

# Optional paramiko import for password authentication
try:
    import paramiko
    PARAMIKO_AVAILABLE = True
except ImportError:
    PARAMIKO_AVAILABLE = False

# Default configuration - can be overridden via environment variables
DEFAULT_EDGE_HOST = os.environ.get("EDGE_SERVER_HOST", "127.0.0.1")
DEFAULT_EDGE_USER = os.environ.get("EDGE_SERVER_USER", "nupylot")
DEFAULT_EDGE_PASSWORD = os.environ.get("EDGE_SERVER_PASSWORD", "")
DEFAULT_EDGE_PORT = int(os.environ.get("EDGE_SERVER_PORT", "22"))
DEFAULT_EDGE_PATH = os.environ.get("EDGE_SERVER_PATH", "/uploaded_data")
# API URL defaults to same host as edge server
DEFAULT_EDGE_API_URL = os.environ.get("API_BASE_URL", os.environ.get("EDGE_API_URL", "http://127.0.0.1:8000"))
# API username for multi-user upload path isolation
DEFAULT_API_USERNAME = os.environ.get("API_USERNAME", "default")
# API password for cloud training authentication (passed to edge server for cloud upload)
DEFAULT_API_PASSWORD = os.environ.get("API_PASSWORD", "")


def log(message: str):
    """Print timestamped log messages"""
    logging.info(f"[EdgeUpload] {message}")


def modify_config_device(local_model_path: str, from_device: str = "npu", to_device: str = "cuda") -> bool:
    """
    Modify config.json device setting after model download.
    Borrowed from train.py for consistency.

    Args:
        local_model_path: Path to downloaded model directory
        from_device: Original device in config (default: npu)
        to_device: Target device to set (default: cuda)

    Returns:
        True if successful, False otherwise
    """
    import json
    config_path = Path(local_model_path) / "config.json"

    if not config_path.exists():
        log(f"config.json not found at {config_path}")
        return False

    try:
        log(f"Modifying config.json device from '{from_device}' to '{to_device}'...")

        # Read the config file
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # Check if device field exists
        if 'device' not in config_data:
            log("'device' field not found in config.json")
            return False

        original_device = config_data.get('device', 'unknown')
        log(f"Current device: {original_device}")

        # Modify the device field
        config_data['device'] = to_device

        # Write back to file
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)

        log(f"Successfully updated device from '{original_device}' to '{to_device}' in config.json")
        return True

    except Exception as e:
        log(f"Failed to modify config.json: {e}")
        return False


@dataclass
class EdgeConfig:
    """Edge server configuration"""
    host: str = DEFAULT_EDGE_HOST
    user: str = DEFAULT_EDGE_USER
    password: str = DEFAULT_EDGE_PASSWORD  # Password for SSH (uses paramiko)
    port: int = DEFAULT_EDGE_PORT
    remote_path: str = DEFAULT_EDGE_PATH
    api_url: str = DEFAULT_EDGE_API_URL
    api_username: str = DEFAULT_API_USERNAME  # API username for path isolation
    api_password: str = DEFAULT_API_PASSWORD  # API password for cloud training auth
    ssh_key: Optional[str] = None  # Path to SSH private key (alternative to password)

    @classmethod
    def from_env(cls) -> "EdgeConfig":
        """Create config from environment variables"""
        return cls(
            host=os.environ.get("EDGE_SERVER_HOST", DEFAULT_EDGE_HOST),
            user=os.environ.get("EDGE_SERVER_USER", DEFAULT_EDGE_USER),
            password=os.environ.get("EDGE_SERVER_PASSWORD", DEFAULT_EDGE_PASSWORD),
            port=int(os.environ.get("EDGE_SERVER_PORT", str(DEFAULT_EDGE_PORT))),
            remote_path=os.environ.get("EDGE_SERVER_PATH", DEFAULT_EDGE_PATH),
            api_url=os.environ.get("API_BASE_URL", os.environ.get("EDGE_API_URL", DEFAULT_EDGE_API_URL)),
            api_username=os.environ.get("API_USERNAME", DEFAULT_API_USERNAME),
            api_password=os.environ.get("API_PASSWORD", DEFAULT_API_PASSWORD),
            ssh_key=os.environ.get("EDGE_SERVER_KEY"),
        )

    def get_upload_path(self, repo_id: str) -> str:
        """Get full upload path including username for isolation: {remote_path}/{api_username}/{repo_id}"""
        return f"{self.remote_path}/{self.api_username}/{repo_id}"


class EdgeUploader:
    """
    Handles uploading dataset to edge server via SFTP/rsync.

    Workflow:
    1. Test SSH connection to edge server
    2. Sync dataset directory to edge server (SFTP for password, rsync for key)
    3. Notify edge server to start encoding + cloud upload
    4. Optionally wait for training completion

    Authentication:
    - Password: Uses paramiko SFTP (recommended for simplicity)
    - SSH Key: Uses rsync over SSH (faster for large datasets)
    """

    def __init__(self, config: Optional[EdgeConfig] = None):
        self.config = config or EdgeConfig.from_env()
        self._connected = False
        self._ssh_client: Optional["paramiko.SSHClient"] = None
        self._sftp: Optional["paramiko.SFTPClient"] = None

    def _use_paramiko(self) -> bool:
        """Check if we should use paramiko (password auth) or rsync (key auth)"""
        return bool(self.config.password and PARAMIKO_AVAILABLE)

    def _get_ssh_client(self) -> "paramiko.SSHClient":
        """Get or create paramiko SSH client"""
        if self._ssh_client is not None and self._ssh_client.get_transport() and self._ssh_client.get_transport().is_active():
            return self._ssh_client

        if not PARAMIKO_AVAILABLE:
            raise RuntimeError("paramiko not available - install with: pip install paramiko")

        log(f"Connecting via paramiko to {self.config.user}@{self.config.host}:{self.config.port}...")

        self._ssh_client = paramiko.SSHClient()
        self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self._ssh_client.connect(
                hostname=self.config.host,
                port=self.config.port,
                username=self.config.user,
                password=self.config.password,
                timeout=30,
                allow_agent=False,
                look_for_keys=False,
            )
            log("Paramiko SSH connection established")
            return self._ssh_client
        except Exception as e:
            log(f"Paramiko connection failed: {e}")
            self._ssh_client = None
            raise

    def _get_sftp(self) -> "paramiko.SFTPClient":
        """Get or create SFTP client"""
        if self._sftp is not None:
            try:
                self._sftp.stat(".")  # Test if still valid
                return self._sftp
            except Exception:
                self._sftp = None

        ssh = self._get_ssh_client()
        self._sftp = ssh.open_sftp()
        return self._sftp

    def _exec_remote_command(self, command: str) -> tuple[int, str, str]:
        """Execute command on remote server via paramiko"""
        ssh = self._get_ssh_client()
        stdin, stdout, stderr = ssh.exec_command(command, timeout=60)
        exit_code = stdout.channel.recv_exit_status()
        return exit_code, stdout.read().decode(), stderr.read().decode()

    def close(self):
        """Close SSH/SFTP connections"""
        if self._sftp:
            try:
                self._sftp.close()
            except Exception:
                pass
            self._sftp = None

        if self._ssh_client:
            try:
                self._ssh_client.close()
            except Exception:
                pass
            self._ssh_client = None

    def test_connection(self, quick_test: bool = False) -> bool:
        """
        Test SSH connection to edge server.

        Args:
            quick_test: If True, use shorter timeouts (5s) for startup checks.
                       If False, use normal timeouts for actual operations.
        """
        timeout = 5 if quick_test else 30
        log(f"Testing connection to {self.config.user}@{self.config.host}:{self.config.port} (timeout={timeout}s)...")

        # Use paramiko if password is set
        if self._use_paramiko():
            try:
                # For quick test, create a new client with short timeout
                if quick_test:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    ssh.connect(
                        hostname=self.config.host,
                        port=self.config.port,
                        username=self.config.user,
                        password=self.config.password,
                        timeout=timeout,
                        allow_agent=False,
                        look_for_keys=False,
                    )
                    stdin, stdout, stderr = ssh.exec_command("echo SSH_OK", timeout=timeout)
                    exit_code = stdout.channel.recv_exit_status()
                    stdout_str = stdout.read().decode()
                    stderr_str = stderr.read().decode()
                    ssh.close()
                else:
                    exit_code, stdout_str, stderr_str = self._exec_remote_command("echo SSH_OK")

                if exit_code == 0 and "SSH_OK" in stdout_str:
                    log("SSH connection successful (paramiko)")
                    self._connected = True
                    return True
                else:
                    log(f"SSH connection failed: {stderr_str}")
                    return False
            except Exception as e:
                log(f"SSH connection error: {e}")
                return False

        # Fall back to subprocess SSH
        ssh_cmd = self._build_ssh_cmd(["echo", "SSH OK"])

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0 and "SSH OK" in result.stdout:
                log("SSH connection successful")
                self._connected = True
                return True
            else:
                log(f"SSH connection failed: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            log(f"SSH connection timeout ({timeout}s)")
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

        # Use paramiko if password is set
        if self._use_paramiko():
            try:
                exit_code, stdout, stderr = self._exec_remote_command(f"mkdir -p '{remote_path}'")
                if exit_code == 0:
                    log("Remote directory created (paramiko)")
                    return True
                else:
                    log(f"Failed to create directory: {stderr}")
                    return False
            except Exception as e:
                log(f"Error creating remote directory: {e}")
                return False

        # Fall back to subprocess SSH
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

    def clear_remote_directory(self, subpath: str = "") -> bool:
        """
        Clear (remove all contents of) a directory on edge server.
        The directory itself is preserved, only its contents are deleted.

        Args:
            subpath: Subdirectory path relative to remote_path

        Returns:
            True if successful
        """
        remote_path = self.config.remote_path
        if subpath:
            remote_path = f"{remote_path}/{subpath}"

        log(f"Clearing remote directory: {remote_path}")

        # Use paramiko if password is set
        if self._use_paramiko():
            try:
                # Remove all contents but keep the directory
                # Using rm -rf with glob to clear contents, then recreate empty dir
                exit_code, stdout, stderr = self._exec_remote_command(
                    f"rm -rf '{remote_path}'/* '{remote_path}'/.[!.]* 2>/dev/null; mkdir -p '{remote_path}'"
                )
                if exit_code == 0:
                    log("Remote directory cleared (paramiko)")
                    return True
                else:
                    # rm might fail if directory is empty (no matches), but mkdir should succeed
                    # Check if directory exists and is accessible
                    check_code, _, _ = self._exec_remote_command(f"test -d '{remote_path}'")
                    if check_code == 0:
                        log("Remote directory cleared (was empty or cleared)")
                        return True
                    log(f"Failed to clear directory: {stderr}")
                    return False
            except Exception as e:
                log(f"Error clearing remote directory: {e}")
                return False

        # Fall back to subprocess SSH
        ssh_cmd = self._build_ssh_cmd([
            "sh", "-c",
            f"rm -rf '{remote_path}'/* '{remote_path}'/.[!.]* 2>/dev/null; mkdir -p '{remote_path}'"
        ])

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Check if directory exists after clearing
            check_cmd = self._build_ssh_cmd(["test", "-d", remote_path])
            check_result = subprocess.run(check_cmd, capture_output=True, timeout=10)

            if check_result.returncode == 0:
                log("Remote directory cleared")
                return True
            else:
                log(f"Failed to clear directory: {result.stderr}")
                return False

        except Exception as e:
            log(f"Error clearing remote directory: {e}")
            return False

    def _sftp_upload_directory(
        self,
        local_dir: str,
        remote_dir: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Upload a directory recursively via SFTP (paramiko)"""
        sftp = self._get_sftp()
        local_path = Path(local_dir)

        # Count total files for progress
        all_files = list(local_path.rglob("*"))
        total_files = len([f for f in all_files if f.is_file()])
        uploaded = 0

        log(f"Uploading {total_files} files via SFTP...")

        for item in all_files:
            rel_path = item.relative_to(local_path)
            remote_path = f"{remote_dir}/{rel_path}"

            if item.is_dir():
                # Create remote directory
                try:
                    sftp.stat(remote_path)
                except FileNotFoundError:
                    sftp.mkdir(remote_path)
            else:
                # Upload file
                try:
                    sftp.put(str(item), remote_path)
                    uploaded += 1
                    if progress_callback and uploaded % 10 == 0:
                        progress = f"{uploaded}/{total_files} files ({100*uploaded//total_files}%)"
                        progress_callback(progress)
                except Exception as e:
                    log(f"Failed to upload {item}: {e}")
                    return False

        if progress_callback:
            progress_callback(f"{total_files}/{total_files} files (100%)")

        return True

    def sync_dataset(
        self,
        local_path: str,
        repo_id: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Sync dataset to edge server using SFTP (password) or rsync (key).

        Args:
            local_path: Local dataset path
            repo_id: Dataset repository ID (used as subdirectory on edge)
            progress_callback: Optional callback for progress updates

        Returns:
            True if sync successful

        Note:
            Upload path is: {remote_path}/{api_username}/{repo_id}/
            This isolates uploads by user to avoid conflicts on shared API servers.
        """
        # Get full upload path with username isolation
        upload_path = self.config.get_upload_path(repo_id)
        upload_subpath = f"{self.config.api_username}/{repo_id}"

        log(f"Syncing dataset to edge server...")
        log(f"  Local: {local_path}")
        log(f"  Remote: {self.config.user}@{self.config.host}:{upload_path}/")
        log(f"  User: {self.config.api_username}")

        # Create remote directory (includes username subdirectory)
        if not self.create_remote_directory(upload_subpath):
            return False

        # Clear remote directory before upload to avoid leftover files
        if not self.clear_remote_directory(upload_subpath):
            log("Warning: Failed to clear remote directory, continuing with upload...")

        start_time = time.time()
        remote_path = upload_path

        # Use SFTP if password authentication (paramiko)
        if self._use_paramiko():
            log("Using SFTP (paramiko) for upload...")
            try:
                success = self._sftp_upload_directory(local_path, remote_path, progress_callback)
                elapsed = time.time() - start_time
                if success:
                    log(f"SFTP sync completed in {elapsed:.1f}s")
                    return True
                else:
                    log("SFTP sync failed")
                    return False
            except Exception as e:
                log(f"SFTP sync error: {e}")
                return False

        # Fall back to rsync for key-based auth
        rsync_cmd = self._build_rsync_cmd(local_path, upload_subpath)

        log(f"Running: {' '.join(rsync_cmd[:5])}...")  # Don't log full command (may have secrets)

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

        Note:
            Dataset path sent to API is: {remote_path}/{api_username}/{repo_id}
            Cloud credentials are passed so edge server can upload to cloud training server.
        """
        upload_path = self.config.get_upload_path(repo_id)
        log(f"Notifying edge server: upload complete for {repo_id}")
        log(f"  Dataset path: {upload_path}")

        # Build request payload with cloud credentials for edge server to use
        payload = {
            "repo_id": repo_id,
            "dataset_path": upload_path,
            "username": self.config.api_username,
        }

        # Add cloud credentials if available (for edge server to forward to cloud)
        if self.config.api_password:
            payload["cloud_username"] = self.config.api_username
            payload["cloud_password"] = self.config.api_password
            log(f"  Cloud credentials: included for {self.config.api_username}")

        try:
            response = requests.post(
                f"{self.config.api_url}/edge/upload-complete",
                json=payload,
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

    def trigger_training(self, repo_id: str) -> tuple[bool, Optional[str]]:
        """
        Trigger cloud training via edge server.

        Returns:
            (success, transaction_id) tuple

        Note:
            Cloud credentials are passed so edge server can authenticate with cloud.
        """
        log(f"Triggering cloud training for {repo_id}")

        # Build request payload with cloud credentials
        payload = {
            "repo_id": repo_id,
            "username": self.config.api_username,
        }

        # Add cloud credentials if available (for edge server to forward to cloud)
        if self.config.api_password:
            payload["cloud_username"] = self.config.api_username
            payload["cloud_password"] = self.config.api_password

        try:
            response = requests.post(
                f"{self.config.api_url}/edge/train",
                json=payload,
                timeout=30,
            )

            if response.status_code == 200:
                data = response.json()
                transaction_id = data.get("transaction_id")
                log(f"Training triggered: {data.get('message', 'OK')}")
                if transaction_id:
                    log(f"Transaction ID: {transaction_id}")
                return True, transaction_id
            else:
                log(f"Failed to trigger training: {response.status_code}")
                return False, None

        except Exception as e:
            log(f"Error triggering training: {e}")
            return False, None

    def download_model(
        self,
        remote_model_path: str,
        local_output_path: str,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Download trained model from edge server via SFTP.

        Args:
            remote_model_path: Path to model on edge server
            local_output_path: Local path to save model
            progress_callback: Optional callback for progress updates

        Returns:
            True if download successful
        """
        log(f"Downloading model from edge server...")
        log(f"  Remote: {self.config.user}@{self.config.host}:{remote_model_path}")
        log(f"  Local:  {local_output_path}")

        try:
            # Create local directory
            Path(local_output_path).mkdir(parents=True, exist_ok=True)

            sftp = self._get_sftp()
            downloaded_files = 0

            def download_recursive(remote_dir: str, local_dir: str):
                nonlocal downloaded_files
                Path(local_dir).mkdir(parents=True, exist_ok=True)

                try:
                    for entry in sftp.listdir_attr(remote_dir):
                        remote_path = f"{remote_dir}/{entry.filename}"
                        local_path = Path(local_dir) / entry.filename

                        if entry.st_mode & 0o40000:  # Is directory
                            download_recursive(remote_path, str(local_path))
                        else:
                            sftp.get(remote_path, str(local_path))
                            downloaded_files += 1
                            if downloaded_files % 10 == 0:
                                progress = f"{downloaded_files} files downloaded"
                                log(f"  {progress}")
                                if progress_callback:
                                    progress_callback(progress)
                except Exception as e:
                    log(f"Error downloading from {remote_dir}: {e}")
                    raise

            download_recursive(remote_model_path, local_output_path)

            log(f"Model download completed: {downloaded_files} files")
            if progress_callback:
                progress_callback(f"{downloaded_files} files (complete)")
            return downloaded_files > 0

        except Exception as e:
            log(f"Download error: {e}")
            import traceback
            traceback.print_exc()
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
            elif current_status in ("FAILED", "ERROR", "UPLOAD_FAILED", "ENCODING_FAILED", "TRAINING_FAILED"):
                error = status.get("error", progress or "Unknown error")
                log(f"Training failed with status '{current_status}': {error}")
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
                success, _ = uploader.trigger_training(self.repo_id)
                if not success:
                    log("Warning: Failed to trigger training")

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
    timeout_minutes: int = 120,
    model_output_path: Optional[str] = None,
    status_callback: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """
    Convenience function to run edge upload workflow.

    Args:
        dataset_path: Local path to dataset
        repo_id: Dataset repository ID
        trigger_training: Whether to trigger cloud training after upload
        wait_for_training: Whether to wait for training completion
        timeout_minutes: Training timeout in minutes (default: 120)
        model_output_path: Local path to download model after training (optional)
        status_callback: Optional callback(status, progress)

    Returns:
        True if upload (and optionally training + model download) successful
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
        success, transaction_id = uploader.trigger_training(repo_id)
        if not success:
            log("Failed to trigger training")
            return False

        # Wait for training if requested
        if wait_for_training:
            success, remote_model_path = uploader.poll_training_status(
                repo_id,
                timeout_minutes=timeout_minutes,
                status_callback=status_callback,
            )

            if not success:
                log("Training failed or timed out")
                return False

            # Download model if output path specified and training succeeded
            if model_output_path and remote_model_path:
                log(f"Downloading model to {model_output_path}...")
                if status_callback:
                    status_callback("DOWNLOADING_MODEL", "Starting download...")

                download_success = uploader.download_model(
                    remote_model_path,
                    model_output_path,
                    progress_callback=lambda p: status_callback("DOWNLOADING_MODEL", p) if status_callback else None
                )

                if not download_success:
                    log("Model download failed")
                    return False

                log(f"Model downloaded successfully to: {model_output_path}")

                # Post-processing: modify config.json device setting for local inference
                log("Post-download processing: updating config.json device setting...")
                if not modify_config_device(model_output_path, from_device="npu", to_device="cuda"):
                    log("Warning: Failed to update config.json device setting, but continuing...")

            return True

    return True
