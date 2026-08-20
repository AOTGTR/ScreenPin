"""Generate the tray/window icon as a real .ico file - no image library needed."""
import os
import struct

ACCENT = (0x4E, 0xA1, 0xFF)
DIM = (0xC8, 0xD2, 0xE0)


def _blank(size):
    return [[(0, 0, 0, 0)] * size for _ in range(size)]


def _fill(px, x0, y0, x1, y1, col):
    size = len(px)
    for y in range(max(0, int(y0)), min(size, int(y1))):
        for x in range(max(0, int(x0)), min(size, int(x1))):
            px[y][x] = col


def _rect_outline(px, x0, y0, x1, y1, col, t=1):
    _fill(px, x0, y0, x1, y0 + t, col)
    _fill(px, x0, y1 - t, x1, y1, col)
    _fill(px, x0, y0, x0 + t, y1, col)
    _fill(px, x1 - t, y0, x1, y1, col)


def _draw(size):
    px = _blank(size)
    t = max(1, size // 16)
    boxes = [(0.02, 0.20), (0.35, 0.14), (0.68, 0.20)]
    for i, (fx, fy) in enumerate(boxes):
        x0 = fx * size
        y0 = fy * size
        x1 = x0 + size * 0.30
        y1 = y0 + size * (0.46 if i != 1 else 0.54)
        active = (i == 2)
        rgb = ACCENT if active else DIM
        col = (rgb[2], rgb[1], rgb[0], 255)
        if active:
            _fill(px, x0, y0, x1, y1, col)
        else:
            _rect_outline(px, x0, y0, x1, y1, col, t)
        # stand
        sx = (x0 + x1) / 2
        _fill(px, sx - t, y1, sx + t, y1 + t * 1.5, col)
        _fill(px, sx - t * 2.2, y1 + t, sx + t * 2.2, y1 + t * 2, col)
    return px


def _ico_image(px):
    size = len(px)
    xor = bytearray()
    for y in range(size - 1, -1, -1):           # DIB rows are bottom-up
        for x in range(size):
            b, g, r, a = px[y][x]
            xor += bytes((b, g, r, a))
    row = ((size + 31) // 32) * 4               # AND mask row padded to 4 bytes
    andmask = bytearray()
    for y in range(size - 1, -1, -1):
        bits = bytearray(row)
        for x in range(size):
            if px[y][x][3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        andmask += bits
    hdr = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0,
                      len(xor) + len(andmask), 0, 0, 0, 0)
    return bytes(hdr) + bytes(xor) + bytes(andmask)


def build_ico(path, sizes=(16, 24, 32, 48, 64)):
    imgs = [_ico_image(_draw(s)) for s in sizes]
    out = bytearray(struct.pack("<HHH", 0, 1, len(imgs)))
    offset = 6 + 16 * len(imgs)
    for s, data in zip(sizes, imgs):
        out += struct.pack("<BBBBHHII", s if s < 256 else 0, s if s < 256 else 0,
                           0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for data in imgs:
        out += data
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


def ensure_icon(app_dir):
    path = os.path.join(app_dir, "screenpin.ico")
    if not os.path.exists(path):
        try:
            build_ico(path)
        except OSError:
            return None
    return path
