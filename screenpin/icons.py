"""Grab the real icon of a running window and hand it back as PNG bytes.

Windows gives icons out as HICON/HBITMAP; converting to PNG here means the web
UI can show the actual app icons with no image library involved.
"""
import ctypes
import struct
import zlib
from ctypes import wintypes

from . import win32 as w

WM_GETICON = 0x7F
ICON_SMALL, ICON_BIG, ICON_SMALL2 = 0, 1, 2
GCLP_HICON, GCLP_HICONSM = -14, -34
SMTO_ABORTIFHUNG = 0x2

SHGFI_ICON = 0x100
SHGFI_LARGEICON = 0x0
SHGFI_USEFILEATTRIBUTES = 0x10
DIB_RGB_COLORS = 0
BI_RGB = 0

_cache = {}          # hwnd -> png bytes or None
_exe_cache = {}      # exe path -> png bytes or None


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


w.user32.PrivateExtractIconsW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
    wintypes.UINT, wintypes.UINT]
w.user32.GetClassLongPtrW.restype = ctypes.c_size_t
w.user32.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
# GDI handles come back sign-extended on x64; everything must be c_void_p or
# ctypes overflows trying to squeeze them into an int.
w.gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
w.gdi32.GetDIBits.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                              wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.UINT]
w.user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
w.user32.DestroyIcon.argtypes = [ctypes.c_void_p]
w.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


# ------------------------------------------------------------------ png


def _png(width, height, rgba):
    rowlen = width * 4
    raw = bytearray()
    for y in range(height):
        raw += b"\x00"
        raw += rgba[y * rowlen:(y + 1) * rowlen]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", comp)
            + chunk(b"IEND", b""))


# ------------------------------------------------------------------ hicon


def _dib_bits(hdc, hbm, width, height, bits):
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height          # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = bits
    bmi.bmiHeader.biCompression = BI_RGB
    stride = ((width * bits + 31) // 32) * 4
    buf = ctypes.create_string_buffer(stride * height)
    ok = w.gdi32.GetDIBits(hdc, ctypes.c_void_p(hbm), 0, height, buf,
                           ctypes.byref(bmi), DIB_RGB_COLORS)
    return (bytes(buf), stride) if ok else (None, 0)


def hicon_to_png(hicon, reject_blank=False):
    """32-bit RGBA PNG of an icon, alpha included. None if it cannot be read."""
    if not hicon:
        return None
    info = ICONINFO()
    if not w.user32.GetIconInfo(ctypes.c_void_p(hicon), ctypes.byref(info)):
        return None
    hdc = w.user32.GetDC(None)
    try:
        bm = BITMAP()
        if not info.hbmColor:
            return None                      # 1bpp legacy icon, not worth it
        w.gdi32.GetObjectW(ctypes.c_void_p(info.hbmColor),
                           ctypes.sizeof(BITMAP), ctypes.byref(bm))
        width, height = int(bm.bmWidth), int(bm.bmHeight)
        if width <= 0 or height <= 0 or width > 512:
            return None
        color, stride = _dib_bits(hdc, info.hbmColor, width, height, 32)
        if color is None:
            return None

        # Slice assignment does the BGRA->RGBA swap at C speed; a per-pixel
        # Python loop here cost ~10 ms per icon.
        rgba = bytearray(color[:width * height * 4])
        rgba[0::4], rgba[2::4] = bytes(rgba[2::4]), bytes(rgba[0::4])

        alpha = bytes(rgba[3::4])
        total = width * height
        solid = total - alpha.count(0)

        if solid and info.hbmMask and alpha.count(0) == total:
            pass                                  # unreachable, kept simple
        if solid == 0 and info.hbmMask:
            # Old-style icon: no alpha channel, transparency lives in the mask.
            mask, mstride = _dib_bits(hdc, info.hbmMask, width, height, 1)
            if mask:
                for y in range(height):
                    base = y * mstride
                    row = y * width
                    for x in range(width):
                        bit = (mask[base + (x >> 3)] >> (7 - (x & 7))) & 1
                        rgba[(row + x) * 4 + 3] = 0 if bit else 255
                alpha = bytes(rgba[3::4])
                solid = total - alpha.count(0)

        if reject_blank:
            flat = all(max(ch) == min(ch)
                       for ch in (bytes(rgba[0::4]), bytes(rgba[1::4]),
                                  bytes(rgba[2::4]), alpha))
            if solid == 0 or solid * 25 < total or flat:
                # Chrome PWA windows hand out an icon that is empty or one flat
                # colour - useless, so let the caller fall back to the exe icon.
                return None

        return _png(width, height, bytes(rgba))
    except Exception:
        return None
    finally:
        w.user32.ReleaseDC(None, hdc)
        for h in (info.hbmColor, info.hbmMask):
            if h:
                w.gdi32.DeleteObject(ctypes.c_void_p(h))


# ------------------------------------------------------------------ sources


def _window_icon(hwnd):
    """Icon the window advertises. Never blocks on a hung app."""
    res = ctypes.c_size_t()
    for which in (ICON_BIG, ICON_SMALL2, ICON_SMALL):
        try:
            if w.user32.SendMessageTimeoutW(
                    wintypes.HWND(hwnd), WM_GETICON, which, 0,
                    SMTO_ABORTIFHUNG, 250, ctypes.byref(res)) and res.value:
                return int(res.value)
        except Exception:
            pass
    for which in (GCLP_HICON, GCLP_HICONSM):
        try:
            h = w.user32.GetClassLongPtrW(wintypes.HWND(hwnd), which)
            if h:
                return int(h)
        except Exception:
            pass
    return 0


def _exe_png(path, size=64):
    if not path:
        return None
    if path in _exe_cache:
        return _exe_cache[path]
    png = None
    hicon = wintypes.HICON()
    got = wintypes.UINT()
    try:
        n = w.user32.PrivateExtractIconsW(path, 0, size, size,
                                          ctypes.byref(hicon),
                                          ctypes.byref(got), 1, 0)
        if n and hicon.value:
            png = hicon_to_png(hicon.value)
            w.user32.DestroyIcon(ctypes.c_void_p(hicon.value))
    except Exception:
        pass
    if png is None:
        shfi = SHFILEINFOW()
        try:
            if w.shell32.SHGetFileInfoW(path, 0, ctypes.byref(shfi),
                                        ctypes.sizeof(shfi),
                                        SHGFI_ICON | SHGFI_LARGEICON):
                png = hicon_to_png(shfi.hIcon)
                w.user32.DestroyIcon(ctypes.c_void_p(shfi.hIcon))
        except Exception:
            pass
    _exe_cache[path] = png
    return png


def for_window(hwnd, exe_path=""):
    """PNG bytes for this window's icon, cached. None when nothing is available."""
    if hwnd in _cache:
        return _cache[hwnd]
    png = None
    try:
        png = hicon_to_png(_window_icon(hwnd), reject_blank=True)
    except Exception:
        png = None
    if png is None:
        png = _exe_png(exe_path)
    _cache[hwnd] = png
    return png


def forget(alive_hwnds):
    for h in [h for h in _cache if h not in alive_hwnds]:
        del _cache[h]
