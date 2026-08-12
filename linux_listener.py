#!/usr/bin/env python3
"""HTTP listener that types dictated text into the focused window, and
(Remote mode) sends navigation keystrokes and macros to it.

See project_spec.md for the full design. Config is env-var driven (FR5) —
run via systemd with EnvironmentFile= pointing at config.env, or export
the DICTATION_* vars yourself for manual testing.
"""

import hmac
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

import macros_store
from injection import get_backend

MAX_BODY_BYTES = 64 * 1024  # dictated utterances are short; reject anything absurd
MAX_SMALL_BODY_BYTES = 4 * 1024  # key actions and macro text/ids are much shorter

WEB_DIR = Path(__file__).parent / "web"

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("claude-code-remote")

injection_lock = Lock()
macros_lock = Lock()


def _env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        log.error("missing required config: %s", name)
        sys.exit(1)
    return val


def load_config():
    host = _env("DICTATION_HOST", required=True)
    if host in ("0.0.0.0", "::"):
        log.error(
            "DICTATION_HOST=%s would bind all interfaces; set it to this "
            "box's LAN IP instead (see: ip -4 addr show)",
            host,
        )
        sys.exit(1)

    secret = _env("DICTATION_SHARED_SECRET", required=True)

    return {
        "host": host,
        "port": int(_env("DICTATION_PORT", "8766")),
        "secret": secret,
        "backend_name": _env("DICTATION_BACKEND", "xdotool"),
        "delay_ms": int(_env("DICTATION_TYPE_DELAY_MS", "0")),
        "chunk_size": int(_env("DICTATION_CHUNK_SIZE", "0")),
        "chunk_pause_ms": int(_env("DICTATION_CHUNK_PAUSE_MS", "50")),
        "paste_mode": _env("DICTATION_INJECTION_MODE", "type") == "paste",
        "paste_key_combo": _env("DICTATION_PASTE_KEY_COMBO", "ctrl+shift+v"),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "ClaudeCodeRemote/1.0"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.client_address[0], fmt % args)

    # --- routing ---

    def do_GET(self):
        if self.path == "/":
            self._serve_index()
        elif self.path == "/macros":
            self._handle_macros_list()
        else:
            self._respond(404, b"not found")

    def do_POST(self):
        if self.path == "/type":
            self._handle_type()
        elif self.path == "/key":
            self._handle_key()
        elif self.path == "/macros":
            self._handle_macros_add()
        elif self.path == "/macros/remove":
            self._handle_macros_remove()
        else:
            self._respond(404, b"not found")

    # --- shared helpers ---

    def _check_auth(self) -> bool:
        auth = self.headers.get("X-Auth", "")
        if not hmac.compare_digest(auth, self.server.shared_secret):
            log.warning("auth failure from %s", self.client_address[0])
            self._respond(401, b"unauthorized")
            return False
        return True

    def _read_body(self, max_bytes):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._respond(400, b"missing or invalid Content-Length")
            return None

        if length <= 0:
            self._respond(400, b"empty body")
            return None
        if length > max_bytes:
            self._respond(413, b"body too large")
            return None

        return self.rfile.read(length)

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- page ---

    def _serve_index(self):
        try:
            body = (WEB_DIR / "index.html").read_bytes()
        except OSError:
            log.exception("failed to read web/index.html")
            self._respond(500, b"page unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --- /type ---

    def _handle_type(self):
        if not self._check_auth():
            return

        body = self._read_body(MAX_BODY_BYTES)
        if body is None:
            return

        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            self._respond(400, b"body must be utf-8 text")
            return

        if not text.strip():
            self._respond(400, b"empty text")
            return

        try:
            with injection_lock:
                self.server.backend.type_text(text)
        except Exception:
            log.exception("injection failed")
            self._respond(500, b"injection failed")
            return

        log.info("typed %d line(s)", text.count("\n") + 1)
        self._respond(200, b"ok")

    # --- /key ---

    def _handle_key(self):
        if not self._check_auth():
            return

        body = self._read_body(MAX_SMALL_BODY_BYTES)
        if body is None:
            return

        try:
            action = body.decode("utf-8").strip()
        except UnicodeDecodeError:
            self._respond(400, b"body must be utf-8 text")
            return

        try:
            with injection_lock:
                self.server.backend.press_key(action)
        except ValueError:
            self._respond(400, b"unknown key action")
            return
        except Exception:
            log.exception("key press failed")
            self._respond(500, b"key press failed")
            return

        log.info("pressed key action %r", action)
        self._respond(200, b"ok")

    # --- /macros ---

    def _handle_macros_list(self):
        if not self._check_auth():
            return
        with macros_lock:
            data = macros_store.load()
        self._send_json(200, data)

    def _handle_macros_add(self):
        if not self._check_auth():
            return

        body = self._read_body(MAX_SMALL_BODY_BYTES)
        if body is None:
            return

        try:
            payload = json.loads(body)
            text = payload["text"]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._respond(400, b'expected JSON body: {"text": "..."}')
            return

        try:
            with macros_lock:
                macro = macros_store.add(text)
        except ValueError as e:
            self._respond(400, str(e).encode("utf-8"))
            return

        log.info("macro added")
        self._send_json(201, macro)

    def _handle_macros_remove(self):
        if not self._check_auth():
            return

        body = self._read_body(MAX_SMALL_BODY_BYTES)
        if body is None:
            return

        try:
            payload = json.loads(body)
            macro_id = payload["id"]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._respond(400, b'expected JSON body: {"id": "..."}')
            return

        with macros_lock:
            found = macros_store.remove(macro_id)

        if not found:
            self._respond(404, b"not found")
            return

        log.info("macro removed")
        self._send_json(200, {"ok": True})


def main():
    cfg = load_config()
    backend = get_backend(
        cfg["backend_name"],
        delay_ms=cfg["delay_ms"],
        chunk_size=cfg["chunk_size"],
        chunk_pause_ms=cfg["chunk_pause_ms"],
        paste_mode=cfg["paste_mode"],
        paste_key_combo=cfg["paste_key_combo"],
    )

    server = ThreadingHTTPServer((cfg["host"], cfg["port"]), Handler)
    server.shared_secret = cfg["secret"]
    server.backend = backend

    log.info(
        "listening on %s:%d (backend=%s, mode=%s)",
        cfg["host"],
        cfg["port"],
        cfg["backend_name"],
        "paste" if cfg["paste_mode"] else "type",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
