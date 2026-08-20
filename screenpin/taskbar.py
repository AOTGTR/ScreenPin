"""Give the UI window our own taskbar identity.

The UI lives in a browser window, so by default Windows groups it under the
browser and shows the browser's icon on the taskbar. Setting an explicit
AppUserModelID plus a relaunch icon on that window makes it show up as
ScreenPin instead.
"""
import ctypes
import os
from ctypes import POINTER, byref, c_void_p, wintypes

from . import win32 as w
from .shortcut import (GUID, PROPERTYKEY, PROPVARIANT, _call,
                       str_variant as _str_variant)

shell32 = ctypes.WinDLL("shell32")
propsys = ctypes.WinDLL("propsys")
ole32 = ctypes.WinDLL("ole32")

S_OK = 0
WM_SETICON = 0x80
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10

# IPropertyStore
PS_SETVALUE = 6
PS_COMMIT = 7
RELEASE = 2

IID_IPropertyStore = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
FMTID_AppUserModel = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")

PID_ID = 5
PID_RELAUNCH_COMMAND = 2
PID_RELAUNCH_ICON = 3
PID_RELAUNCH_NAME = 4


shell32.SHGetPropertyStoreForWindow.argtypes = [wintypes.HWND, POINTER(GUID),
                                                POINTER(c_void_p)]
ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]
w.user32.LoadImageW.restype = wintypes.HANDLE


def _key(pid):
    k = PROPERTYKEY()
    k.fmtid = FMTID_AppUserModel
    k.pid = pid
    return k


def set_identity(hwnd, app_id, icon_path="", display_name="", relaunch=""):
    """Point the taskbar button at us instead of the host browser."""
    store = c_void_p()
    hr = shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd),
                                             byref(IID_IPropertyStore),
                                             byref(store))
    if hr != S_OK or not store:
        return "SHGetPropertyStoreForWindow failed (0x%08x)" % (hr & 0xFFFFFFFF)
    setter = _call(store, PS_SETVALUE, ctypes.HRESULT,
                   POINTER(PROPERTYKEY), POINTER(PROPVARIANT))
    try:
        values = [(PID_ID, app_id)]
        if icon_path:
            values.append((PID_RELAUNCH_ICON, "%s,0" % icon_path))
        if display_name:
            values.append((PID_RELAUNCH_NAME, display_name))
        if relaunch:
            values.append((PID_RELAUNCH_COMMAND, relaunch))
        for pid, text in values:
            pv = _str_variant(text)
            if pv is None:
                continue
            try:
                setter(store, byref(_key(pid)), byref(pv))
            finally:
                ole32.PropVariantClear(byref(pv))
        _call(store, PS_COMMIT, ctypes.HRESULT)(store)
        return None
    except OSError as e:
        return str(e)
    finally:
        _call(store, RELEASE, ctypes.c_ulong)(store)


def set_window_icon(hwnd, icon_path):
    """Title-bar and alt-tab icon."""
    if not icon_path or not os.path.isfile(icon_path):
        return False
    ok = False
    for which, size in ((ICON_BIG, 32), (ICON_SMALL, 16)):
        h = w.user32.LoadImageW(None, icon_path, IMAGE_ICON, size, size,
                                LR_LOADFROMFILE)
        if h:
            w.user32.SendMessageW(wintypes.HWND(hwnd), WM_SETICON, which,
                                  ctypes.c_void_p(h))
            ok = True
    return ok


def brand_window(hwnd, icon_path, app_id="AOTGTR.ScreenPin",
                 display_name="ScreenPin", relaunch=""):
    """Everything needed so the window looks like ScreenPin, not the browser."""
    set_window_icon(hwnd, icon_path)
    err = set_identity(hwnd, app_id, icon_path, display_name, relaunch)
    # The shell reads the identity when the window joins the taskbar, so bounce
    # it once to make the change take effect on an already-visible window.
    if err is None:
        on_screen = (w.user32.IsWindowVisible(wintypes.HWND(hwnd))
                     and not w.user32.IsIconic(wintypes.HWND(hwnd)))
        if on_screen:                     # never un-minimise the user's window
            w.user32.ShowWindow(wintypes.HWND(hwnd), w.SW_HIDE)
            w.user32.ShowWindow(wintypes.HWND(hwnd), w.SW_SHOW)
    return err
