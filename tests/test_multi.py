"""Two windows of the SAME exe on different monitors must keep separate homes."""
import sys, os, time, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)
from screenpin import win32 as w, monitors as M, windows as W, config as C, engine as E
w.set_dpi_aware()
TCFG = os.path.join(TMP, "t4.json")
if os.path.exists(TCFG): os.remove(TCFG)

real = M.enumerate_monitors
allm = real()
A, B, Cm = allm[0], allm[1], allm[2]
pyw = sys.executable.replace("python.exe", "pythonw.exe")

def spawn(title, mon):
    code = ("import tkinter;r=tkinter.Tk();r.title('%s');r.geometry('380x260+%d+%d');"
            "r.mainloop()" % (title, mon.rect[0]+250, mon.rect[1]+180))
    return subprocess.Popen([pyw, "-c", code], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            creationflags=0x00000008)

p1 = spawn("SPTEST_ONE", A)
p2 = spawn("SPTEST_TWO", B)
time.sleep(1.8)

def find(t):
    for win in W.list_windows(real()):
        if t in win.title:
            return win
    return None

cfg = C.Config(TCFG); eng = E.Engine(cfg)
def ticks(n=4, d=0.4):
    for _ in range(n):
        eng.tick(); time.sleep(d)

ticks(5)
w1, w2 = find("SPTEST_ONE"), find("SPTEST_TWO")
print("ONE on", cfg.tag_of(w1.mon.key), "| TWO on", cfg.tag_of(w2.mon.key))
print("same exe:", w1.app_key == w2.app_key, "->", w1.app_key)
s1 = eng.session.get(w1.hwnd, {}).get("tag")
s2 = eng.session.get(w2.hwnd, {}).get("tag")
print("session homes: ONE=%s TWO=%s" % (s1, s2))
ok1 = s1 == cfg.tag_of(A.key) and s2 == cfg.tag_of(B.key)
print("per-window memory kept separate:", "PASS" if ok1 else "FAIL")

print("\n-- unplug B (where TWO lives); Windows shoves TWO onto C --")
M.enumerate_monitors = lambda: [m for m in real() if m.key != B.key]
W.move_window(find("SPTEST_TWO").hwnd, Cm, ratio=[0.3,0.3,0.3,0.3])
time.sleep(0.3); ticks(5)
w1 = find("SPTEST_ONE")
print("ONE stayed on:", cfg.tag_of(w1.mon.key), "(must be", cfg.tag_of(A.key), ")")
ok2 = w1.mon.key == A.key

print("\n-- plug B back --")
M.enumerate_monitors = real
eng.nudge(); eng.tick(); time.sleep(1.3); ticks(3, 0.4)
w1, w2 = find("SPTEST_ONE"), find("SPTEST_TWO")
print("ONE ->", cfg.tag_of(w1.mon.key), "| TWO ->", cfg.tag_of(w2.mon.key))
ok3 = w1.mon.key == A.key and w2.mon.key == B.key
print("\nRESULTS: separate=%s ONE-untouched=%s both-home=%s" % (ok1, ok2, ok3))
p1.terminate(); p2.terminate()
print("RESULT:", "PASS" if (ok1 and ok2 and ok3) else "FAIL")
sys.exit(0 if (ok1 and ok2 and ok3) else 1)
