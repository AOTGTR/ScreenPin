"""Monitor enumeration with a stable identity that survives replug / renumbering.

Windows renames displays (\\\\.\\DISPLAY1/2/3) whenever monitors are turned off and
on, so the GDI name is useless as an identity. We build a key out of the physical
panel instead:  <PnP id> | <EDID serial number> | <connector UID>
"""
import re
import winreg

import ctypes
from ctypes import wintypes

from . import win32 as w

_DEVID_RE = re.compile(r"DISPLAY#([^#]+)#([^#]+)#", re.IGNORECASE)
_edid_cache = {}


class Monitor:
    __slots__ = ("key", "pnp", "sn", "uid", "model", "gdi", "hmon",
                 "rect", "work", "primary", "index", "dpi")

    def __init__(self, **kw):
        for s in self.__slots__:
            setattr(self, s, kw.get(s))

    @property
    def w(self):
        return self.rect[2]

    @property
    def h(self):
        return self.rect[3]

    def contains(self, x, y):
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    def center(self):
        rx, ry, rw, rh = self.rect
        return rx + rw // 2, ry + rh // 2

    def as_saved(self):
        return {"key": self.key, "pnp": self.pnp, "sn": self.sn, "uid": self.uid,
                "model": self.model, "size": [self.rect[2], self.rect[3]]}

    def __repr__(self):
        return "<Monitor %s %s %sx%s @%s,%s>" % (
            self.key, self.gdi, self.rect[2], self.rect[3], self.rect[0], self.rect[1])


# ------------------------------------------------------------------ EDID


def _parse_edid(blob):
    """Return (serial_number:int, model_name:str|None) from a raw EDID block."""
    if not blob or len(blob) < 128:
        return None, None
    sn = int.from_bytes(blob[12:16], "little")
    model = None
    for off in (54, 72, 90, 108):
        d = blob[off:off + 18]
        if len(d) < 18 or d[0:3] != b"\x00\x00\x00":
            continue
        if d[3] == 0xFC:  # monitor name descriptor
            txt = d[5:18].split(b"\n")[0].decode("ascii", "ignore").strip()
            if txt:
                model = txt
    return sn, model


def _read_edid(pnp, instance):
    ck = (pnp, instance)
    if ck in _edid_cache:
        return _edid_cache[ck]
    result = (None, None)
    path = "SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\%s\\%s\\Device Parameters" % (
        pnp, instance)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
            blob, _ = winreg.QueryValueEx(k, "EDID")
            result = _parse_edid(bytes(blob))
    except OSError:
        pass
    _edid_cache[ck] = result
    return result


def _identity(device_id):
    """`\\\\?\\DISPLAY#IPS0001#5&x&0&UID4355#{guid}` -> (key, pnp, sn, uid, model)."""
    m = _DEVID_RE.search(device_id or "")
    if not m:
        return None, None, None, None, None
    pnp, instance = m.group(1).upper(), m.group(2)
    uid = ""
    for part in instance.split("&"):
        if part.upper().startswith("UID"):
            uid = part.upper()
    sn, model = _read_edid(pnp, instance)
    sn_s = str(sn) if sn is not None else "?"
    return "%s|%s|%s" % (pnp, sn_s, uid or "?"), pnp, sn_s, uid, model


# ------------------------------------------------------------------ enumerate


def _gdi_to_device_id():
    """Map \\\\.\\DISPLAY1 -> monitor device interface path."""
    out = {}
    i = 0
    while True:
        dd = w.DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not w.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not (dd.StateFlags & w.DISPLAY_DEVICE_ATTACHED_TO_DESKTOP):
            continue
        md = w.DISPLAY_DEVICEW()
        md.cb = ctypes.sizeof(md)
        if w.user32.EnumDisplayDevicesW(dd.DeviceName, 0, ctypes.byref(md),
                                        w.EDD_GET_DEVICE_INTERFACE_NAME):
            out[dd.DeviceName] = (md.DeviceID, md.DeviceString)
    return out


