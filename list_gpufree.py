#!/usr/bin/env python3
"""
GPUFree Instance Manager
A modular library for managing GPU instances on gpufree.cn

Features:
- List instances
- Start instance (with SSH ready check)
- Stop instance

Status Codes:
- 3: Running (on)
- 5: Stopped (off)
"""

import requests
import json
import subprocess
import time
import sys
from datetime import datetime
from typing import Optional, Dict, List, Tuple

# API Configuration
BASE_URL = "https://www.gpufree.cn/api/v1"
BEARER_TOKEN = "eyJhbGciOiJSUzI1NiIsImtpZCI6Ijk4MmFmNWE1LTc2ZTAtNDZmMy1iOGEyLTdiZjZlYmIyNzdlNiIsInR5cCI6IkpXVCJ9.eyJhdWQiOlsiMm5UMUZBelViQWFVVlZtbXRNOXQ4dDNrZktxIl0sImNsaWVudF9pZCI6IjJuVDFGQXpVYkFhVVZWbW10TTl0OHQza2ZLcSIsImV4cCI6MTc2ODQ3MDExNCwiaWF0IjoxNzY1MDE0MTE4LCJpc3MiOiJodHRwczovL3d3dy5ncHVmcmVlLmNuIiwianRpIjoiNjU0MWRiYjItMjE0Zi00Y2VhLWE0ZTMtOTIxZWE2YmE5ZmFlIiwibmJmIjoxNzY1MDE0MTE4LCJzY29wZSI6Im9wZW5pZCBwcm9maWxlIG9mZmxpbmVfYWNjZXNzIGVtYWlsIHBob25lIHVzZXJfaW5mbyIsInN1YiI6IjYxMzI1NzYzODE4ODE1NDg5IiwidXNlcl9pbmZvIjp7ImlkX2NoZWNrZWQiOnRydWUsInd4X2JvdW5kIjpmYWxzZX19.LCZr_Ckax8WLtaNUUteNi7KVYu4yxfLU0tamV4V5doZtDRbGdcML9PhggkfdROs1SWtiwhINyS90bYCmXXCYkr_fXCxOKDMRGYccmzZsD0PksnDGl7xr5Um-GKWxAVm-TMaWvfApNZ9M7iyNz8tukvP7453ZhbfEWfax6DHFbZg0lb0wGInVgiQwLEPCA90YOhAfjrlNyJV58wk-R5RCJXNvKVFz3ZDZuJx41S71ETnQ9A-UErS1WUbB1ZkVQHOpUR0hkm34sdgCexxocF5QeR6-c0ie2HZzStpC2BbXl4fczjNZ2QNv-aLbQX_bMqC77pJ39X-58XnI6ClsbxvHMw"

# Status constants
STATUS_RUNNING = 3  # Instance is running (on)
STATUS_STOPPED = 5  # Instance is stopped (off)


