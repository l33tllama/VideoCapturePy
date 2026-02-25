import subprocess
import threading
import time

from config import MAX_LATENCY, START_LATENCY


class AudioManager:
    def __init__(self, audio_dev):
        self.latency = START_LATENCY
        self.proc = None
        self.keep_running = True
        self.audio_dev = audio_dev

    def start_audio(self):
        print("Starting audio capture")
        cmd = [
            "alsaloop",
            "-C",
            self.audio_dev,
            "-P",
            "default",
            "-t",
            str(self.latency),
            "-S",
            "1",
            "-A",
            "5",
        ]
        # We capture stderr to "read" the underrun messages
        self.proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)

        # Start a thread to monitor the output
        threading.Thread(target=self.monitor_errors, daemon=True).start()

    def monitor_errors(self):
        while self.proc and self.keep_running:
            line = self.proc.stderr.readline()
            if "underrun" in line.lower():
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