def enumerate_monitors():
    """All active monitors, ordered left-to-right then top-to-bottom."""
    gdi_map = _gdi_to_device_id()
    found = []

    def cb(hmon, hdc, lprc, lparam):
        mi = w.MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if not w.user32.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(mi)):
            return True
        dev_id, dev_str = gdi_map.get(mi.szDevice, ("", ""))
        key, pnp, sn, uid, model = _identity(dev_id)
        if not key:
            # last-resort identity: GDI name + size (unstable, but never crashes)
            key = "GDI|%s|%dx%d" % (mi.szDevice, mi.rcMonitor.right - mi.rcMonitor.left,
                                   mi.rcMonitor.bottom - mi.rcMonitor.top)
            pnp, sn, uid = mi.szDevice, "?", "?"
        if not model or model in ("Generic PnP Monitor", ""):
            model = model or pnp
        found.append(Monitor(
            key=key, pnp=pnp, sn=sn, uid=uid, model=model or pnp,
            gdi=mi.szDevice, hmon=int(hmon),
            rect=mi.rcMonitor.as_tuple(), work=mi.rcWork.as_tuple(),
            primary=bool(mi.dwFlags & w.MONITORINFOF_PRIMARY),
            dpi=96, index=0))
        return True

    w.user32.EnumDisplayMonitors(None, None, w.MonitorEnumProc(cb), 0)
    found.sort(key=lambda m: (m.rect[0], m.rect[1]))

    # de-duplicate identical keys (same model, no serial, same port pattern)
    seen = {}
    for m in found:
        if m.key in seen:
            seen[m.key] += 1
            m.key = "%s#%d" % (m.key, seen[m.key])
        else:
            seen[m.key] = 0
    for i, m in enumerate(found):
        m.index = i
        try:
            m.dpi = int(_monitor_dpi(m.hmon))
        except Exception:
            m.dpi = 96
    return found


def _monitor_dpi(hmon):
    x, y = wintypes.UINT(), wintypes.UINT()
    try:
        shcore = ctypes.WinDLL("shcore")
        if shcore.GetDpiForMonitor(wintypes.HMONITOR(hmon), 0,
                                   ctypes.byref(x), ctypes.byref(y)) == 0:
            return x.value or 96
    except Exception:
        pass
    return 96


def signature(mons):
    """Cheap fingerprint of the whole layout; changes when anything moves."""
    return ";".join("%s@%d,%d,%d,%d" % (m.key, *m.rect) for m in mons)


def monitor_of_window(hwnd, mons):
    hmon = w.user32.MonitorFromWindow(wintypes.HWND(hwnd), w.MONITOR_DEFAULTTONULL)
    if hmon:
        for m in mons:
            if m.hmon == int(hmon):
                return m
    r = w.get_window_rect(hwnd)
    if r:
        cx, cy = r[0] + r[2] // 2, r[1] + r[3] // 2
        for m in mons:
            if m.contains(cx, cy):
                return m
    return None


def monitor_of_rect(rect, mons):
    """Monitor a rect sits on. Used for minimised windows, whose live rect is
    parked far off-screen - their restore rect is the meaningful one."""
    if not rect or not mons:
        return None
    cx = rect[0] + rect[2] // 2
    cy = rect[1] + rect[3] // 2
    for m in mons:
        if m.contains(cx, cy):
            return m
    best, best_area = None, 0
    for m in mons:
        mx, my, mw, mh = m.rect
        ox = max(0, min(rect[0] + rect[2], mx + mw) - max(rect[0], mx))
        oy = max(0, min(rect[1] + rect[3], my + mh) - max(rect[1], my))
        if ox * oy > best_area:
            best, best_area = m, ox * oy
    return best


def monitor_at_cursor(mons):
    p = w.POINT()
    w.user32.GetCursorPos(ctypes.byref(p))
    for m in mons:
        if m.contains(p.x, p.y):
            return m
    return mons[0] if mons else None


# ------------------------------------------------------------------ matching


def match_score(saved, mon):
    """How well a remembered monitor record matches a live monitor. 0 = no match."""
    if not saved:
        return 0
    if saved.get("key") == mon.key:
        return 100
    pnp_ok = saved.get("pnp") and saved.get("pnp") == mon.pnp
    if not pnp_ok:
        return 0
    sn, uid = saved.get("sn"), saved.get("uid")
    if sn and sn != "?" and sn == mon.sn:
        return 80          # same panel, moved to another port
    if uid and uid != "?" and uid == mon.uid:
        return 70          # same port, EDID unreadable
    size = saved.get("size")
    if size and list(size) == [mon.rect[2], mon.rect[3]]:
        return 50          # same model + resolution
    return 30


def resolve_saved(saved_records, mons, min_score=50):
    """Greedy best-match of saved monitor records onto live monitors.

    saved_records: {key: record}. Returns {saved_key: Monitor}.
    """
    pairs = []
    for skey, rec in saved_records.items():
        for mon in mons:
            s = match_score(rec, mon)
            if s >= min_score:
                pairs.append((s, skey, mon))
    pairs.sort(key=lambda t: -t[0])
    out, used_keys, used_mons = {}, set(), set()
    for s, skey, mon in pairs:
        if skey in used_keys or mon.key in used_mons:
            continue
        out[skey] = mon
        used_keys.add(skey)
        used_mons.add(mon.key)
    return out
