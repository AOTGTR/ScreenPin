"""The brain: tag resolution, memory of where things live, auto-restore.

Performance rule for this file: one window enumeration per tick, shared by every
step below. Everything else works off that snapshot.
"""
import os
import time

from . import monitors as M
from . import windows as W
from . import win32 as w


class Engine:
    def __init__(self, cfg, on_event=None):
        self.cfg = cfg
        self.on_event = on_event or (lambda kind, msg: None)
        self.mons = []
        self.wins = []             # snapshot from the most recent tick
        self.livemap = {}          # saved monitor key -> live Monitor
        self.sig = ""
        self.settle_at = 0.0
        self.dirty = False
        self._last_save = 0.0
        self._known = {}           # hwnd -> first seen (monotonic), 0 = handled
        # Per-window memory for this session. An app with several windows
        # (Chrome, Explorer) keeps each one on its own monitor; the per-exe
        # record in config is only the seed for brand-new windows.
        self.session = {}          # hwnd -> {"tag":str, "ratios":{key:ratio}}
        self._displaced = set()    # evacuated hwnds: keep their home, do not relearn
        self.ignore_hwnds = set()  # our own UI window - never manage or learn it
        # While our UI browser window is starting up it looks like any other
        # window of that browser, so hold off on auto-placing that exe.
        self.guard_exe = None
        self.guard_until = 0.0
        self._started = False
        self.last_change = 0.0
        self.busy = False

    # ------------------------------------------------------------ monitors
    def refresh_monitors(self, mons=None):
        self.mons = mons if mons is not None else M.enumerate_monitors()
        for m in self.mons:
            self.cfg.register(m)
        self.livemap = M.resolve_saved(self.cfg.monitors, self.mons)
        self.dirty = True
        return self.mons

    def mon_for_key(self, key):
        m = self.livemap.get(key)
        if m is not None:
            return m
        for mon in self.mons:
            if mon.key == key:
                return mon
        return None

    def mon_for_tag(self, tag):
        if not tag:
            return None
        key = self.cfg.key_of_tag(tag)
        return self.mon_for_key(key) if key else None

    def tag_of_mon(self, mon):
        if mon is None:
            return None
        for skey, live in self.livemap.items():
            if live.key == mon.key:
                return self.cfg.tag_of(skey)
        return self.cfg.tag_of(mon.key)

    def mon_for_slot(self, slot):
        key = self.cfg.key_of_slot(slot)
        return self.mon_for_key(key) if key else None

    def is_tag_live(self, tag):
        return self.mon_for_tag(tag) is not None

    def all_tags(self):
        return [self.cfg.tag_of(m.key) for m in self.mons]

    def fallback_monitor(self, wins=None):
        """Nothing in the chain is plugged in - pick the emptiest live monitor."""
        if not self.mons:
            return None
        counts = {m.key: 0 for m in self.mons}
        for win in (self.wins if wins is None else wins):
            if win.hwnd in self.ignore_hwnds:
                continue
            if win.mon and win.mon.key in counts:
                counts[win.mon.key] += 1
        return sorted(self.mons,
                      key=lambda m: (counts[m.key], 0 if m.primary else 1))[0]

    def resolve_chain(self, chain, allow_fallback=True, wins=None):
        """First live monitor in the tag chain; else the emptiest one."""
        for tag in chain or []:
            mon = self.mon_for_tag(tag)
            if mon is not None:
                return mon
        return self.fallback_monitor(wins) if allow_fallback else None

    # ------------------------------------------------------------ app memory
    def home_chain(self, rec):
        if not rec:
            return []
        if rec.get("mode") == "pin" and rec.get("chain"):
            return list(rec["chain"])
        chain = []
        if rec.get("tag"):
            chain.append(rec["tag"])
        for t in rec.get("chain", []):
            if t not in chain:
                chain.append(t)
        return chain

    def learn(self, wins):
        """Remember where each window sits - but only while its home monitor is up."""
        if not self.cfg.settings.get("learn", True):
            return
        alive = set()
        for win in wins:
            alive.add(win.hwnd)
            if win.hwnd in self.ignore_hwnds or win.minimized or win.mon is None:
                continue
            if (self.guard_exe and win.app_key == self.guard_exe
                    and time.monotonic() < self.guard_until):
                continue
            rec = self.cfg.app_rec(win.app_key)
            if rec.get("mode") == "ignore":
                continue
            tag = self.tag_of_mon(win.mon)
            sess = self.session.setdefault(win.hwnd, {"tag": None, "ratios": {}})
            ratio = None if win.maximized else W.rect_ratio(win.rect, win.mon)

            # Home unplugged, or the window was evacuated on purpose? Then it is
            # sitting somewhere temporary - never let that overwrite the real home.
            home = sess.get("tag")
            displaced = win.hwnd in self._displaced
            if displaced and (home is None or tag == home):
                self._displaced.discard(win.hwnd)
                displaced = False
            if (rec.get("mode") != "pin" and not displaced
                    and (not home or self.is_tag_live(home))):
                sess["tag"] = tag
                rec["tag"] = tag
            if ratio:
                sess["ratios"][win.mon.key] = ratio
                rec.setdefault("ratios", {})[win.mon.key] = ratio
            sess["maximized"] = bool(win.maximized)
            rec["maximized"] = bool(win.maximized)
            rec["title"] = win.title[:80]
        if len(self.session) > 256:
            for h in [h for h in self.session if h not in alive]:
                del self.session[h]
        self._displaced &= alive
        self.dirty = True

    def window_home(self, win):
        """Where this specific window belongs: pin > session > per-app record."""
        rec = self.cfg.apps.get(win.app_key)
        if rec and rec.get("mode") == "ignore":
            return None, rec
        if rec and rec.get("mode") == "pin":
            return self.home_chain(rec), rec
        sess = self.session.get(win.hwnd)
        if sess and sess.get("tag"):
            return [sess["tag"]], rec
        return self.home_chain(rec), rec

    def home_ratio(self, win, target, rec):
        sess = self.session.get(win.hwnd) or {}
        return (sess.get("ratios", {}).get(target.key)
                or (rec or {}).get("ratios", {}).get(target.key))

    def set_home(self, app_key, mon, ratio=None, maximized=None, hwnd=None):
        """Explicit user move - always wins over passive learning."""
        rec = self.cfg.app_rec(app_key)
        tag = self.tag_of_mon(mon)
        rec["tag"] = tag
        if ratio:
            rec.setdefault("ratios", {})[mon.key] = ratio
        if maximized is not None:
            rec["maximized"] = bool(maximized)
        if hwnd is not None:
            sess = self.session.setdefault(hwnd, {"tag": None, "ratios": {}})
            sess["tag"] = tag
            if ratio:
                sess["ratios"][mon.key] = ratio
            self._displaced.discard(hwnd)
        self.dirty = True
        return rec

    def pin_app(self, app_key, mon, fallback_tags=None):
        rec = self.cfg.app_rec(app_key)
        rec["mode"] = "pin"
        rec["tag"] = self.tag_of_mon(mon)
        rec["chain"] = [rec["tag"]] + [t for t in (fallback_tags or [])
                                       if t and t != rec["tag"]]
        self.dirty = True
        return rec

    def unpin_app(self, app_key):
        rec = self.cfg.app_rec(app_key, create=False)
        if rec:
            rec["mode"] = "remember"
            rec["chain"] = []
        self.dirty = True

    def set_mode(self, app_key, mode):
        self.cfg.app_rec(app_key)["mode"] = mode
        self.dirty = True

    # ------------------------------------------------------------ restore
    def reconcile(self, wins=None, force=False):
        """Send every window back to the monitor it remembers, if that one is up."""
        if not self.cfg.settings.get("auto_restore", True) and not force:
            return 0
        wins = self.wins if wins is None else wins
        moved = 0
        for win in wins:
            if win.hwnd in self.ignore_hwnds:
                continue
            if (self.guard_exe and win.app_key == self.guard_exe
                    and time.monotonic() < self.guard_until):
                continue
            chain, rec = self.window_home(win)
            if not chain:
                continue
            target = self.resolve_chain(chain, allow_fallback=False)
            if target is None:
                continue
            if win.mon is not None and win.mon.key == target.key:
                continue
            ratio = self.home_ratio(win, target, rec)
            if ratio is None and win.mon is not None:
                ratio = W.rect_ratio(win.rect, win.mon)
            if W.move_window(win.hwnd, target, ratio=ratio, activate=False):
                self._known[win.hwnd] = 0
                moved += 1
        if moved:
            self.on_event("restore", "คืนหน้าต่างกลับที่เดิม %d อัน" % moved)
        return moved

    def place_new_windows(self, wins):
        """A freshly launched app jumps straight to the monitor it belongs on."""
        if not self.cfg.settings.get("place_new_windows", True):
            return 0
        now = time.monotonic()
        live = set()
        moved = 0
        for win in wins:
            live.add(win.hwnd)
            if win.hwnd in self.ignore_hwnds:
                self._known[win.hwnd] = 0
                continue
            if (self.guard_exe and win.app_key == self.guard_exe
                    and now < self.guard_until):
                continue
            first = self._known.get(win.hwnd)
            if first is None:
                self._known[win.hwnd] = now
                continue
            if first == 0 or now - first < 0.8:
                continue
            self._known[win.hwnd] = 0                # act once per window
            rec = self.cfg.apps.get(win.app_key)
            if not rec or rec.get("mode") == "ignore":
                continue
            target = self.resolve_chain(self.home_chain(rec), allow_fallback=False)
            if target is None or (win.mon and win.mon.key == target.key):
                continue
            ratio = (rec.get("ratios") or {}).get(target.key)
            if W.move_window(win.hwnd, target, ratio=ratio, activate=False):
                moved += 1
        if len(self._known) > 256:
            for h in [h for h in self._known if h not in live]:
                del self._known[h]
        return moved

    # ------------------------------------------------------------ actions
    def move_hwnd_to(self, hwnd, mon, remember=True, activate=True):
        if hwnd is None or mon is None:
            return False
        ok = W.move_to_monitor(hwnd, mon, self.mons, activate=activate)
        if ok and remember:
            path, _pid, exe, cls = W._identity(hwnd)
            app_key = (exe or cls or "?").lower()
            r = w.get_window_rect(hwnd)
            self._known[hwnd] = 0
            self.set_home(app_key, mon, W.rect_ratio(r, mon), hwnd=hwnd)
            self.maybe_save(force=True)
        return ok

    def move_focus_to(self, mon, remember=True):
        return self.move_hwnd_to(W.foreground_window(), mon, remember)

    def move_focus_dir(self, direction, axis="x"):
        hwnd = W.foreground_window()
        if hwnd is None:
            return False
        cur = M.monitor_of_window(hwnd, self.mons)
        if cur is None:
            return False
        return self.move_hwnd_to(
            hwnd, W.neighbour_monitor(cur, self.mons, direction, axis))

    def move_focus_slot(self, slot):
        return self.move_focus_to(self.mon_for_slot(slot))

    def evacuate_dir(self, direction, from_mon=None, axis="x"):
        """Clear a monitor before you switch it off - homes are kept, not relearned."""
        src = from_mon or M.monitor_at_cursor(self.mons)
        if src is None:
            return 0
        dst = W.neighbour_monitor(src, self.mons, direction, axis)
        if dst is None or dst.key == src.key:
            return 0
        wins = [x for x in self.wins if x.hwnd not in self.ignore_hwnds]
        moved = W.evacuate(src, dst, self.mons, wins)
        self._displaced.update(moved)
        if moved:
            self.on_event("evacuate", "อพยพ %d หน้าต่าง -> %s (จำจอเดิมไว้)"
                          % (len(moved), self.tag_of_mon(dst)))
        return len(moved)

    def pin_focus_here(self):
        hwnd = W.foreground_window()
        if hwnd is None:
            return None
        mon = M.monitor_of_window(hwnd, self.mons)
        if mon is None:
            return None
        _p, _pid, exe, cls = W._identity(hwnd)
        app_key = (exe or cls or "?").lower()
        self.pin_app(app_key, mon)
        self.maybe_save(force=True)
        self.on_event("pin", "ปักหมุด %s -> %s" % (app_key, self.tag_of_mon(mon)))
        return app_key

    # ------------------------------------------------------------ self window
    def self_target(self):
        """Where our own window belongs.

        With a chain configured it behaves like any pinned app. With no chain
        the app simply stays where it was last left - it only ever gets rescued
        when that monitor is gone.
        """
        chain = self.cfg.selfcfg.get("chain", [])
        if chain:
            return self.resolve_chain(chain, allow_fallback=True)
        last = self.mon_for_key(self.cfg.selfcfg.get("last_mon") or "")
        return last or self.fallback_monitor()

    def self_is_pinned(self):
        return bool(self.cfg.selfcfg.get("chain"))

    def self_rect_for(self, mon, default_size=(980, 650)):
        saved = self.cfg.selfcfg.setdefault("rects", {}).get(mon.key)
        if saved:
            return W.clamp_rect(tuple(saved), mon)
        wx, wy, ww, wh = mon.work
        cw, ch = min(default_size[0], ww - 60), min(default_size[1], wh - 60)
        return W.clamp_rect((wx + (ww - cw) // 2, wy + (wh - ch) // 2, cw, ch), mon)

    def remember_self_rect(self, rect, mon):
        if mon and rect:
            self.cfg.selfcfg.setdefault("rects", {})[mon.key] = list(rect)
            self.cfg.selfcfg["last_mon"] = mon.key
            self.dirty = True

    # ------------------------------------------------------------ loop
    def tick(self):
        """Call about once a second. Returns the list of things that happened."""
        if self.busy:
            return []
        self.busy = True
        try:
            return self._tick()
        except Exception as e:
            self.on_event("error", repr(e))
            return []
        finally:
            self.busy = False

    def _tick(self):
        events = []
        now = time.monotonic()
        mons = M.enumerate_monitors()
        sig = M.signature(mons)

        if sig != self.sig:
            first = not self.sig
            self.sig = sig
            self.refresh_monitors(mons)
            self.wins = W.list_windows(self.mons)
            self.settle_at = now + (0.35 if first else
                                    self.cfg.settings.get("settle_ms", 900) / 1000.0)
            self.last_change = now
            events.append("display_changed")
            if not first:
                self.on_event("display", "จอเปลี่ยน — กำลังจัดใหม่")
            self.maybe_save(force=True)
            return events

        self.mons = mons
        self.livemap = M.resolve_saved(self.cfg.monitors, self.mons)
        self.wins = W.list_windows(self.mons)

        if not self._started:
            self._started = True
            for win in self.wins:
                self._known[win.hwnd] = 0        # do not treat startup as "new"
            self.reconcile(self.wins)
            events.append("reconciled")
        elif self.settle_at and now >= self.settle_at:
            self.settle_at = 0.0
            self.reconcile(self.wins)
            events.append("reconciled")
        elif not self.settle_at:
            self.learn(self.wins)
            self.place_new_windows(self.wins)

        self.maybe_save()
        return events

    def nudge(self):
        """Instant re-check (called on WM_DISPLAYCHANGE)."""
        self.sig = ""

    def maybe_save(self, force=False):
        now = time.monotonic()
        if self.dirty and (force or now - self._last_save > 5.0):
            self.cfg.save()
            self.dirty = False
            self._last_save = now
