
import atexit
import cv2
import json
import logging
import signal
import time
import draccus
import socketio
import requests
import traceback
import threading
import queue
import subprocess
import os
from pathlib import Path

from dataclasses import dataclass, asdict
from pathlib import Path
from pprint import pformat
from deepdiff import DeepDiff
from functools import cache
from termcolor import colored
from datetime import datetime


# from operating_platform.policy.config import PreTrainedConfig
from operating_platform.robot.robots.configs import RobotConfig
from operating_platform.robot.robots.utils import make_robot_from_config, Robot, busy_wait, safe_disconnect
from operating_platform.utils import parser
from operating_platform.utils.utils import has_method, init_logging, log_say, get_current_git_branch, git_branch_log, get_container_ip_from_hosts
from operating_platform.utils.data_file import find_epindex_from_dataid_json

from operating_platform.utils.constants import DOROBOT_DATASET
from operating_platform.dataset.dorobot_dataset import *
from operating_platform.dataset.visual.visual_dataset import visualize_dataset

# from operating_platform.core._client import Coordinator
from operating_platform.core.daemon import Daemon
from operating_platform.core.record import Record, RecordConfig
from operating_platform.core.replay import DatasetReplayConfig, ReplayConfig, replay
from operating_platform.utils.camera_display import CameraDisplay
from operating_platform.core.cloud_train import CloudTrainer, run_cloud_training
from operating_platform.core.edge_upload import EdgeUploader, run_edge_upload, EdgeConfig
import getpass

DEFAULT_FPS = 30

# Global cloud credentials (set at startup if CLOUD_OFFLOAD=1)
_cloud_credentials = None

# Cloud offload modes
OFFLOAD_LOCAL = 0           # Encode locally, NO upload (local only)
OFFLOAD_CLOUD_RAW = 1       # Skip encoding, upload raw images to cloud for encoding
OFFLOAD_EDGE = 2            # Skip encoding, rsync to edge server for encoding
OFFLOAD_CLOUD_ENCODED = 3   # Encode locally, upload encoded videos to cloud for training
OFFLOAD_LOCAL_RAW = 4       # Skip encoding, save raw images locally only (for later edge_encode.py)


def test_edge_connection() -> bool:
    """
    Test connection to edge server.
    Returns True if connection successful.
    """
    logging.info("=" * 50)
    logging.info("EDGE UPLOAD MODE - Testing Connection")
    logging.info("=" * 50)

    config = EdgeConfig.from_env()
    logging.info(f"Edge server: {config.user}@{config.host}:{config.port}")
    logging.info(f"Remote path: {config.remote_path}")

    uploader = EdgeUploader(config)
    # Use quick_test=True for faster startup (5s timeout instead of 30s+60s)
    if uploader.test_connection(quick_test=True):
        logging.info("Edge server connection successful!")
        return True
    else:
        logging.error("Edge server connection failed!")
        logging.error("Check EDGE_SERVER_HOST, EDGE_SERVER_USER, EDGE_SERVER_PORT environment variables")
        return False


def prompt_cloud_login():
    """
    Prompt user for cloud login credentials at startup.
    Returns (username, password) tuple or None if login fails.
    """
    global _cloud_credentials

    logging.info("=" * 50)
    logging.info("CLOUD MODE - Login Required")
    logging.info("=" * 50)
    print("\nPlease enter your cloud training credentials:")

    try:
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ").strip()

        if not username or not password:
            logging.error("Username and password are required")
            return None

        # Test login with CloudTrainer
        logging.info("Verifying credentials...")
        trainer = CloudTrainer(username=username, password=password)
        if trainer.login():
            logging.info("Login successful!")
            _cloud_credentials = (username, password)
            trainer.cleanup()
            return _cloud_credentials
        else:
            logging.error("Login failed - invalid credentials")
            return None

    except KeyboardInterrupt:
        logging.info("\nLogin cancelled")
        return None
    except Exception as e:
        logging.error(f"Login error: {e}")
        return None

@cache
def is_headless():
    """Detects if python is running without a monitor."""
    try:
        import pynput  # noqa

        return False
    except Exception:
        print(
            "Error trying to import pynput. Switching to headless mode. "
            "As a result, the video stream from the cameras won't be shown, "
            "and you won't be able to change the control flow with keyboards. "
            "For more info, see traceback below.\n"
        )
        traceback.print_exc()
        print()
        return True


@dataclass
class ControlPipelineConfig:
    robot: RobotConfig
    record: RecordConfig
    # control: ControlConfig

    @classmethod
    def __get_path_fields__(cls) -> list[str]:
        """This enables the parser to load config from the policy using `--policy.path=local/dir`"""
        return ["control.policy"]
