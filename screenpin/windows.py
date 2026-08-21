"""Enumerating top-level app windows and moving them between monitors."""
import ctypes
import os
from ctypes import wintypes

from . import win32 as w
from . import monitors as M

SKIP_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Button",
    "DV2ControlHost", "MsgrIMEWindowClass", "SysShadow", "TaskListThumbnailWnd",
    "Windows.UI.Core.CoreWindow", "ForegroundStaging", "XamlExplorerHostIslandWindow",
    "Windows.Internal.Shell.TabProxyWindow", "EdgeUiInputTopWndClass",
    "NarratorHelperWindow", "MultitaskingViewFrame", "TaskSwitcherWnd",
    "TaskSwitcherOverlayWnd", "Xaml_WindowedPopupClass",
}
SKIP_EXES = {"applicationframehost.exe.ghost", "textinputhost.exe",
             "systemsettings.exe.ghost", "searchhost.exe", "startmenuexperiencehost.exe",
             "shellexperiencehost.exe", "lockapp.exe"}

_OWN_PID = os.getpid()

# hwnd -> (path, pid, exe, cls). Process identity never changes for a live hwnd,
# and OpenProcess per window per tick is by far the most expensive call here.
_info_cache = {}


def _identity(hwnd):
    hit = _info_cache.get(hwnd)
    if hit is not None:
        return hit
    path, pid = w.process_path(hwnd)
    exe = os.path.basename(path).lower() if path else ""
    info = (path, pid, exe, w.class_name(hwnd))
    if len(_info_cache) > 512:
        _info_cache.clear()
    _info_cache[hwnd] = info
    return info


def drop_cache(hwnd=None):
    if hwnd is None:
        _info_cache.clear()
    else:
        _info_cache.pop(hwnd, None)


class WinInfo:
    __slots__ = ("hwnd", "title", "exe", "path", "pid", "cls",
                 "rect", "mon", "maximized", "minimized")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    @property
    def app_key(self):
        return (self.exe or self.cls or "?").lower()

    def __repr__(self):
        return "<Win %s %r on %s>" % (self.exe, self.title[:24],
                                      self.mon.key if self.mon else "-")


# ------------------------------------------------------------------ enumerate


def is_manageable(hwnd, cls=None):
    hw = wintypes.HWND(hwnd)
    if not w.user32.IsWindowVisible(hw):
        return False
    style = w.user32.GetWindowLongPtrW(hw, w.GWL_STYLE)
    ex = w.user32.GetWindowLongPtrW(hw, w.GWL_EXSTYLE)
    if style & w.WS_CHILD:
        return False
    if (ex & w.WS_EX_TOOLWINDOW) and not (ex & w.WS_EX_APPWINDOW):
        return False
    if w.user32.GetWindow(hw, w.GW_OWNER) and not (ex & w.WS_EX_APPWINDOW):
        return False
    if (cls if cls is not None else w.class_name(hwnd)) in SKIP_CLASSES:
        return False
    if not w.window_text(hwnd).strip():
        return False
    if w.is_cloaked(hwnd):
        return False
    if w.user32.IsIconic(hw):
        return True          # minimised windows park at (-32000,-32000, 160x28)
    r = w.get_window_rect(hwnd)
    if not r or r[2] < 80 or r[3] < 40:
        return False
    return True


