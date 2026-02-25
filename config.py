import configparser
import os
import platform

# --- Configuration (Defaults) ---
DEFAULT_CONFIG = {
    "Linux": {
        "video_fmt": "v4l2",
        "audio_fmt": "alsa",
        "video_dev": "/dev/video0",
        "audio_dev": "hw:0,0",
        "res": "1280x720",
        "fps": "30",
        "quality": "Medium",
        "input_format": "mjpeg",
    },
    "Darwin": {  # macOS
        "video_fmt": "avfoundation",
        "audio_fmt": "avfoundation",
        "video_dev": "default",
        "audio_dev": "default",
        "res": "1920x1080",
        "fps": "30",
        "quality": "High",
        "input_format": "",
    },
    "Windows": {
        "video_fmt": "dshow",
        "audio_fmt": "dshow",
        "video_dev": "video=Integrated Camera",
        "audio_dev": "audio=Microphone (High Definition Audio Device)",
        "res": "1280x720",
        "fps": "30",
        "quality": "High",
        "input_format": "",
    },
}

CONFIG_FILE = "config.ini"

START_LATENCY = 50000  # Start at 50ms
MAX_LATENCY = 200000  # Cap at 200ms

SUPPRESS_OUTPUT = True
