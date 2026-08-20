"""ScreenPin controller: owns the engine, the tray thread, the HTTP API and the
UI window. The main thread runs a light loop; everything heavy is one tick.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import winreg

from . import browser as BR
from . import config as C
from . import engine as E
from . import icon as ICO
from . import icons as APPICONS
from . import monitors as M
from . import msgloop as ML
from . import server as SV
from . import shortcut as SC
from . import win32 as w
from . import windows as W

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class ScreenPin:
    def __init__(self):
        w.set_dpi_aware()
        self.cfg = C.Config()
        self.engine = E.Engine(self.cfg, on_event=self._on_event)
        self.q = queue.Queue()
        self.lock = threading.RLock()
        self.icon_path = ICO.ensure_icon(C.APP_DIR)

        self.rev = 0
        self._state = {"rev": 0}
        self._state_sig = None
        self._cv = threading.Condition()
        self.status = {"text": "พร้อมใช้งาน", "level": "info", "t": 0}
        self.running = True
        self._hk_ok, self._hk_bad = 0, []
        self._self_mon_key = None
        self._balloon_shown = False
        self._placed_at = 0.0
        self._user_hidden = False
        self._had_window = False

        self.server = SV.Server(self).start()
        self.win = BR.AppWindow(self.server.url,
                                os.path.join(C.APP_DIR, ".uiprofile"))
        self.msg = ML.MsgLoop(self.q, tip="ScreenPin", icon_path=self.icon_path)
        self.msg.start()
        self.msg.wait_ready(4.0)
        self.apply_hotkeys()

        self.engine.tick()
        self.rebuild_state(force=True)

    # ================================================================ status
    def _on_event(self, kind, msg):
        self.set_status(msg, "ok" if kind in ("restore", "pin", "evacuate")
                        else ("bad" if kind == "error" else "info"))
        if kind in ("restore", "evacuate") and self.cfg.settings.get("notify", True):
            self.msg.send("balloon", ("ScreenPin", msg))

    def set_status(self, text, level="info"):
        self.status = {"text": text, "level": level, "t": time.time()}

    # ================================================================ state
    def _mon_dict(self, m):
        rec = self.cfg.monitors.get(m.key) or {}
        return {"key": m.key, "tag": self.engine.tag_of_mon(m) or m.model,
                "slot": rec.get("slot", 0), "model": m.model,
                "x": m.rect[0], "y": m.rect[1], "w": m.rect[2], "h": m.rect[3],
                "primary": m.primary, "here": m.key == self._self_mon_key,
                "dpi": m.dpi}

    def build_state(self):
        eng = self.engine
        mons = [self._mon_dict(m) for m in eng.mons]
        live = {m.key for m in eng.mons}
        known = []
        for key, rec in sorted(self.cfg.monitors.items(),
                               key=lambda kv: (kv[1].get("slot") or 99,
                                               kv[1].get("tag") or "")):
            size = rec.get("size") or [0, 0]
            known.append({"key": key, "tag": rec.get("tag", key),
                          "slot": rec.get("slot", 0), "model": rec.get("model", ""),
                          "online": key in live, "size": list(size),
                          "last_seen": rec.get("last_seen", "")})
        wins = []
        for win in eng.wins:
            if win.hwnd in eng.ignore_hwnds:
                continue
            rec = self.cfg.apps.get(win.app_key) or {}
            sess = eng.session.get(win.hwnd) or {}
            wins.append({
                "hwnd": win.hwnd, "app": win.app_key,
                "exe": win.exe or win.cls, "title": win.title,
                "mon": win.mon.key if win.mon else "",
                "mon_tag": eng.tag_of_mon(win.mon) if win.mon else "",
                "home": sess.get("tag") or rec.get("tag") or "",
                "mode": rec.get("mode", "remember"),
                "max": win.maximized, "min": win.minimized,
                "icon": bool(APPICONS.for_window(win.hwnd, win.path)),
                "displaced": win.hwnd in eng._displaced,
            })
        wins.sort(key=lambda d: (d["exe"], d["title"]))
        return {
            "rev": self.rev,
            "monitors": mons,
            "known": known,
            "windows": wins,
            "self": {"chain": list(self.cfg.selfcfg.get("chain", [])),
                     "follow": bool(self.cfg.selfcfg.get("follow", True)),
                     "mon": self._self_mon_key or ""},
            "settings": dict(self.cfg.settings),
            "hotkeys": dict(self.cfg.hotkeys),
            "hotkey_status": {"ok": self._hk_ok, "bad": self._hk_bad},
            "status": self.status,
            "autostart": self.autostart_on(),
            "start_menu": self.start_menu_on(),
            "config_path": self.cfg.path,
        }

    def rebuild_state(self, force=False):
        with self.lock:
            st = self.build_state()
            sig = (tuple((m["key"], m["tag"], m["slot"], m["x"], m["here"])
                         for m in st["monitors"]),
                   tuple((x["hwnd"], x["title"], x["mon"], x["home"], x["mode"],
                          x["max"], x["min"]) for x in st["windows"]),
                   tuple((k["key"], k["tag"], k["slot"], k["online"])
                         for k in st["known"]),
                   tuple(st["self"]["chain"]), st["self"]["follow"],
                   st["self"]["mon"], tuple(sorted(st["settings"].items())),
                   tuple(sorted(st["hotkeys"].items())), st["status"]["text"],
                   st["hotkey_status"]["ok"], tuple(st["hotkey_status"]["bad"]),
                   st["autostart"])
            if force or sig != self._state_sig:
                self._state_sig = sig
                self.rev += 1
                st["rev"] = self.rev
                self._state = st
                with self._cv:
                    self._cv.notify_all()
        return self._state

    def wait_state(self, since):
        """Long-poll: return at once if newer, else wait for the next change."""
        with self._cv:
            if since < 0 or since != self.rev:
                return self._state
            self._cv.wait(timeout=8.0)
            return self._state

    # ================================================================ actions
    def do_action(self, p):
        a = p.get("a", "")
        fn = getattr(self, "act_" + a, None)
        if fn is None:
            return {"ok": False, "msg": "unknown action: %s" % a}
        with self.lock:
            ok, msg = fn(p)
        self.engine.wins = W.list_windows(self.engine.mons)
        st = self.rebuild_state(force=True)
        return {"ok": bool(ok), "msg": msg or "", "state": st}

    def _mon(self, key):
        return self.engine.mon_for_key(key)

    def window_icon(self, hwnd):
        """Served to the UI as /icon/<hwnd>.png"""
        for win in self.engine.wins:
            if win.hwnd == hwnd:
                return APPICONS.for_window(hwnd, win.path)
        return None

    def act_focus(self, p):
        hwnd = int(p.get("hwnd") or 0)
        if not hwnd or not W.w.user32.IsWindow(W.w.wintypes.HWND(hwnd)):
            return False, "ไม่พบหน้าต่าง"
        if W.w.user32.IsIconic(W.w.wintypes.HWND(hwnd)):
            W.w.user32.ShowWindow(W.w.wintypes.HWND(hwnd), W.w.SW_RESTORE)
        W.w.force_foreground(hwnd)
        return True, ""

    def act_move(self, p):
        mon = self._mon(p.get("key"))
        hwnd = int(p.get("hwnd") or 0)
        if not mon or not hwnd:
            return False, "ไม่พบจอหรือหน้าต่าง"
        if self.engine.move_hwnd_to(hwnd, mon, activate=bool(p.get("focus", True))):
            tag = self.engine.tag_of_mon(mon)
            self.set_status("ย้ายไป %s แล้ว — จำไว้ให้เรียบร้อย" % tag, "ok")
            return True, "ย้ายไป %s" % tag
        return False, "ย้ายไม่ได้ (แอพอาจรันแบบ Admin — ลองรัน ScreenPin as Admin)"

    def act_move_dir(self, p):
        hwnd = int(p.get("hwnd") or 0)
        cur = M.monitor_of_window(hwnd, self.engine.mons) if hwnd else None
        if not cur:
            return False, "ไม่พบหน้าต่าง"
        nxt = W.neighbour_monitor(cur, self.engine.mons, int(p.get("dir", 1)))
        return self.act_move({"hwnd": hwnd, "key": nxt.key})

    def act_pin(self, p):
        hwnd = int(p.get("hwnd") or 0)
        mon = M.monitor_of_window(hwnd, self.engine.mons) if hwnd else None
        if not mon:
            return False, "ไม่พบหน้าต่าง"
        _pp, _pid, exe, cls = W._identity(hwnd)
        app_key = (exe or cls or "?").lower()
        rec = self.cfg.apps.get(app_key) or {}
        if rec.get("mode") == "pin":
            self.engine.unpin_app(app_key)
            self.set_status("เลิกปักหมุด %s" % app_key, "info")
        else:
            others = [self.engine.tag_of_mon(m) for m in self.engine.mons
                      if m.key != mon.key]
            self.engine.pin_app(app_key, mon, others)
            self.set_status("ปักหมุด %s ไว้ที่ %s" % (app_key,
                                                    self.engine.tag_of_mon(mon)), "ok")
        self.engine.maybe_save(force=True)
        return True, ""

    def act_mode(self, p):
        self.engine.set_mode(p.get("app", ""), p.get("mode", "remember"))
        self.engine.maybe_save(force=True)
        return True, ""

    def act_forget(self, p):
        app = p.get("app", "")
        self.cfg.forget_app(app)
        for h, s in list(self.engine.session.items()):
            try:
                if W._identity(h)[2] == app:
                    del self.engine.session[h]
            except Exception:
                pass
        self.engine.maybe_save(force=True)
        self.set_status("ลืมค่าของ %s แล้ว" % app, "info")
        return True, ""

    def act_evacuate(self, p):
        src = self._mon(p.get("key")) or M.monitor_at_cursor(self.engine.mons)
        n = self.engine.evacuate_dir(int(p.get("dir", 1)), from_mon=src)
        return bool(n), "อพยพ %d หน้าต่าง" % n

    def act_rename_monitor(self, p):
        if self.cfg.set_tag(p.get("key", ""), p.get("tag", "")):
            self.cfg.save()
            self.set_status("เปลี่ยนชื่อจอเป็น %s" % p.get("tag"), "ok")
            return True, ""
        return False, "ชื่อซ้ำหรือว่าง"

    def act_set_slot(self, p):
        self.cfg.set_slot(p.get("key", ""), int(p.get("slot", 0)))
        self.cfg.save()
        return True, ""

    def act_delete_monitor(self, p):
        key = p.get("key", "")
        if key in {m.key for m in self.engine.mons}:
            return False, "จอนี้ยังต่ออยู่ ลบไม่ได้"
        self.cfg.monitors.pop(key, None)
        self.cfg.save()
        return True, ""

    def act_self_chain(self, p):
        chain, seen = [], set()
        for t in p.get("chain", []):
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                chain.append(t)
        self.cfg.selfcfg["chain"] = chain
        if "follow" in p:
            self.cfg.selfcfg["follow"] = bool(p["follow"])
        self.cfg.save()
        self.place_self(force=True)
        self.set_status("จอของ ScreenPin: %s" % (" → ".join(chain) or "อัตโนมัติ"),
                        "ok")
        return True, ""

    def act_place_self(self, _p):
        self.place_self(force=True)
        return True, ""

    def act_setting(self, p):
        key, val = p.get("key"), p.get("value")
        if key not in self.cfg.settings:
            return False, "ไม่รู้จัก setting นี้"
        self.cfg.settings[key] = val
        self.cfg.save()
        if key == "hotkeys_enabled":
            self.apply_hotkeys()
        self.push_menu_data()
        return True, ""

    def act_hotkeys(self, p):
        for k, v in (p.get("map") or {}).items():
            if k in self.cfg.hotkeys:
                self.cfg.hotkeys[k] = (v or "").strip()
        self.cfg.save()
        self.apply_hotkeys()
        return True, "บันทึกปุ่มลัดแล้ว"

    def act_hotkeys_reset(self, _p):
        self.cfg.data["hotkeys"] = dict(C.DEFAULT_HOTKEYS)
        self.cfg.save()
        self.apply_hotkeys()
        return True, "คืนค่าปุ่มลัดเริ่มต้น"

    def act_reconcile(self, _p):
        n = self.engine.reconcile(force=True)
        self.place_self(force=True)
        self.set_status("จัดใหม่แล้ว (ย้าย %d หน้าต่าง)" % n, "ok")
        return True, ""

    def act_autostart(self, p):
        return self.set_autostart(bool(p.get("on")))

    def act_open_config(self, _p):
        self.cfg.save()
        try:
            os.startfile(self.cfg.path)
            return True, ""
        except OSError as e:
            return False, str(e)

    def act_hide(self, _p):
        self.hide_to_tray()
        return True, ""

    def act_quit(self, _p):
        self.running = False
        return True, "กำลังปิด"

    def act_ping(self, _p):
        return True, ""

    # ================================================================ hotkeys
    def apply_hotkeys(self):
        if self.cfg.settings.get("hotkeys_enabled", True):
            self.msg.send("hotkeys", dict(self.cfg.hotkeys))
        else:
            self.msg.send("hotkeys_off")

    # ------------------------------------------------------------- shortcut
    def start_menu_path(self):
        return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                            "Start Menu", "Programs", "ScreenPin.lnk")

    def start_menu_on(self):
        return os.path.isfile(self.start_menu_path())

    def launch_command(self, extra=""):
        """(exe, arguments) that starts ScreenPin - frozen exe or python script."""
        if C.FROZEN:
            return sys.executable, extra.strip()
        pyw = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.isfile(pyw):
            pyw = sys.executable
        main = os.path.join(C.APP_DIR, "main.py")
        return pyw, ('"%s" %s' % (main, extra)).strip()

    def act_start_menu(self, p):
        """Add or remove the Start menu entry (also pinnable to taskbar)."""
        lnk = self.start_menu_path()
        if not p.get("on"):
            try:
                os.remove(lnk)
            except OSError:
                pass
            self.set_status("เอา ScreenPin ออกจาก Start menu แล้ว")
            return True, ""
        exe, args = self.launch_command()
        err = SC.create(lnk, exe, arguments=args, working_dir=C.APP_DIR,
                        icon=self.icon_path or exe,
                        description="ScreenPin — จัดแอพข้ามจอ")
        if err:
            return False, err
        if not os.path.isfile(lnk):
            return False, "สร้าง shortcut ไม่สำเร็จ"
        self.set_status("เพิ่ม ScreenPin ใน Start menu แล้ว — กดปุ่ม Start "
                        "แล้วพิมพ์ ScreenPin ได้เลย", "ok")
        return True, ""

    def autostart_on(self):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "ScreenPin")
                return True
        except OSError:
            return False

    def set_autostart(self, on):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as k:
                if on:
                    exe, args = self.launch_command("--tray")
                    winreg.SetValueEx(k, "ScreenPin", 0, winreg.REG_SZ,
                                      ('"%s" %s' % (exe, args)).strip())
                else:
                    try:
                        winreg.DeleteValue(k, "ScreenPin")
                    except OSError:
                        pass
            return True, ""
        except OSError as e:
            return False, str(e)

    # ================================================================ ui window
    def show_ui(self):
        self._user_hidden = False
        if self.win.alive():
            self.engine.ignore_hwnds = {self.win.hwnd}
            self.win.show()
            self.place_self()
            return
        if not self.win.available:
            self.set_status("ไม่พบ Edge/Chrome — เปิด %s ในเบราว์เซอร์เองได้"
                            % self.server.url, "bad")
            return
        mon = self.engine.self_target() or self.engine.fallback_monitor()
        rect = self.engine.self_rect_for(mon) if mon else None
        self.engine.guard_exe = os.path.basename(self.win.exe).lower()
        self.engine.guard_until = time.monotonic() + 25
        self.win.launch(rect)
        threading.Thread(target=self._await_ui, daemon=True).start()

    def _await_ui(self):
        if self.win.wait_for_window(12.0):
            self.engine.ignore_hwnds = {self.win.hwnd}
            self.engine.guard_until = 0.0
            time.sleep(0.15)
            self.place_self(force=True)
            self.win.show()
            self.rebuild_state(force=True)

    def hide_to_tray(self):
        self.remember_self_rect()
        self._user_hidden = True
        self.win.hide()
        if not self._balloon_shown and self.cfg.settings.get("notify", True):
            self._balloon_shown = True
            self.msg.send("balloon", ("ScreenPin ยังทำงานอยู่",
                                      "ย่ออยู่ใน tray — คลิกไอคอนเพื่อเปิด"))

    def place_self(self, force=False):
        if not self.win.alive():
            return
        cur = M.monitor_of_window(self.win.hwnd, self.engine.mons)
        pinned = self.engine.self_is_pinned()
        if not force:
            # No primary monitor chosen: leave the window wherever the user put
            # it, and only step in when the monitor under it disappeared.
            if not pinned and cur is not None:
                self._self_mon_key = cur.key
                return
            if pinned and not self.cfg.selfcfg.get("follow", True) and cur is not None:
                self._self_mon_key = cur.key
                return
        mon = self.engine.self_target()
        if mon is None:
            return
        if cur is not None and cur.key == mon.key and not force:
            self._self_mon_key = mon.key
            return
        W.move_window(self.win.hwnd, mon, rect=self.engine.self_rect_for(mon),
                      activate=False)
        self._self_mon_key = mon.key
        self._placed_at = time.monotonic()

    def sync_self_window(self):
        """Keep our own window identified even if startup discovery missed it.

        Also self-heals: the window must never end up hidden unless the user
        actually sent it to the tray.
        """
        if self.win.alive():
            self._had_window = True
            self.engine.ignore_hwnds = {self.win.hwnd}
            if not self._user_hidden and not self.win.is_visible():
                self.win.show(foreground=False)
            return True
        if self.win.find_window():
            self._had_window = True
            self.engine.ignore_hwnds = {self.win.hwnd}
            self.engine.guard_until = 0.0
            self.place_self(force=True)
            return True
        self.engine.ignore_hwnds = set()
        if self._had_window and not self._user_hidden:
            # The user closed the window with the X button.
            self._had_window = False
            if self.cfg.settings.get("close_quits"):
                self.running = False
            else:
                self._user_hidden = True
                if not self._balloon_shown and self.cfg.settings.get("notify", True):
                    self._balloon_shown = True
                    self.msg.send("balloon", ("ScreenPin ยังทำงานอยู่",
                                              "ปิดหน้าต่างแล้วแต่ยังคอยจัดจอให้ — "
                                              "คลิกไอคอนใน tray เพื่อเปิดใหม่"))
        return False

    def _current_self_key(self):
        if not self.win.alive():
            return self._self_mon_key
        cur = M.monitor_of_window(self.win.hwnd, self.engine.mons)
        return cur.key if cur else self._self_mon_key

    def remember_self_rect(self):
        # Chromium picks its own bounds for a moment before we place the window;
        # never record that transient rect as the user's preferred size.
        if not self.win.is_visible() or time.monotonic() - self._placed_at < 1.5:
            return
        rect = self.win.rect()
        mon = M.monitor_of_window(self.win.hwnd, self.engine.mons)
        if mon and rect and rect[2] > 300:
            self.engine.remember_self_rect(rect, mon)
            self._self_mon_key = mon.key

    # ================================================================ tray
    def push_menu_data(self):
        mons = [{"tag": self.engine.tag_of_mon(m) or m.model,
                 "here": m.key == self._self_mon_key, "key": m.key}
                for m in self.engine.mons]
        self.msg.send("menu_data", {
            "monitors": mons,
            "auto_restore": bool(self.cfg.settings.get("auto_restore")),
            "hotkeys": bool(self.cfg.settings.get("hotkeys_enabled")),
        })
        tag = next((m["tag"] for m in mons if m["here"]), "-")
        self.msg.send("tip", "ScreenPin — %d จอ · อยู่ที่ %s"
                      % (len(self.engine.mons), tag))

    # ================================================================ events
    def handle(self, kind, arg):
        if kind == "hotkey":
            self.do_hotkey(arg)
        elif kind == "display":
            self.engine.nudge()
        elif kind == "menu":
            self.do_menu(int(arg))
        elif kind == "picker_pick":
            hwnd, key = arg
            mon = self._mon(key)
            if mon:
                self.engine.move_hwnd_to(hwnd, mon)
                self.set_status("ย้ายไป %s" % self.engine.tag_of_mon(mon), "ok")
        elif kind == "hotkeys_registered":
            self._hk_ok, self._hk_bad = len(arg), []
        elif kind == "hotkeys_failed":
            self._hk_bad = [c for _a, c in arg]
            self.set_status("ปุ่มลัดชนกับโปรแกรมอื่น: %s — เปลี่ยนได้ในแท็บตั้งค่า"
                            % ", ".join(self._hk_bad), "warn")
        elif kind == "error":
            self.set_status(str(arg), "bad")

    def do_hotkey(self, action):
        eng = self.engine
        if action == "move_left":
            eng.move_focus_dir(-1)
        elif action == "move_right":
            eng.move_focus_dir(1)
        elif action.startswith("slot_"):
            eng.move_focus_slot(int(action.split("_")[1]))
        elif action == "evacuate_left":
            eng.evacuate_dir(-1)
        elif action == "evacuate_right":
            eng.evacuate_dir(1)
        elif action == "pin_here":
            eng.pin_focus_here()
        elif action == "show_app":
            self.show_ui()
        elif action == "picker":
            self.open_picker()

    def open_picker(self):
        target = W.foreground_window()
        if target is None or len(self.engine.mons) < 2:
            return
        cur = M.monitor_of_window(target, self.engine.mons)
        host = (cur or self.engine.fallback_monitor())
        self.msg.send("picker_show", {
            "target": target,
            "title": w.window_text(target),
            "host": host.work,
            "mons": [{"key": m.key,
                      "tag": self.engine.tag_of_mon(m) or m.model,
                      "slot": (self.cfg.monitors.get(m.key) or {}).get("slot", 0),
                      "rect": list(m.rect),
                      "here": bool(cur and cur.key == m.key)}
                     for m in self.engine.mons],
        })

    def do_menu(self, cmd):
        if cmd == ML.ID_SHOW:
            self.show_ui()
        elif cmd == ML.ID_EXIT:
            self.running = False
        elif cmd == ML.ID_AUTORESTORE:
            self.cfg.settings["auto_restore"] = \
                not self.cfg.settings.get("auto_restore", True)
            self.cfg.save()
            self.push_menu_data()
        elif cmd == ML.ID_HOTKEYS:
            self.cfg.settings["hotkeys_enabled"] = \
                not self.cfg.settings.get("hotkeys_enabled", True)
            self.cfg.save()
            self.apply_hotkeys()
            self.push_menu_data()
        elif cmd == ML.ID_RELOAD:
            self.engine.reconcile(force=True)
            self.place_self(force=True)
        elif ML.ID_MON_BASE <= cmd < ML.ID_MON_BASE + 50:
            i = cmd - ML.ID_MON_BASE
            if i < len(self.engine.mons):
                tag = self.engine.tag_of_mon(self.engine.mons[i])
                chain = [tag] + [t for t in self.cfg.selfcfg.get("chain", [])
                                 if t != tag]
                self.act_self_chain({"chain": chain[:3]})
        elif ML.ID_SLOT_BASE <= cmd < ML.ID_SLOT_BASE + 50:
            i = cmd - ML.ID_SLOT_BASE
            if i < len(self.engine.mons):
                self.engine.move_focus_to(self.engine.mons[i])

    # ================================================================ main loop
    def run(self, start_hidden=False):
        if not start_hidden:
            self.show_ui()
        else:
            self._self_mon_key = None
        self.push_menu_data()
        last_tick = 0.0
        while self.running:
            try:
                kind, arg = self.q.get(timeout=0.05)
                with self.lock:
                    self.handle(kind, arg)
                self.rebuild_state()
            except queue.Empty:
                pass
            except Exception as e:
                self.set_status("loop: %r" % e, "bad")

            now = time.monotonic()
            if now - last_tick >= self.cfg.settings.get("poll_ms", 1000) / 1000.0:
                last_tick = now
                with self.lock:
                    self.sync_self_window()
                    events = self.engine.tick()
                    APPICONS.forget({x.hwnd for x in self.engine.wins})
                    if "display_changed" in events or "reconciled" in events:
                        self.place_self()
                        self.push_menu_data()
                    else:
                        self.remember_self_rect()
                self.rebuild_state()
        self.shutdown()

    def shutdown(self):
        try:
            self.remember_self_rect()
            self.engine.maybe_save(force=True)
            self.cfg.save()
        except Exception:
            pass
        try:
            self.msg.send("quit")
        except Exception:
            pass
        try:
            self.win.close()
        except Exception:
            pass
        self.server.stop()