class GPUFreeClient:
    """Client for GPUFree API operations"""

    def __init__(self, bearer_token: str = BEARER_TOKEN, base_url: str = BASE_URL):
        self.base_url = base_url
        self.headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": f"Bearer {bearer_token}",
            "content-type": "application/json"
        }

    def list_instances(self, page_no: int = 1, page_size: int = 50,
                       status: str = "", nick_name: str = "") -> Optional[Dict]:
        """
        List all GPU instances

        Args:
            page_no: Page number (default: 1)
            page_size: Number of items per page (default: 50)
            status: Filter by status (optional)
            nick_name: Filter by nickname (optional)

        Returns:
            dict: API response data or None if failed
        """
        url = f"{self.base_url}/jupyter/list_instance_pages"
        params = {
            "page_no": page_no,
            "page_size": page_size,
            "status": status,
            "nick_name": nick_name
        }

        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error listing instances: {e}")
            return None

    def get_instance_by_uuid(self, uuid: str) -> Optional[Dict]:
        """
        Get instance details by UUID

        Args:
            uuid: Instance UUID

        Returns:
            dict: Instance data or None if not found
        """
        result = self.list_instances(page_no=1, page_size=50)
        if result and result.get("code") == 200:
            instances = result.get("data", {}).get("dataList", [])
            for instance in instances:
                if instance.get("webide_instance_uuid") == uuid:
                    return instance
        return None

    def _send_instance_action(self, instance_id: int, instance_uuid: str,
                               action: str, start_mode: str = "gpu") -> Optional[Dict]:
        """
        Send action (start/stop) to instance

        Args:
            instance_id: Instance ID
            instance_uuid: Instance UUID
            action: Action to perform ("start" or "stop")
            start_mode: Start mode (default: "gpu")

        Returns:
            dict: API response or None if failed
        """
        url = f"{self.base_url}/inferring-api/webide/"
        payload = {
            "instance_id": instance_id,
            "instance_uuid": instance_uuid,
            "start_mode": start_mode,
            "action": action
        }

        try:
            response = requests.put(url, headers=self.headers, json=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Error {action} instance: {e}")
            return None

    def _check_ssh_ready(self, ssh_command: str, password: str,
                         timeout: int = 10) -> bool:
        """
        Check if SSH connection is ready

        Args:
            ssh_command: SSH command string
            password: SSH password
            timeout: Connection timeout in seconds

        Returns:
            bool: True if SSH is ready, False otherwise
        """
        # Parse SSH command
        parts = ssh_command.split()
        user_host = None
        port = "22"

        for i, part in enumerate(parts):
            if "@" in part:
                user_host = part
            if part == "-p" and i + 1 < len(parts):
                port = parts[i + 1]

        if not user_host:
            return False

        user, host = user_host.split("@")

        try:
            cmd = [
                "sshpass", "-p", password,
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=10",
                "-p", port,
                f"{user}@{host}",
                "echo 'SSH_SUCCESS'"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
            return result.returncode == 0 and "SSH_SUCCESS" in result.stdout

        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False

    def start_instance(self, instance_id: int, instance_uuid: str,
                       wait_for_ssh: bool = True, max_retries: int = 30,
                       retry_interval: int = 10, start_mode: str = "gpu") -> Tuple[bool, Optional[str]]:
        """
        Start a GPU instance and optionally wait for SSH to be ready

        Args:
            instance_id: Instance ID
            instance_uuid: Instance UUID
            wait_for_ssh: Whether to wait for SSH to be ready (default: True)
            max_retries: Maximum SSH retry attempts (default: 30)
            retry_interval: Seconds between SSH retries (default: 10)
            start_mode: Start mode (default: "gpu")

        Returns:
            Tuple[bool, Optional[str]]: (success, success_time or error_message)
        """
        start_request_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{start_request_time}] Starting instance {instance_uuid} (ID: {instance_id})...")

        # Check current status first
        instance = self.get_instance_by_uuid(instance_uuid)
        if instance:
            current_status = instance.get("status")
            if current_status == STATUS_RUNNING:
                print(f"✓ Instance is already running (status={current_status}). Skipping start API call.")

                # If wait_for_ssh, still verify SSH is ready
                if wait_for_ssh:
                    ssh_command = instance.get("ssh_command")
                    ssh_password = instance.get("ssh_password")
                    if ssh_command and ssh_password:
                        print(f"Verifying SSH connection...")
                        if self._check_ssh_ready(ssh_command, ssh_password):
                            print(f"✓ SSH is ready")
                            return True, start_request_time
                        else:
                            print(f"⚠ Instance running but SSH not ready, will retry...")
                            # Continue to SSH retry loop below
                    else:
                        return True, start_request_time
                else:
                    return True, start_request_time
            else:
                print(f"Current status: {current_status}")

        # Send start request only if not already running
        if not instance or instance.get("status") != STATUS_RUNNING:
            result = self._send_instance_action(instance_id, instance_uuid, "start", start_mode)

            if not result or result.get("code") != 200:
                error_msg = f"Failed to start instance. Response: {result}"
                print(f"✗ {error_msg}")
                return False, error_msg

            print(f"✓ Start request accepted")

        if not wait_for_ssh:
            return True, start_request_time

        # Wait for instance info to be available
        print(f"Waiting for instance to initialize...")
        time.sleep(5)

        # Get SSH credentials (refresh instance data)
        instance = self.get_instance_by_uuid(instance_uuid)
        if not instance:
            error_msg = f"Could not find instance {instance_uuid}"
            print(f"✗ {error_msg}")
            return False, error_msg

        ssh_command = instance.get("ssh_command")
        ssh_password = instance.get("ssh_password")

        if not ssh_command or not ssh_password:
            error_msg = "SSH credentials not available"
            print(f"✗ {error_msg}")
            return False, error_msg

        print(f"SSH Command: {ssh_command}")
        print(f"Attempting SSH connection (max {max_retries} attempts, {retry_interval}s interval)...")

        overall_start = time.time()

        for attempt in range(1, max_retries + 1):
            attempt_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"  [{attempt_time}] SSH attempt {attempt}/{max_retries}...", end=" ")

            if self._check_ssh_ready(ssh_command, ssh_password):
                success_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                elapsed = time.time() - overall_start

                print(f"OK!")
                print(f"\n{'=' * 60}")
                print(f"✓ INSTANCE STARTED SUCCESSFULLY")
                print(f"{'=' * 60}")
                print(f"Instance UUID: {instance_uuid}")
                print(f"Instance ID:   {instance_id}")
                print(f"SSH Command:   {ssh_command}")
                print(f"SSH Password:  {ssh_password}")
                print(f"Start Time:    {start_request_time}")
                print(f"SSH Ready:     {success_time}")
                print(f"Total Elapsed: {elapsed:.2f} seconds")
                print(f"SSH Attempts:  {attempt}")
                print(f"{'=' * 60}\n")

                return True, success_time
            else:
                print(f"Failed")
                if attempt < max_retries:
                    time.sleep(retry_interval)

        error_msg = f"SSH not ready after {max_retries} attempts"
        print(f"\n✗ {error_msg}")
        return False, error_msg

    def stop_instance(self, instance_id: int, instance_uuid: str) -> Tuple[bool, Optional[str]]:
        """
        Stop a GPU instance

        Args:
            instance_id: Instance ID
            instance_uuid: Instance UUID

        Returns:
            Tuple[bool, Optional[str]]: (success, timestamp or error_message)
        """
        stop_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{stop_time}] Stopping instance {instance_uuid} (ID: {instance_id})...")

        # Check current status first
        instance = self.get_instance_by_uuid(instance_uuid)
        if instance:
            current_status = instance.get("status")
            if current_status == STATUS_STOPPED:
                print(f"✓ Instance is already stopped (status={current_status}). Skipping stop API call.")
                return True, stop_time
            else:
                print(f"Current status: {current_status}")

        # Send stop request only if not already stopped
        result = self._send_instance_action(instance_id, instance_uuid, "stop")

        if result and result.get("code") == 200:
            print(f"✓ Instance stopped successfully")
            print(f"  Stop Time: {stop_time}")
            return True, stop_time
        else:
            error_msg = f"Failed to stop instance. Response: {result}"
            print(f"✗ {error_msg}")
            return False, error_msg


