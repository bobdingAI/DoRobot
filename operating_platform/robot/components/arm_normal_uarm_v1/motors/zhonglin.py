import serial
import time
import re
import numpy as np
from typing import Dict, Any
from .motors_bus import Motor, MotorCalibration, MotorNormMode


class ZhonglinMotorsBus:
    """
    Standalone driver for Zhonglin ASCII protocol servos.

    This is a simplified implementation for leader arm use (read-only).
    It does NOT inherit from MotorsBus to avoid abstract method requirements.
    """

    # Class attributes for compatibility
    model_ctrl_table = {"zhonglin": {}}
    model_number_table = {"zhonglin": 0}
    model_resolution_table = {"zhonglin": 4096}

    def __init__(
        self,
        port: str,
        motors: Dict[str, Motor],
        calibration: Dict[str, MotorCalibration] = None,
        baudrate: int = 115200,
    ):
        self.port = port
        self.motors = motors
        self.calibration = calibration if calibration else {}
        self.baudrate = baudrate
        self.ser = None
        self.zero_angles = {name: 0.0 for name in motors}
        self.is_connected = False

    def connect(self, handshake: bool = True):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1)
            self.is_connected = True
            print(f"[Zhonglin] Serial port {self.port} opened at {self.baudrate}")
            self._init_servos()
        except Exception as e:
            print(f"[Zhonglin] Failed to connect: {e}")
            raise e

    def disconnect(self, disable_torque: bool = False):
        if self.ser:
            self.ser.close()
            self.ser = None
            self.is_connected = False
            print(f"[Zhonglin] Serial port {self.port} closed")

    def send_command(self, cmd: str) -> str:
        if not self.ser:
            return ""
        self.ser.write(cmd.encode('ascii'))
        time.sleep(0.008)
        return self.ser.read_all().decode('ascii', errors='ignore')

    def pwm_to_angle(self, response_str: str, pwm_min=500, pwm_max=2500, angle_range=270) -> float:
        match = re.search(r'P(\d{4})', response_str)
        if not match:
            return None
        pwm_val = int(match.group(1))
        pwm_span = pwm_max - pwm_min
        angle = (pwm_val - pwm_min) / pwm_span * angle_range
        return angle

    def _init_servos(self):
        """Initialize and record the zero angle of each servo."""
        print("[Zhonglin] Initializing servos...")
        self.send_command('#000PVER!')
        for name, motor in self.motors.items():
            self.send_command("#000PCSK!")
            self.send_command(f'#{motor.id:03d}PULK!')
            # Test read to ensure connectivity
            response = self.send_command(f'#{motor.id:03d}PRAD!')
            angle = self.pwm_to_angle(response.strip())
            if angle is None:
                print(f"[Zhonglin] Warning: Could not read from motor {name} (ID: {motor.id})")
        print(f"[Zhonglin] Servo initialization completed.")

    def sync_read(self, register: str, motors: list[str] = None) -> Dict[str, float]:
        """Read present positions. register argument is ignored as Zhonglin has fixed protocol."""
        results = {}
        target_motors = motors if motors else self.motors.keys()
        for name in target_motors:
            motor = self.motors[name]
            response = self.send_command(f'#{motor.id:03d}PRAD!')
            angle = self.pwm_to_angle(response.strip())
            if angle is not None:
                results[name] = angle
            else:
                results[name] = 0.0 # Error fallback
        return results

    def sync_write(self, register: str, values: Dict[str, float]):
        """Write goal positions. Not typically used for passive leader arms, but implemented for compatibility."""
        # Zhonglin write protocol: #001P1500T1000! where 1500 is PWM, 1000 is time
        # This is omitted for now as the UArm is used as a leader (reader only)
        pass

    def configure_motors(self):
        pass

