"""self_target() must walk primary -> secondary -> any-free, and come back."""
import sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
TMP = os.path.join(ROOT, "tests", "_tmp")
os.makedirs(TMP, exist_ok=True)
from screenpin import win32 as w, monitors as M, config as C, engine as E
w.set_dpi_aware()
T = os.path.join(TMP, "t6.json")
if os.path.exists(T): os.remove(T)
real = M.enumerate_monitors
A, B, Cm = real()
cfg = C.Config(T); eng = E.Engine(cfg)
eng.tick(); time.sleep(0.2); eng.tick()
tA, tB, tC = cfg.tag_of(A.key), cfg.tag_of(B.key), cfg.tag_of(Cm.key)
print("tags:", tA, tB, tC)

def sim(keep):
    M.enumerate_monitors = lambda: [m for m in real() if m.key in keep]
    eng.sig = ""; eng.tick(); time.sleep(0.1); eng.tick()
    t = eng.self_target()
    return t.key if t else None

results = []
print("\n== no chain configured (should stay put / not be pinned) ==")
print("  self_is_pinned:", eng.self_is_pinned(), "(expect False)")
results.append(("unpinned by default", eng.self_is_pinned() is False))

cfg.selfcfg["chain"] = [tB, tA]           # primary DP, secondary HDMI
print("\n== chain =", cfg.selfcfg["chain"], "==")
r1 = sim({A.key, B.key, Cm.key}); print("  all on          ->", cfg.tag_of(r1))
r2 = sim({A.key, Cm.key});        print("  primary off     ->", cfg.tag_of(r2))
r3 = sim({Cm.key});               print("  both off        ->", cfg.tag_of(r3))
r4 = sim({A.key, B.key, Cm.key}); print("  primary back    ->", cfg.tag_of(r4))
results += [("primary", r1 == B.key), ("secondary", r2 == A.key),
            ("rescue to free", r3 == Cm.key), ("jump home", r4 == B.key)]

print("\n== no chain: falls back to last_mon ==")
cfg.selfcfg["chain"] = []
cfg.selfcfg["last_mon"] = A.key
r5 = sim({A.key, B.key, Cm.key}); print("  last_mon live   ->", cfg.tag_of(r5))
r6 = sim({B.key, Cm.key});        print("  last_mon gone   ->", cfg.tag_of(r6))
results += [("remembers last monitor", r5 == A.key),
            ("rescued when it vanishes", r6 in (B.key, Cm.key))]

M.enumerate_monitors = real
print()
ok = all(v for _, v in results)
for name, v in results:
    print("  %-26s %s" % (name, "PASS" if v else "FAIL"))
print("\nRESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
