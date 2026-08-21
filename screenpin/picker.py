"""Quick picker overlay drawn with GDI.

Lives entirely inside the Win32 message thread so it can appear instantly and
take keyboard focus without a UI toolkit.
"""
import ctypes
from ctypes import wintypes

from . import win32 as w

BG = w.hex_rgb("#0d1219")
CARD = w.hex_rgb("#1b2532")
CARD_HERE = w.hex_rgb("#243449")
EDGE = w.hex_rgb("#31445c")
ACCENT = w.hex_rgb("#4ea1ff")
TEXT = w.hex_rgb("#e9eff8")
DIM = w.hex_rgb("#8b9aac")
HOVER = w.hex_rgb("#2c405a")

CLASS_NAME = "ScreenPinPickerWnd"


def _font(size, weight=w.FW_NORMAL, face="Segoe UI"):
    return w.gdi32.CreateFontW(-abs(int(size)), 0, 0, 0, weight, 0, 0, 0,
                               w.DEFAULT_CHARSET, 0, 0, w.CLEARTYPE_QUALITY, 0,
                               face)


class Picker:
    """Create and drive from the message-loop thread only."""

    def __init__(self, out_queue):
        self.out = out_queue
        self.hwnd = None
        self.layout = None
        self.boxes = []
        self.hot = -1
        self._proc_ref = None
        self._registered = False

    # ------------------------------------------------------------ window
    def _ensure(self):
        if self.hwnd:
            return
        hinst = w.kernel32.GetModuleHandleW(None)
        if not self._registered:
            cls = w.WNDCLASSEXW()
            cls.cbSize = ctypes.sizeof(cls)
            self._proc_ref = w.WNDPROC(self._wndproc)
            cls.lpfnWndProc = ctypes.cast(self._proc_ref, ctypes.c_void_p)
            cls.hInstance = hinst
            cls.lpszClassName = CLASS_NAME
            cls.hCursor = w.user32.LoadCursorW(None, ctypes.c_wchar_p(w.IDC_ARROW))
            cls.hbrBackground = None
            w.user32.RegisterClassExW(ctypes.byref(cls))
            self._registered = True
        self.hwnd = w.user32.CreateWindowExW(
            w.WS_EX_TOOLWINDOW | w.WS_EX_TOPMOST, CLASS_NAME, "ScreenPin",
            w.WS_POPUP, 0, 0, 10, 10, None, None, hinst, None)

    # ------------------------------------------------------------ show/hide
    def show(self, layout):
        """layout: {target, title, host:(x,y,w,h), mons:[{key,tag,slot,rect,here}]}"""
        mons = layout.get("mons") or []
        if len(mons) < 2 or not layout.get("target"):
            return False
        self._ensure()
        self.layout = layout
        self.hot = -1

        x0 = min(m["rect"][0] for m in mons)
        y0 = min(m["rect"][1] for m in mons)
        x1 = max(m["rect"][0] + m["rect"][2] for m in mons)
        y1 = max(m["rect"][1] + m["rect"][3] for m in mons)
        vw, vh = max(x1 - x0, 1), max(y1 - y0, 1)

        hx, hy, hw, hh = layout["host"]
        pw = max(560, min(int(hw * 0.62), 1180))
        scale = (pw - 40) / vw
        ph = int(vh * scale) + 132
        if ph > hh * 0.8:
            scale *= (hh * 0.8 - 132) / max(ph - 132, 1)
            ph = int(vh * scale) + 132
        px = hx + (hw - pw) // 2
        py = hy + (hh - ph) // 2

        self.boxes = []
        for m in mons:
            bx = 20 + (m["rect"][0] - x0) * scale
            by = 92 + (m["rect"][1] - y0) * scale
            self.boxes.append([int(bx) + 5, int(by) + 5,
                               int(bx + m["rect"][2] * scale) - 5,
                               int(by + m["rect"][3] * scale) - 5, m])

        w.user32.SetWindowPos(wintypes.HWND(self.hwnd), wintypes.HWND(-1),
                              px, py, pw, ph, w.SWP_SHOWWINDOW)
        w.user32.SetForegroundWindow(wintypes.HWND(self.hwnd))
        w.user32.SetFocus(wintypes.HWND(self.hwnd))
        w.user32.InvalidateRect(wintypes.HWND(self.hwnd), None, True)
        return True

    def hide(self):
        if self.hwnd:
            w.user32.ShowWindow(wintypes.HWND(self.hwnd), w.SW_HIDE)
        self.layout = None

    def _pick(self, mon):
        target = (self.layout or {}).get("target")
        self.hide()
        if mon and target:
            self.out.put(("picker_pick", (target, mon["key"])))

    def _pick_dir(self, direction, axis="x"):
        """Arrow keys walk to the monitor that actually lies that way."""
        if not self.boxes:
            return
        mons = [b[4] for b in self.boxes]
        here = next((m for m in mons if m.get("here")), mons[0])
        hx = here["rect"][0] + here["rect"][2] // 2
        hy = here["rect"][1] + here["rect"][3] // 2
        horiz = axis != "y"
        best, best_rank = None, None
        for m in mons:
            if m is here:
                continue
            mx = m["rect"][0] + m["rect"][2] // 2
            my = m["rect"][1] + m["rect"][3] // 2
            along = (mx - hx) if horiz else (my - hy)
            if along * direction <= 0:
                continue
            rank = (abs((my - hy) if horiz else (mx - hx)), abs(along))
            if best_rank is None or rank < best_rank:
                best, best_rank = m, rank
        if best is None:
            spread = {m["rect"][0 if horiz else 1] for m in mons}
            if len(spread) < 2:
                return                      # no monitor lies that way at all
            order = sorted(mons, key=lambda m: m["rect"][0 if horiz else 1])
            best = order[0] if direction > 0 else order[-1]
        self._pick(best)

    # ------------------------------------------------------------ painting
    def _paint(self):
        ps = w.PAINTSTRUCT()
        hdc = w.user32.BeginPaint(wintypes.HWND(self.hwnd), ctypes.byref(ps))
        rc = w.RECT()
        w.user32.GetClientRect(wintypes.HWND(self.hwnd), ctypes.byref(rc))
        cw, ch = rc.right, rc.bottom

        mem = w.gdi32.CreateCompatibleDC(hdc)
        bmp = w.gdi32.CreateCompatibleBitmap(hdc, cw, ch)
        old_bmp = w.gdi32.SelectObject(mem, bmp)
        try:
            self._draw(mem, cw, ch)
            w.gdi32.BitBlt(hdc, 0, 0, cw, ch, mem, 0, 0, w.SRCCOPY)
        finally:
            w.gdi32.SelectObject(mem, old_bmp)
            w.gdi32.DeleteObject(bmp)
            w.gdi32.DeleteDC(mem)
        w.user32.EndPaint(wintypes.HWND(self.hwnd), ctypes.byref(ps))

    def _draw(self, dc, cw, ch):
        g = w.gdi32
        bg = g.CreateSolidBrush(BG)
        full = w.RECT(0, 0, cw, ch)
        w.user32.FillRect(dc, ctypes.byref(full), bg)
        g.DeleteObject(bg)
        g.SetBkMode(dc, w.TRANSPARENT)

        f_title = _font(19, w.FW_SEMIBOLD)
        f_sub = _font(12)
        f_tag = _font(14, w.FW_SEMIBOLD)
        f_small = _font(11)
        f_hint = _font(11)
        fonts = [f_title, f_sub, f_tag, f_small, f_hint]

        def text(s, x0, y0, x1, y1, font, color, flags=w.DT_CENTER | w.DT_VCENTER
                 | w.DT_SINGLELINE | w.DT_NOPREFIX):
            old = g.SelectObject(dc, font)
            g.SetTextColor(dc, color)
            r = w.RECT(int(x0), int(y0), int(x1), int(y1))
            w.user32.DrawTextW(dc, s, -1, ctypes.byref(r), flags)
            g.SelectObject(dc, old)

        text("ย้ายหน้าต่างนี้ไปจอไหน?", 0, 22, cw, 52, f_title, TEXT)
        text((self.layout or {}).get("title", "")[:80], 0, 52, cw, 76, f_sub, DIM,
             w.DT_CENTER | w.DT_VCENTER | w.DT_SINGLELINE | w.DT_END_ELLIPSIS
             | w.DT_NOPREFIX)

        for i, (bx, by, bx2, by2, m) in enumerate(self.boxes):
            here = bool(m.get("here"))
            hot = (i == self.hot)
            fill = HOVER if hot else (CARD_HERE if here else CARD)
            edge = ACCENT if (here or hot) else EDGE
            brush = g.CreateSolidBrush(fill)
            pen = g.CreatePen(w.PS_SOLID, 2, edge)
            ob, op = g.SelectObject(dc, brush), g.SelectObject(dc, pen)
            g.RoundRect(dc, bx, by, bx2, by2, 14, 14)
            g.SelectObject(dc, ob)
            g.SelectObject(dc, op)
            g.DeleteObject(brush)
            g.DeleteObject(pen)

            bw, bh = bx2 - bx, by2 - by
            slot = m.get("slot") or 0
            f_num = _font(max(24, min(bh * 0.42, bw * 0.42)), w.FW_BLACK)
            text(str(slot) if slot else "·", bx, by + bh * 0.10, bx2,
                 by + bh * 0.62, f_num, ACCENT if not hot else TEXT)
            g.DeleteObject(f_num)
            text(m.get("tag", "?"), bx + 6, by + bh * 0.60, bx2 - 6,
                 by + bh * 0.80, f_tag, TEXT,
                 w.DT_CENTER | w.DT_VCENTER | w.DT_SINGLELINE
                 | w.DT_END_ELLIPSIS | w.DT_NOPREFIX)
            sub = "อยู่จอนี้" if here else "%dx%d" % (m["rect"][2], m["rect"][3])
            text(sub, bx + 6, by + bh * 0.79, bx2 - 6, by + bh * 0.95,
                 f_small, ACCENT if here else DIM)

        text("กดเลข = ย้ายทันที    ←  → = จอข้างๆ    คลิกก็ได้    Esc = ปิด",
             0, ch - 34, cw, ch - 12, f_hint, DIM)
        for f in fonts:
            g.DeleteObject(f)

    # ------------------------------------------------------------ input
    def _hit(self, x, y):
        for i, (bx, by, bx2, by2, m) in enumerate(self.boxes):
            if bx <= x <= bx2 and by <= y <= by2:
                return i
        return -1

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == w.WM_PAINT:
                self._paint()
                return 0
            if msg == w.WM_ERASEBKGND:
                return 1
            if msg == w.WM_KEYDOWN:
                vk = int(wparam)
                if vk == w.VK_ESCAPE:
                    self.hide()
                elif vk == w.VK_LEFT:
                    self._pick_dir(-1)
                elif vk == w.VK_RIGHT:
                    self._pick_dir(1)
                elif vk == w.VK_UP:
                    self._pick_dir(-1, "y")
                elif vk == w.VK_DOWN:
                    self._pick_dir(1, "y")
                elif 0x31 <= vk <= 0x39 or 0x61 <= vk <= 0x69:
                    n = (vk - 0x30) if vk <= 0x39 else (vk - 0x60)
                    hit = next((b[4] for b in self.boxes
                                if (b[4].get("slot") or 0) == n), None)
                    if hit is None and n <= len(self.boxes):
                        hit = self.boxes[n - 1][4]
                    self._pick(hit)
                return 0
            if msg == w.WM_MOUSEMOVE:
                x, y = ctypes.c_short(lparam & 0xFFFF).value, \
                    ctypes.c_short((lparam >> 16) & 0xFFFF).value
                hit = self._hit(x, y)
                if hit != self.hot:
                    self.hot = hit
                    w.user32.InvalidateRect(wintypes.HWND(hwnd), None, False)
                return 0
            if msg == w.WM_LBUTTONUP:
                x, y = ctypes.c_short(lparam & 0xFFFF).value, \
                    ctypes.c_short((lparam >> 16) & 0xFFFF).value
                hit = self._hit(x, y)
                if hit >= 0:
                    self._pick(self.boxes[hit][4])
                else:
                    self.hide()
                return 0
            if msg == w.WM_KILLFOCUS:
                self.hide()
                return 0
        except Exception as e:
            try:
                self.out.put(("error", "picker: %r" % (e,)))
            except Exception:
                pass
        return w.user32.DefWindowProcW(wintypes.HWND(hwnd), msg,
                                       wintypes.WPARAM(wparam),
                                       wintypes.LPARAM(lparam))