def list_windows(mons=None, include_self=False):
    """One pass over every top-level window. Kept cheap - runs once per tick."""
    if mons is None:
        mons = M.enumerate_monitors()
    out = []
    alive = set()
    offset = _workspace_offset(mons)

    def cb(hwnd, lparam):
        try:
            hwnd = int(hwnd)
            alive.add(hwnd)
            path, pid, exe, cls = _identity(hwnd)
            if (pid == _OWN_PID and not include_self) or exe in SKIP_EXES:
                return True
            if not is_manageable(hwnd, cls):
                return True
            wp = w.get_placement(hwnd)
            show = wp.showCmd if wp else w.SW_SHOWNORMAL
            minimized = (show == w.SW_SHOWMINIMIZED)
            if minimized and wp:
                # A minimised window lives at (-32000,-32000); the rect it will
                # come back to is the one that means anything.
                rect = _restore_rect(wp, offset)
                mon = M.monitor_of_rect(rect, mons)
            else:
                rect = w.get_window_rect(hwnd)
                mon = M.monitor_of_window(hwnd, mons)
            out.append(WinInfo(
                hwnd=hwnd, title=w.window_text(hwnd), exe=exe, path=path,
                pid=pid, cls=cls, rect=rect, mon=mon,
                maximized=(show == w.SW_SHOWMAXIMIZED),
                minimized=minimized))
        except Exception:
            pass
        return True

    w.user32.EnumWindows(w.EnumWindowsProc(cb), 0)
    for dead in [h for h in _info_cache if h not in alive]:
        _info_cache.pop(dead, None)
    return out


def foreground_window():
    hwnd = w.user32.GetForegroundWindow()
    if not hwnd or not is_manageable(hwnd):
        return None
    return int(hwnd)


# ------------------------------------------------------------------ geometry


def rect_ratio(rect, mon):
    """Window rect -> fractions of the monitor work area (DPI/resolution proof)."""
    if not rect or not mon:
        return None
    wx, wy, ww, wh = mon.work
    ww = max(ww, 1)
    wh = max(wh, 1)
    x, y, cw, ch = rect
    return [round((x - wx) / ww, 5), round((y - wy) / wh, 5),
            round(cw / ww, 5), round(ch / wh, 5)]


