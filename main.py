"""ScreenPin - move apps between monitors fast, and remember where they live.

Run with pythonw.exe (or ScreenPin.vbs) for a windowless start.
Pass --tray to start minimised to the notification area.
"""
import ctypes
import os
import sys
import traceback

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
           else os.path.dirname(os.path.abspath(__file__)))
if not FROZEN and APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

LOG = os.path.join(APP_DIR, "screenpin.log")
MUTEX = r"Global\ScreenPin.SingleInstance.v1"


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def already_running():
    """A second launch just raises the window of the first one."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, MUTEX)
    if handle and ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        from screenpin import msgloop as ML
        hwnd = u32.FindWindowW(ML.WND_CLASS, None)
        if hwnd:
            u32.PostMessageW(hwnd, u32.RegisterWindowMessageW(ML.SHOW_MSG_NAME), 0, 0)
        return True
    globals()["_mutex"] = handle          # keep the handle alive for our lifetime
    return False


def main():
    if already_running():
        return 0
    from screenpin.app import ScreenPin
    app = ScreenPin()
    app.run(start_hidden="--tray" in sys.argv)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        log("=" * 60)
        log(traceback.format_exc())
        try:
            ctypes.WinDLL("user32").MessageBoxW(
                None, "ScreenPin error - see screenpin.log\n\n"
                      + traceback.format_exc()[-900:], "ScreenPin", 0x10)
        except Exception:
            pass
        sys.exit(1)
