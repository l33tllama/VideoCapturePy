#!/usr/bin/env python3
"""Build script to create distributable executables for Linux, Windows, and macOS using PyInstaller."""

import platform
import subprocess
import sys


def main():
    app_name = "VideoCapturePy"
    entry_point = "main.py"

    pyinstaller_args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", app_name,
        "--add-data", f"config.ini{':' if platform.system() != 'Windows' else ';'}.",
        entry_point,
    ]

    print(f"Building {app_name} for {platform.system()}...")
    subprocess.run(pyinstaller_args, check=True)
    print(f"Build complete. Executable is in the dist/ directory.")


if __name__ == "__main__":
    main()