#自己写了份初稿发现可以运行，采用AI润色完善代码
class VideoEncoderThread(threading.Thread):
    """
    后台视频编码守护线程：
    - 自动从任务队列读取任务
    - 每个任务使用 ffmpeg 将图片序列编码为 mp4 视频
    - 支持多线程并发加速编码
    """

    def __init__(self, num_workers: int = 3):
        """
        :param num_workers: 并发 ffmpeg 编码线程数（建议 2~4）
        """
        super().__init__(daemon=True)
        self.task_queue = queue.Queue()
        self.running = True
        self.num_workers = num_workers
        self.workers: list[threading.Thread] = []

    def run(self):
        """主线程启动所有 worker 并维持运行"""
        print(f"[VideoEncoderThread] Starting with {self.num_workers} workers...")
        for i in range(self.num_workers):
            t = threading.Thread(target=self._worker_loop, name=f"EncoderWorker-{i}", daemon=True)
            t.start()
            self.workers.append(t)

        # 主线程只是负责维持生命周期
        while self.running:
            time.sleep(0.5)

    def _worker_loop(self):
        """每个 worker 从队列中拉取任务并执行"""
        while self.running:
            try:
                task = self.task_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                if task is not None:
                    self.encode_video(**task)
            except Exception as e:
                print(f"[{threading.current_thread().name}] Error: {e}")
            finally:
                self.task_queue.task_done()

    def encode_video(self, img_dir: Path, output_path: Path, fps: int = 30):
        """
        使用 ffmpeg 将指定文件夹下的图片编码为视频
        """
        if not img_dir.exists():
            print(f"[VideoEncoderThread] Directory not found: {img_dir}")
            return

        images = sorted([p for p in img_dir.glob("*.png")])
        if not images:
            print(f"[VideoEncoderThread] No images found in {img_dir}")
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[{threading.current_thread().name}] Encoding {len(images)} frames -> {output_path}")

        cmd = [
            "ffmpeg",
            "-y",
            "-framerate", str(fps),
            "-pattern_type", "glob",
            "-i", "*.png",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

        try:
            subprocess.run(
                cmd,
                cwd=str(img_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            print(f"[{threading.current_thread().name}] Finished: {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"[{threading.current_thread().name}] ffmpeg failed for {img_dir}: {e}")

    def add_task(self, img_dir: Path, output_path: Path, fps: int = 30):
        """添加编码任务"""
        self.task_queue.put({"img_dir": img_dir, "output_path": output_path, "fps": fps})

    def stop(self):
        """停止所有线程（不等待队列）"""
        print("[VideoEncoderThread] Stopping encoder threads...")
        self.running = False
        # 给每个worker一个None任务，确保其能退出阻塞
        for _ in range(self.num_workers):
            self.task_queue.put(None)
        print("[VideoEncoderThread] Stop signal sent to workers.")
    def is_idle(self) -> bool:
        """
        检查编码器是否空闲：
        - 队列为空且所有 ffmpeg 子进程执行完毕
        """
        return self.task_queue.empty()
    
# def record_loop(cfg: ControlPipelineConfig, daemon: Daemon, video_encoder:VideoEncoderThread):
def record_loop(cfg: ControlPipelineConfig, daemon: Daemon):

    # 确保数据集根目录存在
    dataset_path = DOROBOT_DATASET
    dataset_path.mkdir(parents=True, exist_ok=True)
    logging.info(f"Dataset root directory: {dataset_path}")

    # Get repo_id from config
    repo_id = cfg.record.repo_id

    # Simple path structure: ~/DoRobot/dataset/{repo_id}/
    # This makes it easy to match with inference and cloud training
    target_dir = dataset_path / repo_id
    # 创建目标目录（确保父目录存在）
    target_dir.mkdir(parents=True, exist_ok=True)
    logging.info(f"Target directory: {target_dir}")

    # Check cloud_offload mode: 0=local, 1=cloud, 2=edge
    cloud_offload = getattr(cfg.record, 'cloud_offload', OFFLOAD_LOCAL)
    # Convert boolean to int for backward compatibility
    if isinstance(cloud_offload, bool):
        cloud_offload = OFFLOAD_CLOUD_RAW if cloud_offload else OFFLOAD_LOCAL

    # Model output path (used by cloud training)
    dorobot_home = Path.home() / "DoRobot"
    model_dir = dorobot_home / "model"

    # Always clear existing data to start fresh
    # This prevents issues with incomplete/corrupted data from previous runs
    # Users don't need to manually clean up folders between sessions
    import shutil
    resume = False

    # Clear dataset folder if it exists and has content
    if target_dir.exists() and any(target_dir.iterdir()):
        logging.warning(f"Clearing existing dataset in {target_dir}")
        shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Dataset folder cleared")
    else:
        logging.info(f"Starting new recording session in: {target_dir}")

    # Clear model folder if it exists and has content
    # This ensures inference will use the newly trained model after cloud training
    if model_dir.exists() and any(model_dir.iterdir()):
        logging.warning(f"Clearing existing model in {model_dir}")
        shutil.rmtree(model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Model folder cleared")
    else:
        model_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Model folder ready: {model_dir}")

    # 任务配置（使用默认值，可选字段从配置获取）
    record_cmd = {
        "task_id": getattr(cfg.record, 'task_id', None) or "default_task",
        "task_name": repo_id,
        "task_data_id": getattr(cfg.record, 'data_id', None) or "001",
        "collector_id": getattr(cfg.record, 'collector_id', None) or "default_collector",
        "countdown_seconds": getattr(cfg.record, 'countdown', None) or 3,
        "task_steps": [
            {
                "duration": str(step.get("duration", 10)),
                "instruction": step.get("instruction", "put")
            } for step in getattr(cfg.record, 'task_steps', [{"duration": "10", "instruction": "put"}])
        ]
    }

    # 创建记录器一次，在整个session中复用
    # Skip encoding if cloud_offload is 1 (cloud raw), 2 (edge), or 4 (local raw)
    # Mode 0 (local) and mode 3 (cloud encoded) do local encoding
    skip_encoding = cloud_offload in (OFFLOAD_CLOUD_RAW, OFFLOAD_EDGE, OFFLOAD_LOCAL_RAW)

    record_cfg = RecordConfig(
        fps=cfg.record.fps,
        repo_id=repo_id,
        single_task=cfg.record.single_task,
        video=daemon.robot.use_videos,
        resume=resume,
        root=target_dir,
        use_async_save=cfg.record.use_async_save,
        async_save_queue_size=cfg.record.async_save_queue_size,
        async_save_timeout_s=cfg.record.async_save_timeout_s,
        async_save_max_retries=cfg.record.async_save_max_retries,
        cloud_offload=skip_encoding,  # True if cloud_offload is 1 or 2
    )

    # Track the actual offload mode (0, 1, or 2)
    offload_mode = cloud_offload

    # Log offload mode status and verify connection
    if offload_mode == OFFLOAD_EDGE:
        logging.info("=" * 50)
        logging.info("EDGE UPLOAD MODE (CLOUD_OFFLOAD=2)")
        logging.info("Video encoding will be skipped - raw images sent to edge server via rsync")
        logging.info("=" * 50)

        # Test edge server connection at startup
        if not test_edge_connection():
            logging.warning("=" * 50)
            logging.warning("Edge server connection failed!")
            logging.warning("Data will be saved locally but NOT uploaded to edge server")
            logging.warning("=" * 50)
            offload_mode = OFFLOAD_LOCAL  # Fall back to local mode

    elif offload_mode == OFFLOAD_CLOUD_RAW:
        logging.info("=" * 50)
        logging.info("CLOUD RAW MODE (CLOUD_OFFLOAD=1)")
        logging.info("Video encoding will be skipped - raw images uploaded to cloud")
        logging.info("=" * 50)

        # Prompt for cloud login at startup
        credentials = prompt_cloud_login()
        if credentials is None:
            logging.warning("=" * 50)
            logging.warning("Cloud login failed or cancelled")
            logging.warning("Data will be saved locally but NOT uploaded to cloud")
            logging.warning("=" * 50)

    elif offload_mode == OFFLOAD_CLOUD_ENCODED:
        logging.info("=" * 50)
        logging.info("CLOUD ENCODED MODE (CLOUD_OFFLOAD=3)")
        logging.info("Video encoding locally (NPU/CPU), then upload encoded videos to cloud")
        logging.info("=" * 50)

        # Prompt for cloud login at startup
        credentials = prompt_cloud_login()
        if credentials is None:
            logging.warning("=" * 50)
            logging.warning("Cloud login failed or cancelled")
            logging.warning("Data will be saved locally but NOT uploaded to cloud")
            logging.warning("=" * 50)

    elif offload_mode == OFFLOAD_LOCAL_RAW:
        logging.info("=" * 50)
        logging.info("LOCAL RAW MODE (CLOUD=4)")
        logging.info("Video encoding will be skipped - raw images saved locally only")
        logging.info("Use 'python scripts/edge_encode.py' later to upload and encode")
        logging.info("=" * 50)

    record = Record(
        fps=cfg.record.fps,
        robot=daemon.robot,
        daemon=daemon,
        record_cfg=record_cfg,
        record_cmd=record_cmd
    )

    logging.info("="*30)
    logging.info(f"Starting recording session | Resume: {resume} | Episodes: {record.dataset.meta.total_episodes}")
    logging.info("="*30)

    # Create unified camera display (combines all cameras into one window)
    camera_display = CameraDisplay(
        window_name="Recording - Cameras",
        layout="horizontal",
        show_labels=True
    )

    # 开始记录（带倒计时）- 只做一次
    if record_cmd.get("countdown_seconds", 3) > 0:
        for i in range(record_cmd["countdown_seconds"], 0, -1):
            logging.info(f"Recording starts in {i}...")
            time.sleep(1)

    record.start()

    # Voice prompt: ready to start
    log_say("准备就绪。按N键保存并开始下一集。", play_sounds=True)

    # 主循环：连续录制多个episodes
    while True:
        # Get current episode index for display
        current_episode = record.dataset.meta.total_episodes

        logging.info("Recording active. Press:")
        logging.info("- 'n' to save current episode and start new one")
        logging.info("- 'p' to proceed after environment reset")
        if offload_mode == OFFLOAD_EDGE:
            logging.info("- 'e' to stop and upload to edge server for encoding/training")
        elif offload_mode == OFFLOAD_CLOUD_RAW:
            logging.info("- 'e' to stop and upload raw images to cloud for encoding/training")
        elif offload_mode == OFFLOAD_CLOUD_ENCODED:
            logging.info("- 'e' to stop, encode locally, upload encoded videos to cloud for training")
        elif offload_mode == OFFLOAD_LOCAL_RAW:
            logging.info("- 'e' to stop and save raw images locally (use edge_encode.py later)")
        else:
            logging.info("- 'e' to stop recording, encode locally, and exit")

        # Episode录制循环
        while True:
            daemon.update()
            observation = daemon.get_observation()

            # 显示图像（仅在非无头模式）- 使用统一相机窗口
            # Get current episode from the episode buffer (pre-allocated index)
            current_episode = record.dataset.episode_buffer.get("episode_index", 0)
            if observation and not is_headless():
                key = camera_display.show(observation, episode_index=current_episode, status="Recording")
            else:
                key = cv2.waitKey(10)

            # 处理用户输入
            if key in [ord('n'), ord('N')]:
                logging.info("Saving current episode and starting new one...")

                # Save current episode (non-blocking)
                metadata = record.save()

                # Log save status
                if hasattr(metadata, 'episode_index'):
                    logging.info(f"Episode {metadata.episode_index} queued (queue pos: {metadata.queue_position})")

                # Check for save errors from previous episodes
                if hasattr(record, 'async_saver') and record.async_saver:
                    status = record.async_saver.get_status()
                    if status["failed_count"] > 0:
                        logging.warning(f"Warning: {status['failed_count']} episodes failed to save: "
                                       f"{status['failed_episodes']}")

                logging.info("*"*30)
                logging.info("Reset Environment - Press 'p' to proceed to next episode")
                logging.info("*"*30)

                # Voice prompt: reset environment
                log_say("请重置环境。按P键继续。", play_sounds=True)

                # Wait for 'p' to proceed (with timeout)
                reset_start = time.time()
                reset_timeout = 60  # 60 seconds timeout

                while time.time() - reset_start < reset_timeout:
                    daemon.update()
                    observation = daemon.get_observation()

                    # Show reset view with status
                    # Get next episode index from the new buffer (allocated after save)
                    if observation and not is_headless():
                        next_episode = record.dataset.episode_buffer.get("episode_index", 0)
                        key = camera_display.show(observation, episode_index=next_episode, status="Reset - Press P")
                    else:
                        key = cv2.waitKey(10)

                    if key in [ord('p'), ord('P')]:
                        logging.info("Reset confirmed. Proceeding to next episode...")
                        break
                    elif key in [ord('e'), ord('E')]:
                        logging.info("User requested exit during reset phase")

                        # Show collection summary BEFORE starting encoding
                        total_episodes = record.dataset.meta.total_episodes
                        logging.info("=" * 50)
                        logging.info("COLLECTION SUMMARY")
                        logging.info(f"Total episodes collected: {total_episodes}")
                        logging.info("=" * 50)

                        # Voice prompt based on offload mode
                        if offload_mode == OFFLOAD_EDGE:
                            log_say(f"采集结束。共采集{total_episodes}集。正在上传到边缘服务器。", play_sounds=True)
                        elif offload_mode == OFFLOAD_CLOUD_RAW:
                            log_say(f"采集结束。共采集{total_episodes}集。正在上传到云端训练。", play_sounds=True)
                        elif offload_mode == OFFLOAD_CLOUD_ENCODED:
                            log_say(f"采集结束。共采集{total_episodes}集。正在编码并上传到云端。", play_sounds=True)
                        elif offload_mode == OFFLOAD_LOCAL_RAW:
                            log_say(f"采集结束。共采集{total_episodes}集。原始图像已保存到本地。", play_sounds=True)
                        else:
                            log_say(f"采集结束。共采集{total_episodes}集。请等待视频编码。", play_sounds=True)

                        # Close camera display
                        camera_display.close()
                        cv2.destroyAllWindows()
                        cv2.waitKey(1)

                        # Stop daemon first
                        logging.info("Stopping DORA daemon...")
                        daemon.stop()
                        logging.info("DORA daemon stopped")

                        # Stop recording thread and wait for image writer
                        record.stop()

                        # Wait for all async saves to complete (including encoding)
                        if hasattr(record, 'async_saver') and record.async_saver:
                            status = record.async_saver.get_status()
                            pending_total = status['pending_count'] + status['queue_size']
                            if pending_total > 0:
                                logging.info(f"Waiting for {pending_total} saves (queue={status['queue_size']}, pending={status['pending_count']})...")

                            record.async_saver.stop(wait_for_completion=True)

                            final_status = record.async_saver.get_status()
                            logging.info(f"Save stats: queued={final_status['stats']['total_queued']} "
                                       f"completed={final_status['stats']['total_completed']} "
                                       f"failed={final_status['stats']['total_failed']}")

                        # Run upload/training based on offload mode
                        upload_dataset_path = str(target_dir)
                        logging.info(f"Dataset path: {upload_dataset_path}")

                        if offload_mode == OFFLOAD_EDGE:
                            # Edge upload mode - rsync to edge server, wait for training, download model
                            logging.info("="*50)
                            logging.info("Starting edge upload workflow...")
                            logging.info("Will wait for training completion and model download")
                            logging.info("="*50)

                            # Model output path: ~/DoRobot/model
                            dorobot_home = Path.home() / "DoRobot"
                            model_output_path = dorobot_home / "model"
                            model_output_path.mkdir(parents=True, exist_ok=True)
                            logging.info(f"Model output path: {model_output_path}")

                            try:
                                success = run_edge_upload(
                                    dataset_path=upload_dataset_path,
                                    repo_id=repo_id,
                                    trigger_training=True,
                                    wait_for_training=True,  # Wait for training completion
                                    timeout_minutes=120,  # 2 hours timeout
                                    model_output_path=str(model_output_path),  # Download model after training
                                )
                                if success:
                                    logging.info("="*50)
                                    logging.info("EDGE WORKFLOW COMPLETED SUCCESSFULLY!")
                                    logging.info(f"Model downloaded to: {model_output_path}")
                                    logging.info("="*50)
                                    logging.info("Model download completed. Ready to run inference.")
                                    log_say("模型下载完成。可以开始推理了。", play_sounds=True)
                                else:
                                    logging.error("=" * 50)
                                    logging.error("EDGE WORKFLOW FAILED")
                                    logging.error(f"Local data preserved at: {upload_dataset_path}")
                                    logging.error("=" * 50)
                                    log_say("边缘工作流失败。本地数据已保存。", play_sounds=True)
                            except Exception as e:
                                logging.error(f"Edge upload error: {e}")
                                logging.error(f"Local data preserved at: {upload_dataset_path}")
                                traceback.print_exc()
                                log_say("边缘上传出错。本地数据已保存。", play_sounds=True)

                        elif offload_mode == OFFLOAD_CLOUD_RAW:
                            # Cloud raw mode - upload raw images to cloud for encoding
                            logging.info(f"Local data saved at: {upload_dataset_path}")

                            # Check if we have valid credentials
                            if _cloud_credentials is None:
                                logging.warning("=" * 50)
                                logging.warning("CLOUD UPLOAD SKIPPED - No valid credentials")
                                logging.warning(f"Local data preserved at: {upload_dataset_path}")
                                logging.warning("=" * 50)
                                log_say("云端上传已跳过。本地数据已保存。", play_sounds=True)
                            else:
                                dorobot_home = Path.home() / "DoRobot"
                                model_output_path = dorobot_home / "model"
                                model_output_path.mkdir(parents=True, exist_ok=True)

                                try:
                                    username, password = _cloud_credentials
                                    success = run_cloud_training(
                                        dataset_path=upload_dataset_path,
                                        model_output_path=str(model_output_path),
                                        username=username,
                                        password=password,
                                        timeout_minutes=120
                                    )
                                    if success:
                                        logging.info("Cloud training completed!")
                                        log_say("训练完成。", play_sounds=True)
                                    else:
                                        logging.error("=" * 50)
                                        logging.error("CLOUD TRAINING FAILED")
                                        logging.error(f"Local data preserved at: {upload_dataset_path}")
                                        logging.error("=" * 50)
                                        log_say("云端训练失败。本地数据已保存。", play_sounds=True)
                                except Exception as e:
                                    logging.error(f"Cloud training error: {e}")
                                    logging.error(f"Local data preserved at: {upload_dataset_path}")
                                    log_say("云端训练出错。本地数据已保存。", play_sounds=True)

                        elif offload_mode == OFFLOAD_CLOUD_ENCODED:
                            # Cloud encoded mode - local encoding done, upload encoded videos to cloud
                            logging.info(f"Local data saved at: {upload_dataset_path}")

                            # Check if we have valid credentials
                            if _cloud_credentials is None:
                                logging.warning("=" * 50)
                                logging.warning("CLOUD UPLOAD SKIPPED - No valid credentials")
                                logging.warning(f"Local data preserved at: {upload_dataset_path}")
                                logging.warning("=" * 50)
                                log_say("云端上传已跳过。本地数据已保存。", play_sounds=True)
                            else:
                                dorobot_home = Path.home() / "DoRobot"
                                model_output_path = dorobot_home / "model"
                                model_output_path.mkdir(parents=True, exist_ok=True)

                                try:
                                    username, password = _cloud_credentials
                                    success = run_cloud_training(
                                        dataset_path=upload_dataset_path,
                                        model_output_path=str(model_output_path),
                                        username=username,
                                        password=password,
                                        timeout_minutes=120
                                    )
                                    if success:
                                        logging.info("Cloud training completed!")
                                        log_say("训练完成。模型已下载。", play_sounds=True)
                                    else:
                                        logging.error("=" * 50)
                                        logging.error("CLOUD TRAINING FAILED")
                                        logging.error(f"Local data preserved at: {upload_dataset_path}")
                                        logging.error("=" * 50)
                                        log_say("云端训练失败。本地数据已保存。", play_sounds=True)
                                except Exception as e:
                                    logging.error(f"Cloud training error: {e}")
                                    logging.error(f"Local data preserved at: {upload_dataset_path}")
                                    log_say("云端训练出错。本地数据已保存。", play_sounds=True)

                        elif offload_mode == OFFLOAD_LOCAL_RAW:
                            # Local raw mode - just save locally, no upload
                            logging.info("="*50)
                            logging.info("LOCAL RAW MODE - Data saved successfully")
                            logging.info(f"Raw images saved at: {upload_dataset_path}")
                            logging.info("="*50)
                            logging.info("To upload and encode later, run:")
                            logging.info(f"  python scripts/edge_encode.py --dataset {upload_dataset_path}")
                            log_say("原始图像已保存到本地。", play_sounds=True)

                        return
                else:
                    logging.info("Reset timeout - auto-proceeding to next episode")

                # Voice prompt: recording new episode
                next_episode = record.dataset.episode_buffer.get("episode_index", 0)
                log_say(f"正在录制第{next_episode}集。", play_sounds=True)

                break  # Break to restart episode loop

            elif key in [ord('e'), ord('E')]:
                logging.info("Stopping recording and exiting...")

                # Show collection summary BEFORE starting encoding
                total_episodes = record.dataset.meta.total_episodes
                logging.info("=" * 50)
                logging.info("COLLECTION SUMMARY")
                logging.info(f"Total episodes collected: {total_episodes}")
                logging.info("=" * 50)

                # Voice prompt based on offload mode
                if offload_mode == OFFLOAD_EDGE:
                    log_say(f"采集结束。共采集{total_episodes}集。正在上传到边缘服务器。", play_sounds=True)
                elif offload_mode == OFFLOAD_CLOUD_RAW:
                    log_say(f"采集结束。共采集{total_episodes}集。正在上传到云端训练。", play_sounds=True)
                elif offload_mode == OFFLOAD_CLOUD_ENCODED:
                    log_say(f"采集结束。共采集{total_episodes}集。正在编码并上传到云端。", play_sounds=True)
                elif offload_mode == OFFLOAD_LOCAL_RAW:
                    log_say(f"采集结束。共采集{total_episodes}集。原始图像已保存到本地。", play_sounds=True)
                else:
                    log_say(f"采集结束。共采集{total_episodes}集。请等待视频编码。", play_sounds=True)

                # Close camera display window FIRST to release video resources
                logging.info("Closing camera display...")
                camera_display.close()
                cv2.destroyAllWindows()
                cv2.waitKey(1)  # Process any pending window events
                logging.info("Camera display closed")

                # IMPORTANT: Stop the DORA daemon FIRST to disconnect hardware gracefully
                # This prevents hardware disconnection errors during save operations
                logging.info("Stopping DORA daemon (disconnecting hardware)...")
                daemon.stop()
                logging.info("DORA daemon stopped")

                # Save the current episode (async save queues it)
                # Note: record.save() now uses cloud_offload setting automatically
                metadata = record.save()
                if hasattr(metadata, 'episode_index'):
                    if record.cloud_offload:
                        logging.info(f"Episode {metadata.episode_index} saved (raw images, no encoding)")
                    else:
                        logging.info(f"Episode {metadata.episode_index} queued for saving")

                # Now stop recording thread and wait for image writer to complete
                # Hardware is already disconnected, so no risk of arm errors
                record.stop()

                # Properly shutdown async saver (waits for queue AND pending, then stops worker)
                if hasattr(record, 'async_saver') and record.async_saver:
                    status = record.async_saver.get_status()
                    pending_total = status['pending_count'] + status['queue_size']
                    if pending_total > 0:
                        logging.info(f"Waiting for {pending_total} saves (queue={status['queue_size']}, pending={status['pending_count']})...")

                    # stop() calls wait_all_complete() internally and properly shuts down worker thread
                    record.async_saver.stop(wait_for_completion=True)

                    # Print final status
                    final_status = record.async_saver.get_status()
                    logging.info(f"Save stats: queued={final_status['stats']['total_queued']} "
                               f"completed={final_status['stats']['total_completed']} "
                               f"failed={final_status['stats']['total_failed']}")

                # Run upload/training based on offload mode
                upload_dataset_path = str(target_dir)
                logging.info(f"Dataset path: {upload_dataset_path}")

                if offload_mode == OFFLOAD_EDGE:
                    # Edge upload mode - rsync to edge server, wait for training, download model
                    logging.info("="*50)
                    logging.info("Starting edge upload workflow...")
                    logging.info("Will wait for training completion and model download")
                    logging.info("="*50)

                    # Model output path: ~/DoRobot/model
                    dorobot_home = Path.home() / "DoRobot"
                    model_output_path = dorobot_home / "model"
                    model_output_path.mkdir(parents=True, exist_ok=True)
                    logging.info(f"Model output path: {model_output_path}")

                    try:
                        success = run_edge_upload(
                            dataset_path=upload_dataset_path,
                            repo_id=repo_id,
                            trigger_training=True,
                            wait_for_training=True,  # Wait for training completion
                            timeout_minutes=120,  # 2 hours timeout
                            model_output_path=str(model_output_path),  # Download model after training
                        )
                        if success:
                            logging.info("="*50)
                            logging.info("EDGE WORKFLOW COMPLETED SUCCESSFULLY!")
                            logging.info(f"Model downloaded to: {model_output_path}")
                            logging.info("="*50)
                            logging.info("Model download completed. Ready to run inference.")
                            log_say("模型下载完成。可以开始推理了。", play_sounds=True)
                        else:
                            logging.error("=" * 50)
                            logging.error("EDGE WORKFLOW FAILED")
                            logging.error(f"Local data preserved at: {upload_dataset_path}")
                            logging.error("=" * 50)
                            log_say("边缘工作流失败。本地数据已保存。", play_sounds=True)
                    except Exception as e:
                        logging.error(f"Edge upload error: {e}")
                        logging.error(f"Local data preserved at: {upload_dataset_path}")
                        traceback.print_exc()
                        log_say("边缘上传出错。本地数据已保存。", play_sounds=True)

                elif offload_mode == OFFLOAD_CLOUD_RAW:
                    # Cloud raw mode - upload raw images to cloud for encoding
                    logging.info(f"Local data saved at: {upload_dataset_path}")

                    # Check if we have valid credentials
                    if _cloud_credentials is None:
                        logging.warning("=" * 50)
                        logging.warning("CLOUD UPLOAD SKIPPED - No valid credentials")
                        logging.warning(f"Local data preserved at: {upload_dataset_path}")
                        logging.warning("=" * 50)
                        log_say("云端上传已跳过。本地数据已保存。", play_sounds=True)
                    else:
                        # Model output path: sibling folder ~/DoRobot/model
                        dorobot_home = Path.home() / "DoRobot"
                        model_output_path = dorobot_home / "model"
                        model_output_path.mkdir(parents=True, exist_ok=True)
                        logging.info(f"Model output path: {model_output_path}")

                        # Run cloud training
                        logging.info("="*50)
                        logging.info("Starting cloud training workflow...")
                        logging.info("="*50)

                        try:
                            username, password = _cloud_credentials
                            success = run_cloud_training(
                                dataset_path=upload_dataset_path,
                                model_output_path=str(model_output_path),
                                username=username,
                                password=password,
                                timeout_minutes=120  # 2 hours timeout
                            )

                            if success:
                                logging.info("="*50)
                                logging.info("CLOUD TRAINING COMPLETED SUCCESSFULLY!")
                                logging.info(f"Model downloaded to: {model_output_path}")
                                logging.info("="*50)
                                log_say("训练完成。模型已下载。", play_sounds=True)
                            else:
                                logging.error("=" * 50)
                                logging.error("CLOUD TRAINING FAILED")
                                logging.error(f"Local data preserved at: {upload_dataset_path}")
                                logging.error("=" * 50)
                                log_say("云端训练失败。本地数据已保存。", play_sounds=True)

                        except Exception as e:
                            logging.error(f"Cloud training error: {e}")
                            logging.error(f"Local data preserved at: {upload_dataset_path}")
                            traceback.print_exc()
                            log_say("云端训练出错。本地数据已保存。", play_sounds=True)

                elif offload_mode == OFFLOAD_CLOUD_ENCODED:
                    # Cloud encoded mode - local encoding done, upload encoded videos to cloud
                    logging.info(f"Local data saved at: {upload_dataset_path}")

                    # Check if we have valid credentials
                    if _cloud_credentials is None:
                        logging.warning("=" * 50)
                        logging.warning("CLOUD UPLOAD SKIPPED - No valid credentials")
                        logging.warning(f"Local data preserved at: {upload_dataset_path}")
                        logging.warning("=" * 50)
                        log_say("云端上传已跳过。本地数据已保存。", play_sounds=True)
                    else:
                        # Model output path: sibling folder ~/DoRobot/model
                        dorobot_home = Path.home() / "DoRobot"
                        model_output_path = dorobot_home / "model"
                        model_output_path.mkdir(parents=True, exist_ok=True)
                        logging.info(f"Model output path: {model_output_path}")

                        # Run cloud training (with encoded videos)
                        logging.info("="*50)
                        logging.info("Starting cloud training workflow (with encoded videos)...")
                        logging.info("="*50)

                        try:
                            username, password = _cloud_credentials
                            success = run_cloud_training(
                                dataset_path=upload_dataset_path,
                                model_output_path=str(model_output_path),
                                username=username,
                                password=password,
                                timeout_minutes=120  # 2 hours timeout
                            )

                            if success:
                                logging.info("="*50)
                                logging.info("CLOUD TRAINING COMPLETED SUCCESSFULLY!")
                                logging.info(f"Model downloaded to: {model_output_path}")
                                logging.info("="*50)
                                log_say("训练完成。模型已下载。", play_sounds=True)
                            else:
                                logging.error("=" * 50)
                                logging.error("CLOUD TRAINING FAILED")
                                logging.error(f"Local data preserved at: {upload_dataset_path}")
                                logging.error("=" * 50)
                                log_say("云端训练失败。本地数据已保存。", play_sounds=True)

                        except Exception as e:
                            logging.error(f"Cloud training error: {e}")
                            logging.error(f"Local data preserved at: {upload_dataset_path}")
                            traceback.print_exc()
                            log_say("云端训练出错。本地数据已保存。", play_sounds=True)

                elif offload_mode == OFFLOAD_LOCAL_RAW:
                    # Local raw mode - just save locally, no upload
                    logging.info("="*50)
                    logging.info("LOCAL RAW MODE - Data saved successfully")
                    logging.info(f"Raw images saved at: {upload_dataset_path}")
                    logging.info("="*50)
                    logging.info("To upload and encode later, run:")
                    logging.info(f"  python scripts/edge_encode.py --dataset {upload_dataset_path}")
                    log_say("原始图像已保存到本地。", play_sounds=True)

                return

        # Continue recording next episode (thread is still running, just save() reset the buffer)


# Global reference for cleanup
_daemon = None
_cleanup_done = False


def cleanup_resources():
    """Clean up all resources on exit."""
    global _daemon, _cleanup_done

    if _cleanup_done:
        return
    _cleanup_done = True

    logging.info("[Cleanup] Releasing resources...")

    # Close OpenCV windows
    try:
        cv2.destroyAllWindows()
        logging.info("[Cleanup] OpenCV windows closed")
    except Exception as e:
        logging.warning(f"[Cleanup] Error closing OpenCV: {e}")

    # Stop daemon (disconnects robot, releases USB ports)
    if _daemon is not None:
        try:
            _daemon.stop()
            logging.info("[Cleanup] Daemon stopped")
        except Exception as e:
            logging.warning(f"[Cleanup] Error stopping daemon: {e}")

    logging.info("[Cleanup] Resources released")


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logging.info(f"[Signal] Received {sig_name}, cleaning up...")
    cleanup_resources()
    exit(0)


@parser.wrap()
def main(cfg: ControlPipelineConfig):
    global _daemon

    init_logging(level=logging.INFO, force=True)
    git_branch_log()
    logging.info(pformat(asdict(cfg)))

    # Register cleanup handlers
    atexit.register(cleanup_resources)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    daemon = Daemon(fps=DEFAULT_FPS)
    _daemon = daemon  # Store globally for cleanup

    daemon.start(cfg.robot)
    daemon.update()

    # video_encoder = VideoEncoderThread()
    # video_encoder.start()

    try:
        # record_loop(cfg, daemon,video_encoder)
        record_loop(cfg, daemon)
    except KeyboardInterrupt:
        logging.info("Recording interrupted by user")
    except Exception as e:
        logging.error(f"Error during recording: {e}")
        traceback.print_exc()
    finally:
        cleanup_resources()
    

if __name__ == "__main__":
    main()
