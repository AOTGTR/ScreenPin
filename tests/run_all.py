"""Run every ScreenPin behaviour test. Stop the app first - it would fight
these tests over the same windows."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_unplug.py", "test_multi.py", "test_evac.py", "test_chain2.py"]
TITLES = {
    "test_unplug.py": "ปิดจอ -> เปิดจอ แล้วหน้าต่างต้องคืนที่เดิม",
    "test_multi.py":  "2 หน้าต่างของ exe เดียวกัน ต้องจำจอแยกกัน",
    "test_evac.py":   "อพยพก่อนปิดจอ ต้องยังจำจอเดิม",
    "test_chain2.py": "จอหลัก -> จอรอง -> จอว่าง -> เด้งกลับ",
}

env = dict(os.environ, PYTHONIOENCODING="utf-8")
fails = []
for t in TESTS:
    print("=" * 68)
    print("%-16s %s" % (t, TITLES.get(t, "")))
    print("=" * 68)
    r = subprocess.run([sys.executable, "-u", os.path.join(HERE, t)], env=env)
    if r.returncode != 0:
        fails.append(t)
    print()
print("=" * 68)
print("FAILED: " + ", ".join(fails) if fails else "ALL TESTS PASSED")
sys.exit(1 if fails else 0)
