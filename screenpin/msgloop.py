"""Background Win32 thread: global hotkeys, tray icon, instant display events.

tkinter owns the main thread, so everything here runs in its own thread and talks
to the UI through a queue.
"""
import ctypes
import queue
import threading
from ctypes import wintypes

from . import win32 as w
from .picker import Picker

TPM_RETURNCMD = 0x100
WM_TRAY = w.WM_APP + 1
WM_PUMP = w.WM_APP + 2
SHOW_MSG_NAME = "ScreenPinShowWindow"
WND_CLASS = "ScreenPinHiddenWnd"

ID_SHOW = 1
ID_AUTORESTORE = 2
ID_HOTKEYS = 3
ID_RELOAD = 4
ID_EXIT = 9
ID_MON_BASE = 100
ID_SLOT_BASE = 200

VK = {
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28, "SPACE": 0x20,
    "ENTER": 0x0D, "RETURN": 0x0D, "TAB": 0x09, "ESC": 0x1B, "ESCAPE": 0x1B,
    "HOME": 0x24, "END": 0x23, "PGUP": 0x21, "PGDN": 0x22,
    "INS": 0x2D, "DEL": 0x2E, "BACKSPACE": 0x08,
}
for _i in range(1, 25):
    VK["F%d" % _i] = 0x6F + _i
for _i in range(10):
    VK["NUM%d" % _i] = 0x60 + _i

MODS = {"CTRL": w.MOD_CONTROL, "CONTROL": w.MOD_CONTROL, "ALT": w.MOD_ALT,
        "SHIFT": w.MOD_SHIFT, "WIN": w.MOD_WIN}


def parse_hotkey(text):
    """'Ctrl+Alt+Left' -> (modifier flags, virtual key). None if unparseable."""
    if not text:
        return None
    mods, vk = 0, None
    for part in str(text).replace(" ", "").split("+"):
        if not part:
            continue
        up = part.upper()
        if up in MODS:
            mods |= MODS[up]
        elif up in VK:
            vk = VK[up]
        elif len(up) == 1:
            vk = ord(up)
    if vk is None or mods == 0:
        return None
    return mods | w.MOD_NOREPEAT, vk


