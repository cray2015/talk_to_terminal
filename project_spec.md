# Project spec: iPhone dictation → Linux keystroke bridge

## 1. Goal

Capture text from iPhone's native, on-device dictation and inject it as
real keystrokes into whatever window currently has focus on a Linux
machine — working uniformly across a GUI text editor, VS Code, and a
terminal running a Claude Code session.

## 2. Design rationale

- Reuse Apple's on-device dictation instead of building or hosting a
  competing speech-to-text pipeline — it already works well.
- Deliver text as OS-level synthetic keystrokes rather than app-specific
  integrations, so no per-app plugin work is needed and any focused
  window works the same way.
- Transport over the local LAN (iPhone and Linux box on the same
  Wi-Fi/router) rather than exposing anything publicly. Since a LAN is
  a broader trust boundary than a private overlay network, the
  shared-secret header is load-bearing, not just defense in depth.

## 3. Architecture

Two components:

**A. iOS Shortcut** (manual, user-configured — not built by Claude Code,
but the exact steps are the acceptance reference for what the Linux side
must accept):
1. "Dictate Text" action.
2. "Get Contents of URL" action — POST, raw text body, to the Linux
   listener's `/type` endpoint, with an `X-Auth` header.

**B. Linux service**, target machine: an HP EliteDesk running Linux Mint
(Cinnamon, X11 by default — verify with `echo $XDG_SESSION_TYPE` before
assuming):
- HTTP listener bound to the box's LAN IP (configurable)
- `/type` endpoint receiving a raw POST text body
- Auth via a shared-secret header
- Injects text as keystrokes into the focused window via `xdotool`
  (X11), behind an abstraction so a `ydotool` backend can be swapped in
  later for Wayland
- Runs as a `systemd --user` service tied to the graphical session
  (needs `DISPLAY`/`XAUTHORITY` correctly available)

**Data flow:** iPhone dictates → Shortcut POSTs raw text → Linux
listener validates the auth header → text is split on `\n` → xdotool
types each line, with a `Return` keypress between lines → text appears
in the focused window.

## 4. Functional requirements

- **FR1** — HTTP POST endpoint `/type` accepting a raw text body,
  protected by a shared-secret header (`X-Auth`).
- **FR2** — Multi-line dictated text is split on `\n`; a `Return`
  keypress is sent between lines rather than a literal newline
  character.
- **FR3** — Must work correctly when the focused window is: a GUI text
  editor, VS Code's editor pane, and specifically a Claude Code CLI
  session running inside a terminal.
- **FR4** — No per-application changes required — injection happens at
  the OS/X11 level.
- **FR5** — Listen host/port and shared secret are configurable (env
  vars or a config file), never hardcoded in source.
- **FR6** — Runs unattended as a systemd user service, restarting on
  failure, starting with the graphical session.
- **FR7** — Text should appear within roughly 1 second of the POST
  arriving under normal conditions.

## 5. Non-functional / operational requirements

- **Security**: bind only to the box's LAN interface address by default
  (never `0.0.0.0`), plus the shared-secret header, which is
  load-bearing on an open LAN rather than pure defense in depth.
  Document how to find and set the LAN IP.
- **Privacy**: no persistence of dictated text — nothing is logged or
  stored beyond the immediate request handling.
- **Reliability**: errors (auth failures, injection failures) are
  logged to stderr/journal without crashing the service.
- **Robustness**: malformed or empty requests are handled gracefully.

## 6. Open questions to resolve while building

