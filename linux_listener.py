#!/usr/bin/env python3
"""HTTP listener that types dictated text into the focused window.

See project_spec.md for the full design. Config is env-var driven (FR5) —
run via systemd with EnvironmentFile= pointing at config.env, or export
the DICTATION_* vars yourself for manual testing.
"""

import hmac
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

from injection import get_backend

MAX_BODY_BYTES = 64 * 1024  # dictated utterances are short; reject anything absurd

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("dictation-bridge")

injection_lock = Lock()


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
    server_version = "DictationBridge/1.0"

    def log_message(self, fmt, *args):
        log.info("%s - %s", self.client_address[0], fmt % args)

    def do_POST(self):
        if self.path != "/type":
            self._respond(404, b"not found")
            return

        auth = self.headers.get("X-Auth", "")
        if not hmac.compare_digest(auth, self.server.shared_secret):
            log.warning("auth failure from %s", self.client_address[0])
            self._respond(401, b"unauthorized")
            return

        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._respond(400, b"missing or invalid Content-Length")
            return

        if length <= 0:
            self._respond(400, b"empty body")
            return
        if length > MAX_BODY_BYTES:
            self._respond(413, b"body too large")
            return

        body = self.rfile.read(length)
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

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
