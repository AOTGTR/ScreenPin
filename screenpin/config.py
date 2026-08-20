"""JSON config: monitor tags, the app's own monitor chain, per-app memory."""
import json
import os
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
# Frozen: everything user-visible (config, icon, browser profile) lives next to
# ScreenPin.exe. Source run: next to main.py.
APP_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULT_HOTKEYS = {
    "move_left":     "Ctrl+Alt+Left",
    "move_right":    "Ctrl+Alt+Right",
    "slot_1":        "Ctrl+Alt+1",
    "slot_2":        "Ctrl+Alt+2",
    "slot_3":        "Ctrl+Alt+3",
    "slot_4":        "Ctrl+Alt+4",
    "slot_5":        "",
    "slot_6":        "",
    "evacuate_left": "Ctrl+Alt+Shift+Left",
    "evacuate_right": "Ctrl+Alt+Shift+Right",
    "picker":        "Ctrl+Alt+Q",
    "pin_here":      "Ctrl+Alt+P",
    "show_app":      "Ctrl+Alt+M",
}

DEFAULTS = {
    "version": 1,
    "monitors": {},
    "self": {"chain": [], "follow": True, "rects": {}},
    "apps": {},
    "hotkeys": dict(DEFAULT_HOTKEYS),
    "settings": {
        "poll_ms": 1000,
        "settle_ms": 900,
        "auto_restore": True,
        "learn": True,
        "place_new_windows": True,
        "start_minimized": False,
        "close_quits": False,
        "hotkeys_enabled": True,
        "notify": True,
        "theme": "dark",
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULTS))
        self.load()

    # ------------------------------------------------------------- io
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except (OSError, ValueError):
            pass
        return self.data

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------- shortcuts
    @property
    def monitors(self):
        return self.data["monitors"]

    @property
    def apps(self):
        return self.data["apps"]

    @property
    def selfcfg(self):
        return self.data["self"]

    @property
    def settings(self):
        return self.data["settings"]

    @property
    def hotkeys(self):
        return self.data["hotkeys"]

    # ------------------------------------------------------------- monitors
    def register(self, mon):
        """Add a never-seen monitor, or refresh what we know about a known one."""
        rec = self.monitors.get(mon.key)
        if rec is None:
            rec = mon.as_saved()
            rec["tag"] = self._unique_tag(mon)
            rec["slot"] = self._free_slot()
            rec["created"] = time.strftime("%Y-%m-%d %H:%M")
            self.monitors[mon.key] = rec
        else:
            rec.update(mon.as_saved())
            rec.setdefault("tag", self._unique_tag(mon))
            rec.setdefault("slot", self._free_slot())
        rec["last_seen"] = time.strftime("%Y-%m-%d %H:%M")
        return rec

    def _unique_tag(self, mon):
        used = {r.get("tag") for r in self.monitors.values()}
        base = (mon.model or mon.pnp or "Monitor").strip() or "Monitor"
        if base not in used:
            return base
        i = 2
        while "%s %d" % (base, i) in used:
            i += 1
        return "%s %d" % (base, i)

    def _free_slot(self):
        used = {r.get("slot") for r in self.monitors.values()}
        for i in range(1, 10):
            if i not in used:
                return i
        return 0

    def tag_of(self, key):
        return (self.monitors.get(key) or {}).get("tag", key)

    def key_of_tag(self, tag):
        for k, r in self.monitors.items():
            if r.get("tag") == tag:
                return k
        return None

    def set_tag(self, key, tag):
        tag = (tag or "").strip()
        if not tag:
            return False
        for k, r in self.monitors.items():
            if k != key and r.get("tag") == tag:
                return False
        old = self.tag_of(key)
        if key in self.monitors:
            self.monitors[key]["tag"] = tag
        # keep every reference to the old tag pointing at the renamed monitor
        chain = self.selfcfg.get("chain", [])
        self.selfcfg["chain"] = [tag if t == old else t for t in chain]
        for app in self.apps.values():
            app["chain"] = [tag if t == old else t for t in app.get("chain", [])]
            if app.get("tag") == old:
                app["tag"] = tag
        return True

    def set_slot(self, key, slot):
        for k, r in self.monitors.items():
            if k != key and r.get("slot") == slot:
                r["slot"] = 0
        if key in self.monitors:
            self.monitors[key]["slot"] = int(slot)

    def key_of_slot(self, slot):
        for k, r in self.monitors.items():
            if r.get("slot") == slot:
                return k
        return None

    # ------------------------------------------------------------- apps
    def app_rec(self, app_key, create=True):
        rec = self.apps.get(app_key)
        if rec is None and create:
            rec = {"mode": "remember", "tag": None, "chain": [], "ratios": {},
                   "maximized": False}
            self.apps[app_key] = rec
        return rec

    def forget_app(self, app_key):
        self.apps.pop(app_key, None)
