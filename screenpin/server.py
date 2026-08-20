"""Local HTTP API + static page host. Bound to 127.0.0.1 and token-gated."""
import json
import os
import secrets
import sys
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

def _web_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, "web")
    if os.path.isdir(local):
        return local
    base = getattr(sys, "_MEIPASS", here)          # PyInstaller bundle
    return os.path.join(base, "screenpin", "web")


WEB_DIR = _web_dir()
MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app = None          # set by Server
    token = ""

    def log_message(self, *_a):
        pass

    # ---------------------------------------------------------------- helpers
    def _send(self, code, body=b"", ctype="application/json; charset=utf-8",
              cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control",
                         "public, max-age=3600" if cache else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _icon(self):
        """The window/taskbar icon of the app window comes from here."""
        path = getattr(self.app, "icon_path", None)
        if not path or not os.path.isfile(path):
            return self._send(404, b"", "text/plain")
        with open(path, "rb") as f:
            self._send(200, f.read(), "image/x-icon", cache=True)

    def _app_icon(self, path):
        """PNG of a running app's own icon: /icon/<hwnd>.png"""
        try:
            hwnd = int(os.path.splitext(path.rsplit("/", 1)[-1])[0])
        except ValueError:
            return self._send(404, b"", "text/plain")
        png = self.app.window_icon(hwnd)
        if not png:
            return self._send(404, b"", "text/plain")
        self._send(200, png, "image/png", cache=True)

    def _auth(self, qs):
        given = (qs.get("k") or [""])[0] or self.headers.get("X-ScreenPin-Key", "")
        return secrets.compare_digest(given, self.token)

    # ---------------------------------------------------------------- routes
    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path.startswith("/api/"):
            if not self._auth(qs):
                return self._json({"error": "forbidden"}, 403)
            if u.path == "/api/state":
                since = int((qs.get("since") or ["-1"])[0])
                state = self.app.wait_state(since)
                return self._json(state)
            return self._json({"error": "not found"}, 404)
        return self._static(u.path)

    do_HEAD = do_GET

    def do_POST(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if not self._auth(qs):
            return self._json({"error": "forbidden"}, 403)
        if u.path != "/api/action":
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, OSError):
            return self._json({"error": "bad json"}, 400)
        try:
            result = self.app.do_action(payload)
        except Exception as e:                       # never kill the server
            return self._json({"ok": False, "msg": repr(e)}, 200)
        return self._json(result)

    def _static(self, path):
        if path == "/favicon.ico":
            return self._icon()
        if path.startswith("/icon/"):
            return self._app_icon(path)
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(WEB_DIR, name))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            return self._send(404, b"not found", "text/plain")
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as f:
            data = f.read()
        if ext == ".html":
            data = data.replace(b"__TOKEN__", self.token.encode())
        self._send(200, data, MIME.get(ext, "application/octet-stream"),
                   cache=(ext != ".html"))


class Server:
    def __init__(self, app, host="127.0.0.1", port=0):
        self.token = secrets.token_urlsafe(18)
        handler = type("BoundHandler", (Handler,),
                       {"app": app, "token": self.token})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.3},
                                       daemon=True, name="screenpin-http")

    @property
    def url(self):
        return "http://127.0.0.1:%d/?k=%s" % (self.port, self.token)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass
