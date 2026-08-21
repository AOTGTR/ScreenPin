"""Pick monitors for the behaviour tests on whatever setup is plugged in.

The tests need at least two live monitors. With exactly two, the third slot
falls back to the first one and the caller skips the cases that need three.
"""
import sys


def pick(enumerate_monitors):
    mons = enumerate_monitors()
    if len(mons) < 2:
        print("ข้ามเทส: ต้องมีอย่างน้อย 2 จอที่เปิดอยู่ (เจอ %d)" % len(mons))
        sys.exit(0)
    a, b = mons[0], mons[1]
    c = mons[2] if len(mons) > 2 else mons[0]
    return a, b, c, len(mons)
