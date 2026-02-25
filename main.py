import configparser
import os
import platform
import subprocess
import sys

from PyQt6.QtWidgets import QApplication

from capture_gui import CaptureGUI


def get_linux_font_scale():
    """Detect the host Linux font/UI scale factor."""
    if platform.system() != "Linux":
        return 1.0

    # Try GNOME/GTK text-scaling-factor
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "text-scaling-factor"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            scale = float(result.stdout.strip())
            if scale > 0:
                return scale
    except Exception:
        pass

    # Try KDE Plasma global scale
    try:
        kde_config = os.path.expanduser("~/.config/kdeglobals")
        if os.path.exists(kde_config):
            cfg = configparser.ConfigParser()
            cfg.read(kde_config)
            scale = cfg.getfloat("KDE", "ScaleFactor", fallback=0)
            if scale > 0:
                return scale
    except Exception:
        pass

    # Fallback: check GDK_SCALE env var
    try:
        gdk_scale = os.environ.get("GDK_SCALE")
        if gdk_scale:
            return float(gdk_scale)
    except Exception:
        pass

    # Fallback: check QT_SCALE_FACTOR env var
    try:
        qt_scale = os.environ.get("QT_SCALE_FACTOR")
        if qt_scale:
            return float(qt_scale)
    except Exception:
        pass

    return 1.0


def _is_elementary_os():
    """Check if running on elementaryOS."""
    try:
        with open("/etc/os-release") as f:
            content = f.read().lower()
            return "elementary" in content
    except Exception:
        return False


def _xcb_cursor_available():
    """Check whether libxcb-cursor is loadable (required by Qt >= 6.5 for xcb)."""
    import ctypes.util

    return ctypes.util.find_library("xcb-cursor") is not None


def _ensure_elementary_shadows():
    """Work around missing window shadows on elementaryOS.

    Gala (the elementaryOS compositor) does not reliably draw drop shadows
    for Qt/non-GTK windows when running under Wayland.  Forcing the XCB
    (X11) platform backend makes Gala treat the window like any other
    X11 client and apply its normal shadow decoration.

    Skipped when libxcb-cursor is not installed, since Qt >= 6.5 requires
    it for the xcb plugin to load.
    """
    if not _is_elementary_os():
        return

    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland" and _xcb_cursor_available():
        # Only override if the user hasn't already chosen a platform
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")


def main():
    # Detect Linux font scale and apply it to Qt before creating QApplication
    scale = get_linux_font_scale()
    if scale != 1.0:
        os.environ.setdefault("QT_SCALE_FACTOR", str(scale))

    # Fix missing drop shadows on elementaryOS
    _ensure_elementary_shadows()

    try:
        app = QApplication(sys.argv)
    except RuntimeError:
        # xcb plugin may fail if libxcb-cursor0 is missing (Qt >= 6.5);
        # fall back to the default platform plugin.
        if os.environ.pop("QT_QPA_PLATFORM", None):
            app = QApplication(sys.argv)
        else:
            raise
    window = CaptureGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