- **Terminal input reliability — RESOLVED for the Claude Code CLI case.**
  Tested live from a real iPhone dictation (not a curl simulation) into
  an active Claude Code terminal session: a short phrase ("Check 123 from
  iPhone") and a long ~50-word run-on sentence with no punctuation breaks
  both arrived complete, correctly ordered, and byte-for-byte as spoken —
  user-confirmed against their actual intent, not just visual inspection.
  No reliability knobs were needed; `DICTATION_TYPE_DELAY_MS`,
  `DICTATION_CHUNK_SIZE`, and `DICTATION_INJECTION_MODE=paste` all remain
  at their zero/off defaults. **Still untested**: VS Code's editor pane
  from real dictation (the plain GUI editor was only exercised via
  curl-simulated requests during development, not real dictation either).
  If drops are ever seen against a different target, the fallback order
  remains:
  1. an inter-character delay (`xdotool type --delay <ms>`)
  2. chunking long text into smaller bursts with brief pauses between
  3. as a fallback for terminal targets specifically, clipboard-based
     injection (`xclip` + paste keystroke) instead of simulated typing
- **X11 vs Wayland.** Assume X11 per Mint Cinnamon's default; confirm
  with `echo $XDG_SESSION_TYPE` first. If Wayland, the injection backend
  needs to be `ydotool` instead (requires `input` group membership and
  its own daemon) — keep the injection call behind a small interface so
  this swap doesn't touch the HTTP layer.
- **DISPLAY/XAUTHORITY for the systemd user service.** User systemd
  services don't always inherit the graphical session's `DISPLAY` /
  `XAUTHORITY` cleanly, depending on the display manager. Verify the
  service actually has X access after `systemctl --user start`; if not,
  set `Environment=DISPLAY=:0` and/or `Environment=XAUTHORITY=...`
  explicitly in the unit (confirm the exact `XAUTHORITY` path via `echo
  $XAUTHORITY` in an active desktop session — it varies by display
  manager).

## 7. Reference implementation (starting point)

A minimal working prototype already exists and should be treated as a
first draft to harden, not a finished deliverable:

- `linux_listener.py` — Python stdlib HTTP server, shared-secret auth,
  xdotool-based typing, newline → Return handling
- `dictation-bridge.service` — systemd user unit
- `README.md` — setup steps and the iOS Shortcut configuration

In particular, the prototype hardcodes `LISTEN_HOST`, `LISTEN_PORT`, and
`SHARED_SECRET` as constants — these should move to config (see FR5),
and the terminal-reliability question above hasn't been tested yet.

## 8. Deliverables

- [ ] Config-driven listener (env vars or a small config file, no
      hardcoded secrets)
- [ ] Injection backend abstracted behind an interface — xdotool (X11)
      implementation plus a stub for a future ydotool (Wayland) one
- [ ] systemd user unit, verified to actually start with correct
      DISPLAY/XAUTHORITY
- [x] Resolution of the terminal-reliability open question, tested
      specifically against a Claude Code session — confirmed clean at
      default settings with real iPhone dictation, short and long
      passages (see section 6)
- [ ] Basic structured logging (auth failures, injection errors) to
      stderr/journal — never logging dictated text content itself
- [ ] Updated README covering setup, the iOS Shortcut steps, and
      troubleshooting for the DISPLAY/XAUTHORITY and Wayland cases

## 9. Explicitly out of scope

- Live/streaming word-by-word transcription — this captures Apple's
  dictation output per-utterance, after you stop speaking, not
  continuous streaming
- Any custom speech-to-text model or server
- Public internet exposure — LAN-only by design
- iOS app development — the iPhone side stays a Shortcut, not a custom
  app

## 10. Acceptance test

1. [x] Start the service on the EliteDesk. — running as `dictation-bridge.service`, active/enabled.
2. [x] From the iPhone, on the same LAN/Wi-Fi, run the Shortcut and dictate a
   passage. — done, including a long multi-clause passage beyond the
   original two-sentence target.
3. Confirm identical, complete, correctly-ordered text appears in: a GUI
   text editor, a VS Code buffer, and an active Claude Code terminal
   session — each tested separately with that window focused at the
   moment of dictation.
   - [x] Claude Code terminal — confirmed, short and long passages, user-verified against actual spoken content.
   - [ ] GUI text editor — not yet tested from real dictation (only curl-simulated).
   - [ ] VS Code buffer — not yet tested.
4. [x] Confirm a request without the correct `X-Auth` header is rejected
   (401) and types nothing. — confirmed, both via curl and via the real iPhone Shortcut.
5. [ ] Confirm the service survives a restart of the graphical session, or
   the README documents the manual restart step required. — not yet tested.
