import configparser
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from tarfile import SUPPORTED_TYPES

from PyQt6.QtCore import QProcess, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio_manager import AudioManager
from config import CONFIG_FILE, DEFAULT_CONFIG, SUPPRESS_OUTPUT
from settings_dialog import SettingsDialog


class CaptureGUI(QMainWindow):
    _log_signal = pyqtSignal(str)
    _status_signal = pyqtSignal(str)
    _finished_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Low-Latency Capture")
        self.setMinimumWidth(400)

        self.os_type = platform.system()
        self.load_settings()

        self.v_proc = None
        self.a_proc = None  # Used for separate audio loop if needed (Linux)
        self.am = None
        self._linux_ffplay_proc = None

        self._log_signal.connect(self._append_log)
        self._status_signal.connect(self._set_status)
        self._finished_signal.connect(self.on_process_finished)
        self.init_ui()

    def load_settings(self):
        self.config = configparser.ConfigParser()
        defaults = DEFAULT_CONFIG.get(self.os_type, DEFAULT_CONFIG["Linux"])

        if os.path.exists(CONFIG_FILE):
            self.config.read(CONFIG_FILE)
            if self.os_type in self.config:
                self.current_settings = {
                    "video_fmt": self.config.get(
                        self.os_type, "video_fmt", fallback=defaults["video_fmt"]
                    ),
                    "audio_fmt": self.config.get(
                        self.os_type, "audio_fmt", fallback=defaults["audio_fmt"]
                    ),
                    "video_dev": self.config.get(
                        self.os_type, "video_dev", fallback=defaults["video_dev"]
                    ),
                    "audio_dev": self.config.get(
                        self.os_type, "audio_dev", fallback=defaults["audio_dev"]
                    ),
                    "res": self.config.get(
                        self.os_type, "res", fallback=defaults["res"]
                    ),
                    "fps": self.config.get(
                        self.os_type, "fps", fallback=defaults.get("fps", "")
                    ),
                    "quality": self.config.get(
                        self.os_type,
                        "quality",
                        fallback=defaults.get("quality", "High"),
                    ),
                    "input_format": self.config.get(
                        self.os_type,
                        "input_format",
                        fallback=defaults.get("input_format", ""),
                    ),
                }
            else:
                self.current_settings = defaults.copy()
        else:
            self.current_settings = defaults.copy()

        # On Linux, auto-detect a valid capture device if the configured one
        # is not a real capture node (e.g. metadata-only /dev/videoN).
        if self.os_type == "Linux":
            self._validate_linux_video_device()

    def save_settings(self):
        if self.os_type not in self.config:
            self.config.add_section(self.os_type)

        for key, value in self.current_settings.items():
            self.config.set(self.os_type, key, value)

        with open(CONFIG_FILE, "w") as configfile:
            self.config.write(configfile)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Start/Stop Button (prominent, green)
        self.start_btn = QPushButton("Start Capture")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-size: 16px; "
            "font-weight: bold; padding: 12px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:pressed { background-color: #3d8b40; }"
        )
        self.start_btn.clicked.connect(self.toggle_capture)
        layout.addWidget(self.start_btn)

        # Settings Button
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)

        self.status_label = QLabel("Status: Idle")
        layout.addWidget(self.status_label)

        # Check for ffplay
        self.check_ffplay()

        layout.addWidget(QLabel(f"System: {self.os_type}"))

        # Display current settings
        self.info_label = QLabel()
        layout.addWidget(self.info_label)

        # Command Preview
        layout.addWidget(QLabel("FFplay Command Preview:"))
        cmd_layout = QHBoxLayout()
        self.cmd_preview = QLineEdit()
        self.cmd_preview.setReadOnly(True)
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy_command_to_clipboard)
        cmd_layout.addWidget(self.cmd_preview)
        cmd_layout.addWidget(self.copy_btn)
        layout.addLayout(cmd_layout)

        # Initialize info label and command preview AFTER widgets are created
        self.update_info_label()

        # Log output
        layout.addWidget(QLabel("Logs:"))
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)

        # Clear logs button
        self.clear_logs_btn = QPushButton("Clear Logs")
        self.clear_logs_btn.clicked.connect(self.log_output.clear)
        layout.addWidget(self.clear_logs_btn)

    def update_info_label(self):
        fps_info = (
            f" @ {self.current_settings['fps']} FPS"
            if self.current_settings.get("fps")
            else ""
        )
        quality_info = (
            f" [{self.current_settings['quality']}]"
            if self.current_settings.get("quality")
            else ""
        )
        self.info_label.setText(
            f"Video: {self.current_settings['video_dev']} ({self.current_settings['res']}{fps_info}){quality_info}\n"
            f"Audio: {self.current_settings['audio_dev']}"
        )
        self.update_command_preview()

    def update_command_preview(self):
        video_dev = self.current_settings["video_dev"]
        audio_dev = self.current_settings["audio_dev"]
        res = self.current_settings["res"]
        fps = self.current_settings.get("fps", "")
        quality = self.current_settings.get("quality", "High")

        input_format = self.current_settings.get("input_format", "")

        cmd = ["ffplay"]
        if self.os_type == "Linux":
            cmd += ["-f", self.current_settings["video_fmt"]]
            if input_format:
                cmd += ["-input_format", input_format]

            # Apply quality presets for Linux (v4l2)
            if quality == "Low":
                cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                cmd += ["-video_size", "1280x720"]
            else:  # High or Manual
                cmd += ["-video_size", res]

            if fps:
                cmd += ["-framerate", fps]

            cmd += [
                "-i",
                video_dev,
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-an",
                "-framedrop",
            ]
        elif self.os_type == "Darwin":
            cmd += [
                "-f",
                self.current_settings["video_fmt"],
            ]

            # Apply quality presets for macOS (avfoundation)
            if quality == "Low":
                cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                cmd += ["-video_size", "1280x720"]
            else:
                cmd += ["-video_size", res]

            if fps:
                cmd += ["-framerate", fps]
            cmd += [
                "-i",
                f"{video_dev}:{audio_dev}",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-alwaysontop",
            ]
        elif self.os_type == "Windows":
            cmd += [
                "-f",
                self.current_settings["video_fmt"],
            ]

            # Apply quality presets for Windows (dshow)
            if quality == "Low":
                cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                cmd += ["-video_size", "1280x720"]
            else:
                cmd += ["-video_size", res]

            if fps:
                cmd += ["-framerate", fps]
            cmd += [
                "-i",
                f"video={video_dev}:audio={audio_dev}",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-alwaysontop",
            ]

        # Join with quotes if necessary, though simple join is usually enough for terminal
        self.cmd_preview.setText(" ".join(cmd))

    def copy_command_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.cmd_preview.text())
        self.status_label.setText("Status: Command copied to clipboard")

    def get_available_devices(self):
        video_devices = []
        audio_devices = []

        if self.os_type == "Darwin":
            try:
                # ffmpeg output for device listing is usually in stderr
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-list_devices",
                        "true",
                        "-f",
                        "avfoundation",
                        "-i",
                        "",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = result.stderr

                # Parse output
                section = None
                for line in output.splitlines():
                    if "AVFoundation video devices" in line:
                        section = "video"
                        continue
                    elif "AVFoundation audio devices" in line:
                        section = "audio"
                        continue

                    if section and "[" in line and "]" in line:
                        # Format: [AVFoundation indev @ 0x...] [0] FaceTime HD Camera
                        try:
                            parts = line.split("]", 2)
                            if len(parts) >= 3:
                                dev_id = parts[1].split("[")[-1].strip()
                                name = parts[2].strip()
                                if section == "video":
                                    video_devices.append((name, dev_id))
                                else:
                                    audio_devices.append((name, dev_id))
                        except Exception:
                            continue
            except Exception as e:
                print(f"Error listing devices on macOS: {e}")

        elif self.os_type == "Windows":
            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-list_devices",
                        "true",
                        "-f",
                        "dshow",
                        "-i",
                        "dummy",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                output = result.stderr

                # Parsing dshow output is tricky as it uses quotes
                # [dshow @ 000...] "Integrated Camera" (video)
                # [dshow @ 000...]   DirectShow video devices
                # [dshow @ 000...]  "Integrated Camera"
                # [dshow @ 000...]     Alternative name "@device_pnp_..."

                section = None
                lines = output.splitlines()
                for i, line in enumerate(lines):
                    if "DirectShow video devices" in line:
                        section = "video"
                        continue
                    elif "DirectShow audio devices" in line:
                        section = "audio"
                        continue

                    if section and '"' in line:
                        name = line.split('"')[1]
                        # The dev_id for dshow can be the name or the alternative name.
                        # Using the name prefixed with video= or audio= is standard.
                        if section == "video":
                            video_devices.append((name, name))
                        else:
                            audio_devices.append((name, name))
            except Exception as e:
                print(f"Error listing devices on Windows: {e}")

        elif self.os_type == "Linux":
            # Video devices via v4l2-ctl if available, else /dev/video*
            # Filter to only include actual capture devices (not metadata nodes)
            if shutil.which("v4l2-ctl"):
                try:
                    output = subprocess.check_output(
                        ["v4l2-ctl", "--list-devices"], text=True
                    )
                    lines = output.splitlines()
                    current_name = ""
                    for line in lines:
                        if line and not line.startswith("\t"):
                            current_name = line.split("(")[0].strip()
                        elif line.startswith("\t"):
                            dev_path = line.strip()
                            # Check if this is a capture device (not metadata)
                            if self._is_v4l2_capture_device(dev_path):
                                video_devices.append(
                                    (current_name or dev_path, dev_path)
                                )
                except Exception:
                    pass

            if not video_devices:
                import glob

                for dev in sorted(glob.glob("/dev/video*")):
                    if self._is_v4l2_capture_device(dev):
                        video_devices.append((dev, dev))

            # Audio devices via arecord -l
            if shutil.which("arecord"):
                try:
                    output = subprocess.check_output(["arecord", "-l"], text=True)
                    # card 0: PCH [HDA Intel PCH], device 0: ALC285 Analog [ALC285 Analog]
                    for line in output.splitlines():
                        if line.startswith("card"):
                            m = re.match(r"card\s+(\d+):.*device\s+(\d+):", line)
                            if m:
                                card = m.group(1)
                                device = m.group(2)
                                parts = line.split(":")
                                name = parts[1].split("[")[1].split("]")[0]
                                audio_devices.append((name, f"hw:{card},{device}"))
                except Exception:
                    pass

            if not audio_devices:
                audio_devices.append(("Default", "default"))

        return video_devices, audio_devices

    def _validate_linux_video_device(self):
        """Ensure the configured video device is a real capture node.

        USB capture cards often register multiple /dev/videoN nodes — only
        some are actual Video Capture devices.  If the current setting
        points to a metadata-only node (which causes the
        ``VIDIOC_G_INPUT: Inappropriate ioctl`` error), automatically
        switch to the first valid capture device found.
        """
        dev = self.current_settings.get("video_dev", "")
        if not dev.startswith("/dev/video"):
            return
        if self._is_v4l2_capture_device(dev):
            return

        # Current device is not a capture node — try to find one.
        import glob

        for candidate in sorted(glob.glob("/dev/video*")):
            if self._is_v4l2_capture_device(candidate):
                print(
                    f"[auto-detect] {dev} is not a capture device, switching to {candidate}"
                )
                self.current_settings["video_dev"] = candidate
                self.save_settings()
                return

    def _is_v4l2_capture_device(self, dev_path):
        """Check if a v4l2 device node is an actual video capture device."""
        if not shutil.which("v4l2-ctl"):
            return True
        try:
            output = subprocess.check_output(
                ["v4l2-ctl", "-d", dev_path, "--all"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            return "Video Capture" in output
        except Exception:
            return False

    def open_settings(self):
        self.status_label.setText("Status: Scanning for devices...")
        QApplication.processEvents()  # Ensure UI updates

        video_devices, audio_devices = self.get_available_devices()

        dialog = SettingsDialog(
            self.current_settings, video_devices, audio_devices, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_settings = dialog.get_settings()
            self.save_settings()
            self.update_info_label()
            self.status_label.setText("Status: Settings updated")
        else:
            self.status_label.setText("Status: Idle")

    def check_ffplay(self):
        if not shutil.which("ffplay"):
            QMessageBox.warning(
                self,
                "Warning",
                "ffplay was not found on your system. Please install ffmpeg/ffplay to use this application.",
            )
            self.start_btn.setEnabled(False)
            self.status_label.setText("Status: Error (ffplay missing)")
            return False
        return True

    def toggle_capture(self):
        if self._linux_ffplay_proc and self._linux_ffplay_proc.poll() is None:
            self.stop_capture()
        elif self.v_proc and self.v_proc.state() == QProcess.ProcessState.Running:
            self.stop_capture()
        else:
            self.start_capture()

    def start_capture(self):
        video_dev = self.current_settings["video_dev"]
        audio_dev = self.current_settings["audio_dev"]
        res = self.current_settings["res"]
        fps = self.current_settings.get("fps", "")
        quality = self.current_settings.get("quality", "High")

        input_format = self.current_settings.get("input_format", "")

        # Pre-flight check: warn if the device is not a capture node
        if self.os_type == "Linux" and video_dev.startswith("/dev/video"):
            if not self._is_v4l2_capture_device(video_dev):
                self._log_signal.emit(
                    f"\n⚠ {video_dev} is not a video capture device "
                    "(likely a metadata node). Open Settings to pick a "
                    "valid capture device, or the stream will fail."
                )
                self._status_signal.emit(
                    "Status: Warning — device may not be a capture node"
                )

        ffplay_cmd = ["ffplay"]

        if self.os_type == "Linux":
            ffplay_cmd += ["-f", self.current_settings["video_fmt"]]
            if input_format:
                ffplay_cmd += ["-input_format", input_format]

            if quality == "Low":
                ffplay_cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                ffplay_cmd += ["-video_size", "1280x720"]
            else:
                ffplay_cmd += ["-video_size", res]

            if fps:
                ffplay_cmd += ["-framerate", fps]

            ffplay_cmd += [
                "-i",
                video_dev,
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-an",
                "-framedrop",
            ]

            # Use subprocess.Popen on Linux — QProcess causes nan/no-frame
            # issues with v4l2 capture devices.
            # Write stderr to a temp file instead of piping — piping stderr
            # can cause ffplay to block or fail to display video on Linux.
            self._linux_stderr_file = tempfile.NamedTemporaryFile(
                mode="w+", prefix="ffplay_stderr_", suffix=".log", delete=False
            )
            self._linux_ffplay_proc = subprocess.Popen(
                ffplay_cmd, stderr=self._linux_stderr_file
            )
            self.am = AudioManager(audio_dev)
            self.am.start_audio()

            # Monitor stderr file in a background thread
            self._linux_stderr_thread = threading.Thread(
                target=self._monitor_linux_ffplay, daemon=True
            )
            self._linux_stderr_thread.start()

            self.start_btn.setText("Stop Capture")
            self.start_btn.setStyleSheet(
                "QPushButton { background-color: #f44336; color: white; font-size: 16px; "
                "font-weight: bold; padding: 12px; border-radius: 6px; }"
                "QPushButton:hover { background-color: #da190b; }"
                "QPushButton:pressed { background-color: #c1170a; }"
            )
            self.status_label.setText("Status: Capturing...")

            # Poll for process exit in a thread
            def _wait_exit():
                self._linux_ffplay_proc.wait()
                self._finished_signal.emit()

            threading.Thread(target=_wait_exit, daemon=True).start()
            return

        elif self.os_type == "Darwin":  # macOS
            # On macOS, ffplay can handle both video and audio together
            # Note: -i "video_index:audio_index"
            ffplay_cmd += [
                "-f",
                self.current_settings["video_fmt"],
            ]

            if quality == "Low":
                ffplay_cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                ffplay_cmd += ["-video_size", "1280x720"]
            else:
                ffplay_cmd += ["-video_size", res]

            if fps:
                ffplay_cmd += ["-framerate", fps]

            # If names are used, ensure they are in the format expected by avfoundation
            # But here we assume video_dev and audio_dev are what the user selected (index or name)
            ffplay_cmd += [
                "-i",
                f"{video_dev}:{audio_dev}",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-alwaysontop",
            ]
        elif self.os_type == "Windows":
            # On Windows, ffplay can handle both via dshow
            ffplay_cmd += [
                "-f",
                self.current_settings["video_fmt"],
            ]

            if quality == "Low":
                ffplay_cmd += ["-video_size", "640x480"]
            elif quality == "Medium":
                ffplay_cmd += ["-video_size", "1280x720"]
            else:
                ffplay_cmd += ["-video_size", res]

            if fps:
                ffplay_cmd += ["-framerate", fps]
            ffplay_cmd += [
                "-i",
                f"video={video_dev}:audio={audio_dev}",
                "-fflags",
                "nobuffer",
                "-flags",
                "low_delay",
                "-framedrop",
                "-alwaysontop",
            ]
        else:
            QMessageBox.critical(self, "Error", f"Unsupported OS: {self.os_type}")
            return

        self.v_proc = QProcess()
        self.v_proc.finished.connect(self.on_process_finished)
        self.v_proc.readyReadStandardOutput.connect(self.handle_stdout)
        self.v_proc.readyReadStandardError.connect(self.handle_stderr)
        self.v_proc.start("ffplay", ffplay_cmd[1:])

        if self.v_proc.waitForStarted():
            self.start_btn.setText("Stop Capture")
            self.start_btn.setStyleSheet(
                "QPushButton { background-color: #f44336; color: white; font-size: 16px; "
                "font-weight: bold; padding: 12px; border-radius: 6px; }"
                "QPushButton:hover { background-color: #da190b; }"
                "QPushButton:pressed { background-color: #c1170a; }"
            )
            self.status_label.setText("Status: Capturing...")
        else:
            self.status_label.setText("Status: Failed to start")

    def _monitor_linux_ffplay(self):
        """Tail the stderr log file from the Linux ffplay process."""
        proc = self._linux_ffplay_proc
        log_path = self._linux_stderr_file.name
        time.sleep(0.5)  # Let ffplay start writing
        try:
            with open(log_path, "r") as f:
                while proc.poll() is None:
                    line = f.readline()
                    if line:
                        line = line.strip()
                        if line:
                            if not SUPPRESS_OUTPUT:
                                print(f"[ffplay STDERR] {line}")
                            self._log_signal.emit(f"[ffplay STDERR] {line}")
                            self._check_v4l2_errors(line)
                    else:
                        time.sleep(0.1)
                # Read remaining lines after process exits
                for line in f:
                    line = line.strip()
                    if line:
                        if not SUPPRESS_OUTPUT:
                            print(f"[ffplay STDERR] {line}")
                        self._log_signal.emit(f"[ffplay STDERR] {line}")
        except Exception as e:
            print(f"Error reading ffplay stderr log: {e}")
        finally:
            try:
                os.unlink(log_path)
            except OSError:
                pass

    @pyqtSlot(str)
    def _append_log(self, text):
        self.log_output.appendPlainText(text)

    @pyqtSlot(str)
    def _set_status(self, text):
        self.status_label.setText(text)

    def stop_capture(self):
        if hasattr(self, "_linux_ffplay_proc") and self._linux_ffplay_proc:
            self._linux_ffplay_proc.terminate()
            self._linux_ffplay_proc = None
        if self.v_proc:
            self.v_proc.terminate()
        if self.a_proc:
            self.a_proc.terminate()
        if self.am:
            self.am.stop()

    def on_process_finished(self):
        self.start_btn.setText("Start Capture")
        self.start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-size: 16px; "
            "font-weight: bold; padding: 12px; border-radius: 6px; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:pressed { background-color: #3d8b40; }"
        )
        self.status_label.setText("Status: Stopped")
        self._linux_ffplay_proc = None
        if self.a_proc:
            self.a_proc.terminate()
        if self.am:
            self.am.stop()

    def handle_stdout(self):
        if not SUPPRESS_OUTPUT:
            data = self.v_proc.readAllStandardOutput().data().decode().strip()
            if data:
                print(f"[ffplay STDOUT] {data}")
                self.log_output.appendPlainText(f"[ffplay STDOUT] {data}")

    def handle_stderr(self):
        if not SUPPRESS_OUTPUT:
            data = self.v_proc.readAllStandardError().data().decode().strip()
            if data:
                print(f"[ffplay STDERR] {data}")
                self.log_output.appendPlainText(f"[ffplay STDERR] {data}")
                self._check_v4l2_errors(data)

    def _check_v4l2_errors(self, output):
        """Detect common v4l2 errors and show helpful guidance."""
        if "No space left on device" in output:
            self._status_signal.emit(
                "Status: USB bandwidth error — try lower resolution/fps"
            )
            self._log_signal.emit(
                "\n⚠ USB bandwidth exhausted. Your camera cannot stream at the "
                "requested resolution/framerate over USB. Try:\n"
                "  • Lower resolution (e.g. 1280x720 or 640x480)\n"
                "  • Lower framerate (e.g. 15 or 24)\n"
                "  • Disconnect other USB devices on the same hub\n"
                "  • Use a USB 3.0 port if available"
            )
        elif "Inappropriate ioctl for device" in output:
            self._status_signal.emit("Status: Wrong device node — not a capture device")
            self._log_signal.emit(
                "\n⚠ This device node is not a video capture device (likely a "
                "metadata node). Use Settings to select a different device."
            )
        elif (
            "Invalid argument" in output
            or "No such file or directory" in output
            and "input_format" not in output
        ):
            if "video_size" in output.lower() or "pixel format" in output.lower():
                self._log_signal.emit(
                    "\n⚠ The device may not support the requested resolution or "
                    "pixel format. Try changing Input Format in Settings "
                    "(e.g. yuyv422 instead of mjpeg) or use a lower resolution."
                )
        elif "Could not find codec parameters" in output:
            self._status_signal.emit(
                "Status: Format/resolution not supported by device"
            )
            self._log_signal.emit(
                "\n⚠ Could not negotiate capture parameters. The device may not "
                "support the requested input format or resolution. Try:\n"
                "  • Change Input Format (e.g. yuyv422 or leave blank for auto)\n"
                "  • Lower the resolution\n"
                "  • Check the device supports the requested framerate"
            )

    def closeEvent(self, event):
        self.stop_capture()
        event.accept()