def print_instance_info(instance: Dict) -> None:
    """Print formatted instance information"""
    status = instance.get('status')
    status_str = "RUNNING" if status == STATUS_RUNNING else "STOPPED" if status == STATUS_STOPPED else f"UNKNOWN({status})"

    print("-" * 60)
    print(f"Instance ID:   {instance.get('webide_instance_id')}")
    print(f"Instance UUID: {instance.get('webide_instance_uuid')}")
    print(f"Name:          {instance.get('webide_instance_name')}")
    print(f"Nickname:      {instance.get('nick_name', 'N/A')}")
    print(f"Product:       {instance.get('product_name')}")
    print(f"Data Center:   {instance.get('data_center_name')}")
    print(f"Image:         {instance.get('image_display_name')} ({instance.get('image_display_version')})")
    print(f"Status:        {status} ({status_str})")
    print(f"Charge Type:   {instance.get('charge_type')}")
    print(f"SSH Command:   {instance.get('ssh_command')}")
    print(f"SSH Password:  {instance.get('ssh_password')}")
    print(f"Jupyter URL:   {instance.get('jupyter_url')}")

    open_apis = instance.get('open_apis', [])
    if open_apis:
        print("Open APIs:")
        for api in open_apis:
            print(f"  - {api.get('name')}: {api.get('api_url')}")


def main():
    """Main function - list all instances"""

    # Create client
    client = GPUFreeClient()

    print("=" * 60)
    print("GPUFree Instance Manager")
    print("=" * 60)

    # List all instances
    print("\nListing all instances...\n")
    result = client.list_instances(page_no=1, page_size=50)

    if result and result.get("code") == 200:
        data = result.get("data", {})
        instances = data.get("dataList", [])
        total = data.get("totalRecord", 0)

        print(f"Total instances: {total}\n")

        for instance in instances:
            print_instance_info(instance)
        print("-" * 60)
    else:
        print("Failed to fetch instances.")
        return 1

    print("\nDone.")
    return 0

    # # Instance configurations for start/stop tests
    # START_INSTANCE_ID = 7764
    # START_INSTANCE_UUID = "gghcmwa6-emgm7485"
    #
    # STOP_INSTANCE_ID = 7792
    # STOP_INSTANCE_UUID = "pe8xqrcp-d79wvs3s"
    #
    # # Start instance (with SSH ready check)
    # print(f"\n[Step 2] Starting instance...\n")
    # success, result_msg = client.start_instance(
    #     instance_id=START_INSTANCE_ID,
    #     instance_uuid=START_INSTANCE_UUID,
    #     wait_for_ssh=True,
    #     max_retries=30,
    #     retry_interval=10
    # )
    #
    # if not success:
    #     print(f"Start failed: {result_msg}")
    #     return 1
    #
    # # Stop another instance
    # print(f"\n[Step 3] Stopping instance...\n")
    # success, result_msg = client.stop_instance(
    #     instance_id=STOP_INSTANCE_ID,
    #     instance_uuid=STOP_INSTANCE_UUID
    # )
    #
    # if not success:
    #     print(f"Stop failed: {result_msg}")
    #     return 1
    #
    # print("\n✓ All operations completed successfully!")


# Example usage for external programs

from list_gpufree import GPUFreeClient, STATUS_RUNNING, STATUS_STOPPED

# Create client
client = GPUFreeClient()

# List instances
result = client.list_instances()

"""
# Start instance and wait for SSH (skips API call if already running)
#success, msg = client.start_instance(
#    instance_id=7764,
#    instance_uuid="gghcmwa6-emgm7485",
#    wait_for_ssh=True
#)

# Stop instance (skips API call if already stopped)
#success, msg = client.stop_instance(
#    instance_id=7792,
#    instance_uuid="pe8xqrcp-d79wvs3s"
#)
"""

if __name__ == "__main__":
    sys.exit(main())
