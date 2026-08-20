# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with
code in this repository.

## Build Commands

Python 3 standard library only — no build step, no dependencies to install.
The external requirements are the injection tools themselves (`xdotool`, and
`xclip` only if `DICTATION_INJECTION_MODE=paste`).

```bash
# Run manually — needs the DICTATION_* vars exported, or source config.env first
set -a; . ~/.config/talk-to-terminal/config.env; set +a
python3 linux_listener.py

# Normal operation: systemd USER service. These are invisible to plain
# systemctl without --user; omitting it is the most common wrong-result here.
systemctl --user restart talk-to-terminal.service
systemctl --user status  talk-to-terminal.service
journalctl --user -u talk-to-terminal.service -f
```

There are no tests in this project. Verification is the acceptance criteria in
`project_spec.md` §10, exercised from a real phone rather than curl — several
of those checks only fail against real dictation.

## Layout

- **`linux_listener.py`** — routing, auth, body limits, config. Holds
  `injection_lock`; every injection call in the process goes through it.
- **`injection.py`** — `InjectionBackend` ABC plus `XdotoolBackend` and the
  `YdotoolBackend` stub, and `KEY_ACTIONS`, the `/key` allowlist. The HTTP
  layer never calls `xdotool` directly.
- **`macros_store.py`** — reads/writes `~/.config/talk-to-terminal/macros.json`.
- **`web/index.html`** — the phone page, served by `GET /`. Self-contained.

Config lives in `~/.config/talk-to-terminal/config.env`, not in the repo;
`config.env.example` is the template. It holds the shared secret — never commit it.

## Key Constraints

- **The port is 8766, not 8765** — `url-opener` already holds 8765 on this box.
  Changing `DICTATION_PORT` also means updating the URL bookmarked on the phone.

- **Never log dictated text.** The listener logs a line *count*
  (`log.info("typed %d line(s)", ...)`), never content, and macro handlers log
  "macro added" without the text. Adding the payload to a log line would work
  fine and silently break the privacy guarantee. See `project_spec.md` §8.

- **`KEY_ACTIONS` keys are a wire contract with the page.** The dict keys in
  `injection.py` are exactly the strings `web/index.html` sends: the
  `data-key="..."` attribute values, plus the `sendKey("ctrl+e")` /
  `sendKey("ctrl+u")` literals. Renaming a key breaks those buttons with a 400
  at press time and no build-time signal. Add new actions to both sides
  together. (`injection.py`'s docstring calls this attribute `data-action` —
  the attribute is actually `data-key`.)

- **`ctrl+e` and `ctrl+u` are load-bearing, not spare keys.** They implement
  clear-current-line as End-then-kill-backward, because readline-based inputs
  (a shell, Claude Code's prompt) treat Ctrl+A as "jump to line start", not
  "select all". Don't prune them as unused — no button carries their name.

- **`DICTATION_HOST` must be a specific LAN address.** `load_config()` exits
  with status 1 on `0.0.0.0` or `::` rather than warning. This is deliberate;
  don't relax it to make local testing easier. See `project_spec.md` §8.

- **The unit is `WantedBy=default.target`, never `graphical-session.target`.**
  On Mint Cinnamon the latter is never reliably activated, so the service shows
  `enabled` and silently never auto-starts. See `project_spec.md` §11.

- **`YdotoolBackend` is a stub.** `DICTATION_BACKEND=ydotool` is accepted at
  startup and raises `NotImplementedError` on the first request, not at boot.
  Check `echo $XDG_SESSION_TYPE` before assuming X11.

- **Every endpoint checks `X-Auth` first**, including `GET /macros` and both
  `/macros` writes — not just `/type` and `/key`. New routes must call
  `_check_auth()` before reading a body.

- **`macros.json` is written atomically** (`mkstemp` + `os.replace`) and
  `_migrate()` converts the original single-list format on load. Keep both when
  touching that file — dropping the migration silently discards saved Claude
  macros on the next read.
