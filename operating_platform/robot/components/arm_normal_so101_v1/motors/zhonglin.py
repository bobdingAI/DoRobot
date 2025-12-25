import serial
import time
import re
import numpy as np
import threading
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

    def send_command(self, cmd: str, retries: int = 3) -> str:
        """Send command with retry mechanism for reliability."""
        if not self.ser:
            return ""

        for attempt in range(retries):
            self.ser.reset_input_buffer()  # Clear any stale data
            self.ser.write(cmd.encode('ascii'))
            time.sleep(0.015)  # Increased from 0.008 to 0.015 for more reliable reads
            response = self.ser.read_all().decode('ascii', errors='ignore')

            # Check if we got a valid response
            if response and 'P' in response:
                return response

            # If no valid response and not last attempt, wait a bit longer
            if attempt < retries - 1:
                time.sleep(0.01)

        return ""  # Return empty string if all retries failed

    def pwm_to_angle(self, response_str: str, pwm_min=500, pwm_max=2500, angle_range=270) -> tuple[float, int]:
        """
        Extract PWM value and convert to angle.

        Returns:
            tuple: (angle_degrees, pwm_value) or (None, None) if parsing fails
        """
        match = re.search(r'P(\d{4})', response_str)
        if not match:
            return None, None
        pwm_val = int(match.group(1))
        pwm_span = pwm_max - pwm_min
        angle = (pwm_val - pwm_min) / pwm_span * angle_range
        return angle, pwm_val

    def _normalize_value(self, motor_name: str, raw_angle: float, pwm_val: int, norm_mode: MotorNormMode) -> float:
        """
        Apply calibration and convert to requested normalization mode.

        Args:
            motor_name: Name of the motor
            raw_angle: Raw angle in degrees (0-270) - for fallback only
            pwm_val: Raw PWM value (500-2500)
            norm_mode: Target normalization mode

        Returns:
            Normalized value according to norm_mode
        """
        # If no calibration, return raw angle converted according to mode
        if not self.calibration or motor_name not in self.calibration:
            if norm_mode == MotorNormMode.DEGREES:
                return raw_angle
            elif norm_mode == MotorNormMode.RADIANS:
                return np.deg2rad(raw_angle)
            elif norm_mode == MotorNormMode.RANGE_0_100:
                return (raw_angle / 270.0) * 100.0
            elif norm_mode == MotorNormMode.RANGE_M100_100:
                return ((raw_angle / 270.0) * 200.0) - 100.0
            else:
                return raw_angle

        # Get calibration parameters
        calib = self.calibration[motor_name]

        # Apply homing offset to PWM value
        calibrated_pwm = pwm_val - calib.homing_offset

        # Bound to calibrated range
        bounded_pwm = min(calib.range_max, max(calib.range_min, calibrated_pwm))

        # Normalize according to mode
        if norm_mode == MotorNormMode.DEGREES:
            # Convert PWM to degrees using calibrated range
            norm = ((bounded_pwm - calib.range_min) / (calib.range_max - calib.range_min)) * 270.0
            return -norm if calib.drive_mode else norm
        elif norm_mode == MotorNormMode.RADIANS:
            # Convert PWM to degrees then to radians using calibrated range
            degrees = ((bounded_pwm - calib.range_min) / (calib.range_max - calib.range_min)) * 270.0
            degrees = -degrees if calib.drive_mode else degrees
            return np.deg2rad(degrees)
        elif norm_mode == MotorNormMode.RANGE_0_100:
            norm = ((bounded_pwm - calib.range_min) / (calib.range_max - calib.range_min)) * 100.0
            return 100.0 - norm if calib.drive_mode else norm
        elif norm_mode == MotorNormMode.RANGE_M100_100:
            norm = (((bounded_pwm - calib.range_min) / (calib.range_max - calib.range_min)) * 200.0) - 100.0
            return -norm if calib.drive_mode else norm
        else:
            return raw_angle

    def _init_servos(self):
        """Initialize and record the zero angle of each servo."""
        print("[Zhonglin] Initializing servos...")
        self.send_command('#000PVER!')
        for name, motor in self.motors.items():
            self.send_command("#000PCSK!")
            self.send_command(f'#{motor.id:03d}PULK!')
            # Test read to ensure connectivity
            response = self.send_command(f'#{motor.id:03d}PRAD!')
            angle, pwm_val = self.pwm_to_angle(response.strip())
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
            angle, pwm_val = self.pwm_to_angle(response.strip())
            if angle is not None and pwm_val is not None:
                # Apply calibration and normalization
                normalized_value = self._normalize_value(name, angle, pwm_val, motor.norm_mode)
                # Debug: print first read to verify normalization
                if not hasattr(self, '_debug_printed'):
                    print(f"[Zhonglin Debug] {name}: raw={angle:.2f}° (PWM={pwm_val}) → normalized={normalized_value:.4f} (mode={motor.norm_mode})")
                results[name] = normalized_value
            else:
                results[name] = 0.0 # Error fallback
        if not hasattr(self, '_debug_printed'):
            self._debug_printed = True
        return results

    def sync_write(self, register: str, values: Dict[str, float]):
        """Write goal positions. Not typically used for passive leader arms, but implemented for compatibility."""
        # Zhonglin write protocol: #001P1500T1000! where 1500 is PWM, 1000 is time
        # This is omitted for now as the UArm is used as a leader (reader only)
        pass

    def configure_motors(self):
        pass

    def write_calibration(self, calibration_dict: Dict[str, MotorCalibration], cache: bool = True) -> None:
        """
        Write calibration to cache. Zhonglin leader arms are passive (read-only),
        so calibration is only stored in memory, not written to motors.
        """
        if cache:
            self.calibration = calibration_dict
        print(f"[Zhonglin] Calibration cached (leader arms don't write to motors)")

    def set_half_turn_homings(self, motors: list[str] = None) -> Dict[str, int]:
        """Set homing offsets to center the range around current position."""
        target_motors = motors if motors else list(self.motors.keys())

        # Read current PWM positions (raw values, not angles)
        current_positions = {}
        for name in target_motors:
            motor = self.motors[name]
            response = self.send_command(f'#{motor.id:03d}PRAD!')
            match = re.search(r'P(\d{4})', response.strip())
            if match:
                current_positions[name] = int(match.group(1))
            else:
                print(f"[Zhonglin] Warning: Could not read PWM from motor {name}")
                current_positions[name] = 1500  # Default middle PWM

        # Calculate homing offsets (current_pos - middle_of_range)
        # For Zhonglin PWM range 500-2500, middle is 1500
        homing_offsets = {}
        for name, pos in current_positions.items():
            homing_offsets[name] = pos - 1500

        print(f"[Zhonglin] Homing offsets set: {homing_offsets}")
        return homing_offsets

    def record_ranges_of_motion(
        self, motors: list[str] = None, display_values: bool = True, stop_event: threading.Event = None
    ) -> tuple[Dict[str, int], Dict[str, int]]:
        """Record min/max PWM values for each motor."""
        target_motors = motors if motors else list(self.motors.keys())

        # Initialize min/max tracking
        mins = {name: 9999 for name in target_motors}
        maxes = {name: 0 for name in target_motors}
        current = {name: 0 for name in target_motors}

        # Print table header once
        if display_values:
            print("\n[Zhonglin] Recording ranges of motion...")
            print("=" * 70)
            print(f"{'Joint':<18} {'Current':<12} {'Min':<12} {'Max':<12}")
            print("-" * 70)
            # Print initial rows with placeholder
            for name in target_motors:
                print(f"{name:<18} {'---':<12} {'---':<12} {'---':<12}")
            print("=" * 70)
            print("Move each joint to extremes. Press 'e' to finish.")

            # Move cursor up to data rows (num_motors + 2 lines: separator + instruction)
            num_lines_to_move = len(target_motors) + 2
            print(f"\033[{num_lines_to_move}A", end='', flush=True)  # Move cursor up

        while not (stop_event and stop_event.is_set()):
            for name in target_motors:
                motor = self.motors[name]
                response = self.send_command(f'#{motor.id:03d}PRAD!')
                match = re.search(r'P(\d{4})', response.strip())
                if match:
                    pwm_val = int(match.group(1))
                    current[name] = pwm_val
                    mins[name] = min(mins[name], pwm_val)
                    maxes[name] = max(maxes[name], pwm_val)

            if display_values:
                # Update each row in place
                for idx, name in enumerate(target_motors):
                    # Display actual values, handle initial state
                    min_val = mins[name] if mins[name] < 9999 else 0
                    max_val = maxes[name]
                    print(f"\r{name:<18} {current[name]:<12} {min_val:<12} {max_val:<12}")

                # Move cursor back up to first data row
                if len(target_motors) > 0:
                    print(f"\033[{len(target_motors)}A", end='', flush=True)

            time.sleep(0.05)

        # Move cursor down past the table
        if display_values:
            print(f"\033[{len(target_motors) + 2}B")  # Move down past table

        print("\n[Zhonglin] Recording completed")
        return mins, maxes