class MsgLoop(threading.Thread):
    daemon = True

    def __init__(self, out_queue=None, tip="ScreenPin", icon_path=None):
        super().__init__(name="screenpin-msgloop")
        self.out = out_queue or queue.Queue()
        self.hwnd = None
        self.tip = tip
        self.icon_path = icon_path
        self.hicon = None
        self._ready = threading.Event()
        self._inbox = queue.Queue()
        self._hotkeys = {}          # id -> action name
        self._menu_data = {"monitors": [], "auto_restore": True, "hotkeys": True}
        self._wndproc_ref = None
        self._tray_added = False
        self._taskbar_msg = 0
        self._show_msg = 0
        self.picker = None

    # ------------------------------------------------------------- public
    def send(self, cmd, arg=None):
        self._inbox.put((cmd, arg))
        if self.hwnd:
            w.user32.PostMessageW(wintypes.HWND(self.hwnd), WM_PUMP, 0, 0)

    def wait_ready(self, timeout=5.0):
        return self._ready.wait(timeout)

    def set_menu_data(self, data):
        self._menu_data = data

    # ------------------------------------------------------------- thread
    def run(self):
        self.picker = Picker(self.out)
        self._create_window()
        self._load_icon()
        self._add_tray()
        self._ready.set()
        msg = wintypes.MSG()
        while True:
            r = w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))
        self._remove_tray()

    def _create_window(self):
        hinst = w.kernel32.GetModuleHandleW(None)
        cls = w.WNDCLASSEXW()
        cls.cbSize = ctypes.sizeof(cls)
        self._wndproc_ref = w.WNDPROC(self._wndproc)
        cls.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        cls.hInstance = hinst
        cls.lpszClassName = "ScreenPinHiddenWnd"
        cls.hCursor = w.user32.LoadCursorW(None, ctypes.c_wchar_p(w.IDC_ARROW))
        w.user32.RegisterClassExW(ctypes.byref(cls))
        self.hwnd = w.user32.CreateWindowExW(
            0, "ScreenPinHiddenWnd", "ScreenPin", 0, 0, 0, 0, 0,
            None, None, hinst, None)
        self._taskbar_msg = w.user32.RegisterWindowMessageW("TaskbarCreated")
        self._show_msg = w.user32.RegisterWindowMessageW(SHOW_MSG_NAME)

    def _load_icon(self):
        if self.icon_path:
            try:
                h = w.user32.LoadImageW(None, self.icon_path, 1, 0, 0, 0x10 | 0x40)
                if h:
                    self.hicon = h
                    return
            except Exception:
                pass
        self.hicon = w.user32.LoadIconW(None, ctypes.c_wchar_p(w.IDI_APPLICATION))

    # ------------------------------------------------------------- tray
    def _nid(self, flags):
        nid = w.NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = wintypes.HWND(self.hwnd)
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self.hicon
        nid.szTip = self.tip[:127]
        return nid

    def _add_tray(self):
        nid = self._nid(w.NIF_MESSAGE | w.NIF_ICON | w.NIF_TIP)
        self._tray_added = bool(w.shell32.Shell_NotifyIconW(w.NIM_ADD,
                                                            ctypes.byref(nid)))

    def _remove_tray(self):
        if self._tray_added:
            nid = self._nid(0)
            w.shell32.Shell_NotifyIconW(w.NIM_DELETE, ctypes.byref(nid))
            self._tray_added = False

    def _update_tip(self, tip):
        self.tip = tip
        if self._tray_added:
            nid = self._nid(w.NIF_TIP)
            w.shell32.Shell_NotifyIconW(w.NIM_MODIFY, ctypes.byref(nid))

    def _balloon(self, title, text):
        if not self._tray_added:
            return
        nid = self._nid(w.NIF_INFO | w.NIF_ICON)
        nid.szInfo = str(text)[:255]
        nid.szInfoTitle = str(title)[:63]
        nid.dwInfoFlags = w.NIIF_INFO
        w.shell32.Shell_NotifyIconW(w.NIM_MODIFY, ctypes.byref(nid))

    # ------------------------------------------------------------- hotkeys
    def _register_hotkeys(self, mapping, enabled=True):
        for hk_id in list(self._hotkeys):
            w.user32.UnregisterHotKey(wintypes.HWND(self.hwnd), hk_id)
        self._hotkeys.clear()
        if not enabled:
            self.out.put(("hotkeys_registered", []))
            return
        ok, failed = [], []
        for i, (action, combo) in enumerate(sorted(mapping.items())):
            if not (combo or "").strip():
                continue                      # deliberately unassigned
            parsed = parse_hotkey(combo)
            if not parsed:
                failed.append((action, combo))
                continue
            mods, vk = parsed
            hk_id = 0xB000 + i
            if w.user32.RegisterHotKey(wintypes.HWND(self.hwnd), hk_id, mods, vk):
                self._hotkeys[hk_id] = action
                ok.append(action)
            else:
                failed.append((action, combo))
        self.out.put(("hotkeys_registered", ok))
        if failed:
            self.out.put(("hotkeys_failed", failed))

    # ------------------------------------------------------------- menu
    def _show_menu(self):
        menu = w.user32.CreatePopupMenu()
        w.user32.AppendMenuW(menu, w.MF_STRING, ID_SHOW, "เปิดหน้าต่าง ScreenPin")
        w.user32.AppendMenuW(menu, w.MF_SEPARATOR, 0, None)

        mons = self._menu_data.get("monitors", [])
        sub = w.user32.CreatePopupMenu()
        for i, m in enumerate(mons):
            label = "%s%s" % (m.get("tag", "?"),
                              "  (อยู่ตรงนี้)" if m.get("here") else "")
            w.user32.AppendMenuW(sub, w.MF_STRING, ID_MON_BASE + i, label)
        w.user32.AppendMenuW(menu, w.MF_POPUP, sub, "ย้าย ScreenPin ไปจอ")

        sub2 = w.user32.CreatePopupMenu()
        for i, m in enumerate(mons):
            w.user32.AppendMenuW(sub2, w.MF_STRING, ID_SLOT_BASE + i,
                                 "-> %s" % m.get("tag", "?"))
        w.user32.AppendMenuW(menu, w.MF_POPUP, sub2, "ส่งหน้าต่างที่ใช้อยู่ไป")

        w.user32.AppendMenuW(menu, w.MF_SEPARATOR, 0, None)
        w.user32.AppendMenuW(
            menu, w.MF_STRING | (w.MF_CHECKED if self._menu_data.get("auto_restore")
                                 else 0),
            ID_AUTORESTORE, "คืนจออัตโนมัติ")
        w.user32.AppendMenuW(
            menu, w.MF_STRING | (w.MF_CHECKED if self._menu_data.get("hotkeys")
                                 else 0),
            ID_HOTKEYS, "เปิดใช้ hotkey")
        w.user32.AppendMenuW(menu, w.MF_STRING, ID_RELOAD, "จัดใหม่เดี๋ยวนี้")
        w.user32.AppendMenuW(menu, w.MF_SEPARATOR, 0, None)
        w.user32.AppendMenuW(menu, w.MF_STRING, ID_EXIT, "ออก")

        pt = w.POINT()
        w.user32.GetCursorPos(ctypes.byref(pt))
        w.user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
        cmd = w.user32.TrackPopupMenu(
            menu, TPM_RETURNCMD | w.TPM_RIGHTBUTTON, pt.x, pt.y, 0,
            wintypes.HWND(self.hwnd), None)
        w.user32.PostMessageW(wintypes.HWND(self.hwnd), w.WM_NULL, 0, 0)
        w.user32.DestroyMenu(menu)
        if cmd:
            self.out.put(("menu", int(cmd)))

    # ------------------------------------------------------------- wndproc
    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == w.WM_HOTKEY:
                action = self._hotkeys.get(int(wparam))
                if action:
                    self.out.put(("hotkey", action))
                return 0
            if msg == w.WM_DISPLAYCHANGE:
                self.out.put(("display", None))
                return 0
            if msg == w.WM_SETTINGCHANGE and wparam == 0x2F:   # SPI_SETWORKAREA
                self.out.put(("display", None))
                return 0
            if msg == WM_TRAY:
                low = int(lparam) & 0xFFFF
                if low in (w.WM_RBUTTONUP, 0x7B):
                    self._show_menu()
                elif low in (w.WM_LBUTTONUP, w.WM_LBUTTONDBLCLK):
                    self.out.put(("menu", ID_SHOW))
                return 0
            if msg == WM_PUMP:
                self._drain()
                return 0
            if self._show_msg and msg == self._show_msg:
                self.out.put(("menu", ID_SHOW))
                return 1
            if self._taskbar_msg and msg == self._taskbar_msg:
                self._tray_added = False
                self._add_tray()
                return 0
            if msg == w.WM_DESTROY:
                self._remove_tray()
                w.user32.PostQuitMessage(0)
                return 0
        except Exception as e:
            try:
                self.out.put(("error", repr(e)))
            except Exception:
                pass
        return w.user32.DefWindowProcW(wintypes.HWND(hwnd), msg,
                                       wintypes.WPARAM(wparam),
                                       wintypes.LPARAM(lparam))

    def _drain(self):
        while True:
            try:
                cmd, arg = self._inbox.get_nowait()
            except queue.Empty:
                return
            if cmd == "hotkeys":
                self._register_hotkeys(arg or {}, True)
            elif cmd == "hotkeys_off":
                self._register_hotkeys({}, False)
            elif cmd == "tip":
                self._update_tip(arg)
            elif cmd == "balloon":
                self._balloon(arg[0], arg[1])
            elif cmd == "menu_data":
                self._menu_data = arg
            elif cmd == "picker_show":
                if self.picker:
                    self.picker.show(arg or {})
            elif cmd == "picker_hide":
                if self.picker:
                    self.picker.hide()
            elif cmd == "quit":
                self._remove_tray()
                w.user32.PostQuitMessage(0)
