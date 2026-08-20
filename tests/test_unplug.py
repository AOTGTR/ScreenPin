"""End-to-end: monitor goes away, comes back, window must return home."""
import sys, os, time, subprocess, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)
from screenpin import win32 as w, monitors as M, windows as W, config as C, engine as E
w.set_dpi_aware()

CFG = os.path.join(TMP, "t2.json")
if os.path.exists(CFG): os.remove(CFG)

real_enum = M.enumerate_monitors
mons_all = real_enum()
HOME = mons_all[1]      # DISPLAY3 @ -1920,0
OTHER = mons_all[2]     # DISPLAY1 @ 0,0
print("HOME =", HOME.key, HOME.rect)
print("OTHER=", OTHER.key, OTHER.rect)

# --- helper window in its own process, parked on HOME -----------------------
code = ("import tkinter;r=tkinter.Tk();r.title('SCREENPIN_TESTWIN');"
        "r.geometry('420x300+%d+%d');r.mainloop()" % (HOME.rect[0]+200, HOME.rect[1]+150))
pyw = sys.executable.replace("python.exe","pythonw.exe")
proc = subprocess.Popen([pyw, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=0x00000008)
time.sleep(1.6)

def find_test():
    for win in W.list_windows(M.enumerate_monitors()):
        if "SCREENPIN_TESTWIN" in win.title:
            return win
    return None

tw = find_test()
assert tw, "test window not found"
APPKEY = tw.app_key
print("test window on:", tw.mon.key, tw.rect, "app_key=", APPKEY)

cfg = C.Config(CFG)
eng = E.Engine(cfg)

def ticks(n=3, delay=0.45):
    for _ in range(n):
        eng.tick(); time.sleep(delay)

print("\n--- phase 1: learn ---")
ticks(4)
rec = cfg.apps.get(APPKEY, {})
print("learned tag  :", rec.get("tag"), " (expect", cfg.tag_of(HOME.key), ")")
assert rec.get("tag") == cfg.tag_of(HOME.key), "FAIL: did not learn home"

print("\n--- phase 2: unplug HOME (simulated) ---")
M.enumerate_monitors = lambda: [m for m in real_enum() if m.key != HOME.key]
# Windows would shove the window onto a surviving monitor - do the same
W.move_window(find_test().hwnd, OTHER, ratio=[0.2,0.2,0.3,0.3])
time.sleep(0.3)
ticks(5)
rec = cfg.apps.get(APPKEY, {})
tw = find_test()
print("window now on:", tw.mon.key)
print("remembered tag still:", rec.get("tag"))
assert rec.get("tag") == cfg.tag_of(HOME.key), "FAIL: memory got overwritten while home was off!"
print("OK - memory survived the blackout")

print("\n--- phase 3: plug HOME back in ---")
M.enumerate_monitors = real_enum
ticks(1, 0.1)          # detects change, starts settle timer
time.sleep(1.2)
ticks(2, 0.4)          # settle expires -> reconcile
tw = find_test()
print("window back on:", tw.mon.key, "(expect", HOME.key, ")")
ok = tw.mon.key == HOME.key
print("\nRESULT:", "PASS - window returned home automatically" if ok else "FAIL")
proc.terminate()
sys.exit(0 if ok else 1)
