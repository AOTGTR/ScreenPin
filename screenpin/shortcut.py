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


VT_LPWSTR = 31
ole32.CoTaskMemAlloc.restype = c_void_p
ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("data", ctypes.c_byte * 16)]


ole32.PropVariantClear.argtypes = [POINTER(PROPVARIANT)]


def str_variant(text):
    """VT_LPWSTR PROPVARIANT. InitPropVariantFromString is inline-only, so the
    string goes into a CoTaskMem block that PropVariantClear will free."""
    buf = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(buf)
    mem = ole32.CoTaskMemAlloc(size)
    if not mem:
        return None
    ctypes.memmove(mem, buf, size)
    pv = PROPVARIANT()
    pv.vt = VT_LPWSTR
    ctypes.memmove(ctypes.byref(pv, 8), ctypes.byref(c_void_p(mem)),
                   ctypes.sizeof(c_void_p))
    return pv


FMTID_AppUserModel = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
PKEY_AppUserModel_ID = 5
IID_IPropertyStore = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
PS_SETVALUE, PS_COMMIT = 6, 7

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


def _set_app_id(link, app_id):
    """Tag the shortcut with the same AppUserModelID the window uses, so a
    pinned icon and the running window are treated as the same app."""
    store = c_void_p()
    hr = _call(link, QUERY_INTERFACE, ctypes.HRESULT,
               POINTER(GUID), POINTER(c_void_p))(
        link, byref(IID_IPropertyStore), byref(store))
    if hr != S_OK or not store:
        return
    try:
        pv = str_variant(app_id)
        if pv is None:
            return
        key = PROPERTYKEY()
        key.fmtid = FMTID_AppUserModel
        key.pid = PKEY_AppUserModel_ID
        try:
            _call(store, PS_SETVALUE, ctypes.HRESULT, POINTER(PROPERTYKEY),
                  POINTER(PROPVARIANT))(store, byref(key), byref(pv))
            _call(store, PS_COMMIT, ctypes.HRESULT)(store)
        finally:
            ole32.PropVariantClear(byref(pv))
    finally:
        _call(store, RELEASE, ctypes.c_ulong)(store)


def create(path, target, arguments="", working_dir="", icon="", icon_index=0,
           description="", show_cmd=1, app_id=""):
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
        if app_id:
            _set_app_id(link, app_id)

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
