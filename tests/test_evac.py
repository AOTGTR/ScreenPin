"""Evacuate a monitor before switching it off - homes must survive."""
import sys, os, time, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)
from screenpin import win32 as w, monitors as M, windows as W, config as C, engine as E
w.set_dpi_aware()
TCFG = os.path.join(TMP, "t5.json")
if os.path.exists(TCFG): os.remove(TCFG)
real = M.enumerate_monitors
allm = real(); A, B, Cm = allm
pyw = sys.executable.replace("python.exe", "pythonw.exe")
code = ("import tkinter;r=tkinter.Tk();r.title('SPEVAC');r.geometry('380x260+%d+%d');"
        "r.mainloop()" % (B.rect[0]+300, B.rect[1]+200))
p = subprocess.Popen([pyw, "-c", code], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     creationflags=0x00000008)
time.sleep(1.7)
def find():
    for win in W.list_windows(real()):
        if "SPEVAC" in win.title: return win
cfg = C.Config(TCFG); eng = E.Engine(cfg)
def ticks(n=4, d=0.4):
    for _ in range(n): eng.tick(); time.sleep(d)
ticks(5)
win = find()
print("start on:", cfg.tag_of(win.mon.key), "(expect", cfg.tag_of(B.key), ")")
home0 = eng.session.get(win.hwnd, {}).get("tag")
print("home learned:", home0)

print("\n-- evacuate B -> neighbour (as if about to switch B off) --")
n = eng.evacuate_dir(1, from_mon=B)
time.sleep(0.4); ticks(5)
win = find()
home1 = eng.session.get(win.hwnd, {}).get("tag")
print("moved %d window(s); now sitting on %s; remembered home = %s"
      % (n, cfg.tag_of(win.mon.key), home1))
ok1 = home1 == cfg.tag_of(B.key) and win.mon.key != B.key
print("home survived evacuation:", "PASS" if ok1 else "FAIL")

print("\n-- simulate B off then back on --")
M.enumerate_monitors = lambda: [m for m in real() if m.key != B.key]
eng.nudge(); ticks(3, 0.4)
M.enumerate_monitors = real
eng.nudge(); eng.tick(); time.sleep(1.3); ticks(3, 0.4)
win = find()
print("final:", cfg.tag_of(win.mon.key), "(expect", cfg.tag_of(B.key), ")")
ok2 = win.mon.key == B.key
p.terminate()
print("\nRESULT:", "PASS" if (ok1 and ok2) else "FAIL")
sys.exit(0 if (ok1 and ok2) else 1)
