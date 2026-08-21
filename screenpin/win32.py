"""Raw Win32 bindings via ctypes. Zero external dependencies."""
import ctypes
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

# ---------------------------------------------------------------- structures


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    def as_tuple(self):
        return (self.left, self.top, self.right - self.left, self.bottom - self.top)


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128), ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128), ("DeviceKey", wintypes.WCHAR * 128)]


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", POINT),
                ("ptMaxPosition", POINT), ("rcNormalPosition", RECT)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON)]


# ---------------------------------------------------------------- constants

MONITORINFOF_PRIMARY = 0x1
EDD_GET_DEVICE_INTERFACE_NAME = 0x1
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_VISIBLE, WS_CHILD, WS_CAPTION = 0x10000000, 0x40000000, 0x00C00000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_THICKFRAME = 0x20000, 0x10000, 0x40000
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE = 0x80, 0x40000, 0x08000000
WS_EX_TOPMOST, WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x8, 0x80000, 0x20

GW_OWNER = 4
SW_HIDE, SW_SHOWNORMAL, SW_SHOWMINIMIZED = 0, 1, 2
SW_SHOWMAXIMIZED, SW_RESTORE, SW_SHOW, SW_SHOWNA = 3, 9, 5, 8

SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER = 0x1, 0x2, 0x4
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_FRAMECHANGED = 0x10, 0x40, 0x20
SWP_ASYNCWINDOWPOS, SWP_NOOWNERZORDER = 0x4000, 0x200
HWND_TOP, HWND_TOPMOST, HWND_NOTOPMOST = 0, -1, -2

DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_HOTKEY = 0x2, 0x10, 0x111, 0x312
WM_DISPLAYCHANGE, WM_SETTINGCHANGE, WM_DEVICECHANGE = 0x7E, 0x1A, 0x219
WM_USER, WM_APP, WM_NULL, WM_QUIT = 0x400, 0x8000, 0x0, 0x12
WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x202, 0x205, 0x203

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NOTIFYICON_VERSION_4 = 4
NIIF_INFO = 0x1

MF_STRING, MF_SEPARATOR, MF_CHECKED, MF_GRAYED, MF_POPUP = 0x0, 0x800, 0x8, 0x1, 0x10
TPM_RIGHTALIGN, TPM_BOTTOMALIGN, TPM_RIGHTBUTTON = 0x8, 0x20, 0x2
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE, LR_SHARED = 1, 0x10, 0x40, 0x8000

IDI_APPLICATION = 32512
IDC_ARROW = 32512

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 0, 1, 2

# --- GDI drawing (used by the quick picker overlay) ---
WS_POPUP, WS_BORDER = 0x80000000, 0x00800000
WM_PAINT, WM_KEYDOWN, WM_KILLFOCUS, WM_ERASEBKGND = 0x0F, 0x100, 0x8, 0x14
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_ACTIVATE = 0x200, 0x201, 0x06
VK_ESCAPE, VK_LEFT, VK_RIGHT, VK_RETURN, VK_TAB = 0x1B, 0x25, 0x27, 0x0D, 0x09
VK_UP, VK_DOWN = 0x26, 0x28
TRANSPARENT, OPAQUE = 1, 2
DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_LEFT = 0x1, 0x4, 0x20, 0x0
DT_END_ELLIPSIS, DT_NOPREFIX = 0x8000, 0x800
PS_SOLID = 0
SRCCOPY = 0xCC0020
FW_NORMAL, FW_SEMIBOLD, FW_BOLD, FW_BLACK = 400, 600, 700, 900
ANTIALIASED_QUALITY, CLEARTYPE_QUALITY = 4, 5
DEFAULT_CHARSET = 1
LWA_ALPHA = 0x2


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL),
                ("rcPaint", RECT), ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


def hex_rgb(s):
    s = s.lstrip("#")
    return rgb(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))

# ---------------------------------------------------------------- prototypes

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(RECT), wintypes.LPARAM)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = LRESULT
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadCursorW.restype = ctypes.c_void_p
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t,
                               wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  ctypes.c_void_p]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                              ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindow.restype = wintypes.HWND
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.BeginPaint.restype = wintypes.HDC
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetDC.restype = wintypes.HDC
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), ctypes.c_void_p]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
                             ctypes.POINTER(RECT), wintypes.UINT]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF,
                                              ctypes.c_ubyte, wintypes.DWORD]
gdi32.CreateSolidBrush.restype = ctypes.c_void_p
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreatePen.restype = ctypes.c_void_p
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [wintypes.HDC, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                         wintypes.DWORD]
gdi32.RoundRect.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.CreateFontW.restype = ctypes.c_void_p
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                              wintypes.LPCWSTR]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

# ---------------------------------------------------------------- helpers


def set_dpi_aware():
    """Per-monitor DPI v2 so window coordinates are real physical pixels."""
    try:
        if user32.SetProcessDpiAwarenessContext(
                DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return True
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return True
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    return False


def get_dpi_for_window(hwnd):
    try:
        d = int(user32.GetDpiForWindow(wintypes.HWND(hwnd)))
        return d if d else 96
    except Exception:
        return 96


def window_text(hwnd):
    n = user32.GetWindowTextLengthW(wintypes.HWND(hwnd))
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buf, n + 2)
    return buf.value


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
    return buf.value


def is_cloaked(hwnd):
    """DWM-cloaked windows are invisible ghosts (suspended UWP, other desktops)."""
    val = wintypes.DWORD(0)
    try:
        hr = dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), DWMWA_CLOAKED,
                                          ctypes.byref(val), ctypes.sizeof(val))
        return hr == 0 and val.value != 0
    except Exception:
        return False


def get_window_rect(hwnd):
    r = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r)):
        return None
    return r.as_tuple()


def get_placement(hwnd):
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(wp)
    if not user32.GetWindowPlacement(wintypes.HWND(hwnd), ctypes.byref(wp)):
        return None
    return wp


def process_path(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    if not pid.value:
        return "", 0
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return "", pid.value
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value, pid.value
        return "", pid.value
    finally:
        kernel32.CloseHandle(h)


def force_foreground(hwnd):
    """SetForegroundWindow refuses cross-process; attach input to work around it."""
    h = wintypes.HWND(hwnd)
    try:
        cur = user32.GetForegroundWindow()
        t1 = user32.GetWindowThreadProcessId(cur, None)
        t2 = user32.GetWindowThreadProcessId(h, None)
        if t1 and t2 and t1 != t2:
            user32.AttachThreadInput(t1, t2, True)
            user32.SetForegroundWindow(h)
            user32.AttachThreadInput(t1, t2, False)
        else:
            user32.SetForegroundWindow(h)
    except Exception:
        try:
            user32.SetForegroundWindow(h)
        except Exception:
            pass