def apply_ratio(ratio, mon):
    """Fractions -> a real rect on `mon`, clamped so the window can never sink."""
    wx, wy, ww, wh = mon.work
    if not ratio:
        cw, ch = int(ww * 0.6), int(wh * 0.6)
        return clamp_rect((wx + (ww - cw) // 2, wy + (wh - ch) // 2, cw, ch), mon)
    rx, ry, rw, rh = ratio
    cw = max(160, min(int(round(rw * ww)), ww))
    ch = max(80, min(int(round(rh * wh)), wh))
    x = wx + int(round(rx * ww))
    y = wy + int(round(ry * wh))
    return clamp_rect((x, y, cw, ch), mon)


def clamp_rect(rect, mon):
    """Keep the whole window inside the work area, title bar always reachable."""
    wx, wy, ww, wh = mon.work
    x, y, cw, ch = rect
    cw = max(160, min(cw, ww))
    ch = max(80, min(ch, wh))
    x = max(wx, min(x, wx + ww - cw))
    y = max(wy, min(y, wy + wh - ch))
    return (int(x), int(y), int(cw), int(ch))


def _workspace_offset(mons=None):
    """GetWindowPlacement uses workspace coords: screen minus primary work origin."""
    for m in (mons if mons is not None else M.enumerate_monitors()):
        if m.primary:
            return m.work[0], m.work[1]
    return 0, 0


def _restore_rect(wp, offset):
    r = wp.rcNormalPosition
    return (r.left + offset[0], r.top + offset[1],
            r.right - r.left, r.bottom - r.top)


# ------------------------------------------------------------------ move


def move_window(hwnd, mon, ratio=None, rect=None, keep_maximized=True,
                activate=False):
    """Move a window onto `mon`. Handles maximized and minimized windows."""
    hw = wintypes.HWND(hwnd)
    if not w.user32.IsWindow(hw) or mon is None:
        return False
    target = rect if rect else apply_ratio(ratio, mon)
    target = clamp_rect(target, mon)

    wp = w.get_placement(hwnd)
    show = wp.showCmd if wp else w.SW_SHOWNORMAL

    # Minimized: rewrite the restore rect, do not pop the window open.
    if show == w.SW_SHOWMINIMIZED:
        if not wp:
            return False
        ox, oy = _workspace_offset()
        wp.rcNormalPosition.left = target[0] - ox
        wp.rcNormalPosition.top = target[1] - oy
        wp.rcNormalPosition.right = target[0] + target[2] - ox
        wp.rcNormalPosition.bottom = target[1] + target[3] - oy
        wp.flags = 0
        return bool(w.user32.SetWindowPlacement(hw, ctypes.byref(wp)))

    was_max = (show == w.SW_SHOWMAXIMIZED)
    if was_max:
        w.user32.ShowWindow(hw, w.SW_RESTORE)

    flags = w.SWP_NOZORDER | w.SWP_NOOWNERZORDER
    if not activate:
        flags |= w.SWP_NOACTIVATE
    ok = bool(w.user32.SetWindowPos(hw, wintypes.HWND(0), target[0], target[1],
                                    target[2], target[3], flags))

    if was_max and keep_maximized:
        w.user32.ShowWindow(hw, w.SW_SHOWMAXIMIZED)
    if activate:
        w.force_foreground(hwnd)
    return ok


def move_to_monitor(hwnd, mon, mons=None, activate=True):
    """Move keeping the same relative position/size it had on its old monitor."""
    if mons is None:
        mons = M.enumerate_monitors()
    cur = M.monitor_of_window(hwnd, mons)
    if cur is not None and cur.key == mon.key:
        return False
    wp = w.get_placement(hwnd)
    show = wp.showCmd if wp else w.SW_SHOWNORMAL
    if show == w.SW_SHOWMINIMIZED and wp:
        ox, oy = _workspace_offset()
        r = wp.rcNormalPosition
        src = (r.left + ox, r.top + oy, r.right - r.left, r.bottom - r.top)
    elif show == w.SW_SHOWMAXIMIZED and wp:
        ox, oy = _workspace_offset()
        r = wp.rcNormalPosition
        src = (r.left + ox, r.top + oy, r.right - r.left, r.bottom - r.top)
    else:
        src = w.get_window_rect(hwnd)
    ratio = rect_ratio(src, cur) if cur else None
    return move_window(hwnd, mon, ratio=ratio, activate=activate)


def neighbour_monitor(mon, mons, direction, axis="x"):
    """Monitor next to `mon` in a direction, for any physical arrangement.

    axis "x" is left/right, "y" is up/down; direction is -1 or +1. Picks the
    nearest monitor that actually lies that way (so a 2x2 grid steps sideways
    within its row), and wraps to the far end when there is nothing left.
    """
    if not mons or mon is None:
        return None
    if len(mons) == 1:
        return mons[0]
    horiz = axis != "y"
    cx, cy = mon.center()
    best, best_rank = None, None
    for m in mons:
        if m.key == mon.key:
            continue
        mx, my = m.center()
        along = (mx - cx) if horiz else (my - cy)
        if along * direction <= 0:
            continue                       # not in that direction
        across = abs((my - cy) if horiz else (mx - cx))
        rank = (across, abs(along))        # same row/column first, then nearest
        if best_rank is None or rank < best_rank:
            best, best_rank = m, rank
    if best is not None:
        return best
    # Nothing that way. Wrap only if the monitors actually spread along this
    # axis - otherwise "move up" on a single row should do nothing at all.
    spread = {m.center()[0] if horiz else m.center()[1] for m in mons}
    if len(spread) < 2:
        return None
    order = sorted(mons, key=lambda m: m.center()[0] if horiz else m.center()[1])
    return order[0] if direction > 0 else order[-1]


def evacuate(from_mon, to_mon, mons=None, wins=None):
    """Move every window off one monitor - use right before switching it off.

    Returns the hwnds that moved so the caller can keep their remembered home.
    """
    if mons is None:
        mons = M.enumerate_monitors()
    moved = []
    for win in (list_windows(mons) if wins is None else wins):
        if win.mon and win.mon.key == from_mon.key:
            if move_to_monitor(win.hwnd, to_mon, mons, activate=False):
                moved.append(win.hwnd)
    return moved
