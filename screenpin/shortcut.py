"""Create Windows .lnk files through IShellLinkW.

WScript.Shell (the usual one-liner) mangles non-ANSI paths into '?', which
breaks any install that lives in a folder with a Thai name - so we talk to the
COM interface directly instead.
"""
import ctypes
from ctypes import POINTER, byref, c_int, c_void_p, wintypes

ole32 = ctypes.WinDLL("ole32")

CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 0x2
S_OK = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

    def __init__(self, text):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(self))


CLSID_ShellLink = GUID("{00021401-0000-0000-C000-000000000046}")
IID_IShellLinkW = GUID("{000214F9-0000-0000-C000-000000000046}")
IID_IPersistFile = GUID("{0000010B-0000-0000-C000-000000000046}")

# IShellLinkW vtable slots (after the three IUnknown entries)
SET_DESCRIPTION = 7
SET_WORKING_DIR = 9
SET_ARGUMENTS = 11
SET_SHOW_CMD = 15
SET_ICON_LOCATION = 17
SET_PATH = 20
# IPersistFile
PF_SAVE = 6

RELEASE = 2
QUERY_INTERFACE = 0


def _call(ptr, slot, restype, *argtypes):
    vtbl = ctypes.cast(ptr, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtbl, POINTER(c_void_p))[slot]
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(fn)


def _wstr(ptr, slot, text):
    return _call(ptr, slot, ctypes.HRESULT, wintypes.LPCWSTR)(ptr, text)


def create(path, target, arguments="", working_dir="", icon="", icon_index=0,
           description="", show_cmd=1):
    """Write a .lnk at `path`. Returns None on success, else an error string."""
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    started = hr in (S_OK, 1)                     # S_OK or S_FALSE
    link = c_void_p()
    persist = c_void_p()
    try:
        hr = ole32.CoCreateInstance(byref(CLSID_ShellLink), None,
                                    CLSCTX_INPROC_SERVER, byref(IID_IShellLinkW),
                                    byref(link))
        if hr != S_OK or not link:
            return "CoCreateInstance failed (0x%08x)" % (hr & 0xFFFFFFFF)

        _wstr(link, SET_PATH, target)
        if arguments:
            _wstr(link, SET_ARGUMENTS, arguments)
        if working_dir:
            _wstr(link, SET_WORKING_DIR, working_dir)
        if description:
            _wstr(link, SET_DESCRIPTION, description[:260])
        if icon:
            _call(link, SET_ICON_LOCATION, ctypes.HRESULT,
                  wintypes.LPCWSTR, c_int)(link, icon, icon_index)
        _call(link, SET_SHOW_CMD, ctypes.HRESULT, c_int)(link, show_cmd)

        hr = _call(link, QUERY_INTERFACE, ctypes.HRESULT,
                   POINTER(GUID), POINTER(c_void_p))(
            link, byref(IID_IPersistFile), byref(persist))
        if hr != S_OK or not persist:
            return "QueryInterface(IPersistFile) failed"

        hr = _call(persist, PF_SAVE, ctypes.HRESULT,
                   wintypes.LPCWSTR, wintypes.BOOL)(persist, path, True)
        if hr != S_OK:
            return "Save failed (0x%08x)" % (hr & 0xFFFFFFFF)
        return None
    except OSError as e:
        return str(e)
    finally:
        for p in (persist, link):
            if p:
                _call(p, RELEASE, ctypes.c_ulong)(p)
        if started:
            ole32.CoUninitialize()
