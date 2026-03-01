import subprocess
import threading
import time

from config import MAX_LATENCY, START_LATENCY


class AudioManager:
    SAMPLE_RATES = [48000, 44100, 96000, 32000, 16000]

    def __init__(self, audio_dev):
        self.latency = START_LATENCY
        self.proc = None
        self.keep_running = True
        self.audio_dev = audio_dev
        self.sample_rate = self.SAMPLE_RATES[0]
        self.sample_format = "S16_LE"
        self.channels = 2
        self._rate_index = 0

    def start_audio(self):
        print("Starting audio capture")
        # Sanitise hw:CARD,DEV — both CARD and DEV must be integers.
        # Earlier versions of the device-detection code could store names
        # (e.g. "hw:5,Audio") which ALSA rejects with "Parameter DEV must
        # be an integer".  Fix up by dropping the non-numeric subdevice.
        capture_dev = self.audio_dev
        import re
        m = re.match(r"^(plug)?hw:(\d+),(.+)$", capture_dev)
        if m and not m.group(3).isdigit():
            # Subdevice is not numeric — default to subdevice 0
            prefix = m.group(1) or ""
            capture_dev = f"{prefix}hw:{m.group(2)},0"
            print(f"[AudioManager] Fixed non-numeric subdevice: {self.audio_dev} -> {capture_dev}")
        # Use plughw: instead of hw: so ALSA can do automatic format/rate conversion
        if capture_dev.startswith("hw:"):
            capture_dev = "plug" + capture_dev
        cmd = [
            "alsaloop",
            "-C",
            capture_dev,
            "-P",
            "default",
            "-t",
            str(self.latency),
            "-r",
            str(self.sample_rate),
            "-f",
            self.sample_format,
            "-c",
            str(self.channels),
        ]
        # We capture stderr to "read" the underrun messages
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Start a thread to monitor the output
        threading.Thread(target=self.monitor_errors, daemon=True).start()

    def monitor_errors(self):
        while self.proc and self.keep_running:
            line = self.proc.stderr.readline()
            if not line:
                if self.proc.poll() is not None:
                    print(f"[AudioManager] alsaloop exited with code {self.proc.returncode}")
                    break
                continue
            print(f"[AudioManager] {line.strip()}")
            if "invalid argument" in line.lower() or "open error" in line.lower():
                # Try next sample rate
                self._rate_index += 1
                if self._rate_index < len(self.SAMPLE_RATES):
                    self.sample_rate = self.SAMPLE_RATES[self._rate_index]
                    print(f"[AudioManager] Retrying with sample rate {self.sample_rate}")
                    self.restart()
                    break
                else:
                    print("[AudioManager] All sample rates exhausted, giving up.")
                    break
            elif "underrun" in line.lower():
                print(
                    f"![Underrun detected] Increasing latency: {self.latency // 1000}ms -> {(self.latency + 20000) // 1000}ms"
                )
                self.latency = min(self.latency + 20000, MAX_LATENCY)
                self.restart()
                break

    def restart(self):
        if self.proc:
            self.proc.terminate()
        time.sleep(0.5)
        self.start_audio()

    def stop(self):
        self.keep_running = False
        if self.proc:
            self.proc.terminate()
