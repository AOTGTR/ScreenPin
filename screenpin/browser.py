"""Host the UI in an Edge app-window (a chromeless browser window).

We only borrow the renderer - the window itself is then ours to move around with
the same Win32 code we use for every other app.
"""
import ctypes
import os
import subprocess
import time
import winreg
from ctypes import wintypes

from . import win32 as w

CHROME_CLASSES = {"Chrome_WidgetWin_1", "Chrome_WidgetWin_0"}

CANDIDATES = [
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                 r"Google\Chrome\Application\chrome.exe"),
    os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 r"Google\Chrome\Application\chrome.exe"),
]


def find_browser():
    for name in ("msedge.exe", "chrome.exe"):
        try:
            with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + name
            ) as k:
                path = winreg.QueryValueEx(k, "")[0]
                if path and os.path.isfile(path):
                    return path
        except OSError:
            pass
    for p in CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


class AppWindow:
    """Launch, find, move, hide and show the UI window."""

    def __init__(self, url, profile_dir, title_match="ScreenPin"):
        self.url = url
        self.profile_dir = profile_dir
        self.title_match = title_match
        self.exe = find_browser()
        self.proc = None
        self.hwnd = None

    @property
    def available(self):
        return bool(self.exe)

    # ------------------------------------------------------------- lifecycle
    def launch(self, rect=None):
        if not self.exe:
            return False
        if self.alive():
            self.show()
            return True
        os.makedirs(self.profile_dir, exist_ok=True)
        args = [
            self.exe,
            "--app=" + self.url,
            "--user-data-dir=" + self.profile_dir,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-extensions",
            "--noerrdialogs",
            "--disable-translate",
            "--disable-popup-blocking",
            "--disable-component-update",
            "--disable-features=Translate,TranslateUI,msEdgeTranslate,"
            "msEdgeSplitScreen,msWebOOUI,msPdfOOUI,EdgeDiscoverPage,"
            "msEdgeSidebar,msEdgeShoppingAssistant,msEntityExtraction,"
            "msEdgeCollections,EdgeAutofill",
        ]
        if rect:
            args += ["--window-position=%d,%d" % (rect[0], rect[1]),
                     "--window-size=%d,%d" % (rect[2], rect[3])]
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=0x08000000)  # NO_WINDOW
        self.hwnd = None
        return True

    def alive(self):
        if self.hwnd and w.user32.IsWindow(wintypes.HWND(self.hwnd)):
            return True
        self.hwnd = None
        return False

    def find_window(self):
        """Locate our browser window; returns hwnd or None."""
        if self.alive():
            return self.hwnd
        want_pid = self.proc.pid if self.proc else 0
        found = []

        def cb(hwnd, _lp):
            hwnd = int(hwnd)
            if not w.user32.IsWindowVisible(wintypes.HWND(hwnd)):
                return True
            if w.class_name(hwnd) not in CHROME_CLASSES:
                return True
            title = w.window_text(hwnd)
            if self.title_match not in title:
                return True
            pid = wintypes.DWORD()
            w.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd),
                                              ctypes.byref(pid))
            found.append((hwnd, pid.value == want_pid))
            return True

        w.user32.EnumWindows(w.EnumWindowsProc(cb), 0)
        if not found:
            return None
        found.sort(key=lambda t: 0 if t[1] else 1)
        self.hwnd = found[0][0]
        return self.hwnd

    def wait_for_window(self, timeout=8.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.find_window():
                return self.hwnd
            time.sleep(0.08)
        return None

    # ------------------------------------------------------------- window ops
    def show(self, foreground=True):
        hwnd = self.find_window()
        if not hwnd:
            return False
        h = wintypes.HWND(hwnd)
        if w.user32.IsIconic(h):
            w.user32.ShowWindow(h, w.SW_RESTORE)
        else:
            w.user32.ShowWindow(h, w.SW_SHOW)
        if foreground:
            w.force_foreground(hwnd)
        return True

    def hide(self):
        if self.alive():
            w.user32.ShowWindow(wintypes.HWND(self.hwnd), w.SW_HIDE)
            return True
        return False

    def is_visible(self):
        return bool(self.alive()
                    and w.user32.IsWindowVisible(wintypes.HWND(self.hwnd))
                    and not w.user32.IsIconic(wintypes.HWND(self.hwnd)))

    def rect(self):
        return w.get_window_rect(self.hwnd) if self.alive() else None

    def close(self):
        if self.alive():
            w.user32.PostMessageW(wintypes.HWND(self.hwnd), w.WM_CLOSE, 0, 0)
        if self.proc:
            try:
                self.proc.wait(timeout=2.5)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
        self.hwnd = None
        self.proc = None
