# Talk to Terminal — project spec

## 1. Overview

Captures text from a phone's native, on-device dictation (iOS or Android) and
injects it as real keystrokes into whatever window currently has focus on a
Linux machine — working uniformly across a GUI text editor, VS Code, and a
terminal running either a Claude Code or Codex CLI session. A Remote mode on
the same page adds navigation keystrokes and per-target command macros, so the
phone drives the focused terminal as well as feeding it text.

## 2. Goals

- Reuse the phone's own on-device dictation as the text source — no
  competing speech-to-text pipeline to build or host.
- Deliver text as OS-level synthetic keystrokes, so any focused window works
  the same way with no per-app integration.
- Work identically against a GUI text editor, VS Code's editor pane, and
  Claude Code / Codex CLI sessions in a terminal.
- Stay entirely on the LAN, authenticated by a shared secret.
- Drive the focused terminal from the phone — navigation keys and editable
  per-target command macros — without a second service.

## 3. Non-Goals

<!-- Tag names when the item could come back, not what release excluded it:
     [never]       — permanently out of scope, architectural or by principle
     [v2] / [v3]   — deferred to that release
     [unplanned]   — not ruled out, not scheduled
     [superseded]  — reversed; annotate in place, never delete -->

- **[never]** Live/streaming word-by-word transcription — this captures the
  phone's dictation output per-utterance, after you stop speaking, not
  continuously. It follows directly from reusing the platform's own dictation.
- **[never]** Any custom speech-to-text model or server.
- **[never]** Public internet exposure — LAN-only by design; see §8.
- **[never]** Native app development for either phone platform — the phone
  side stays a browser page.

## 4. Design rationale and constraints

- **Reuse the phone's on-device dictation** rather than building or hosting a
  competing speech-to-text pipeline — it already works well on iOS and Android.
- **Inject at the OS level, not per-app.** Synthetic keystrokes mean no plugin
  work for any target, and any focused window behaves the same.
- **LAN transport, not a public endpoint or an overlay network.** Since a LAN
  is a broader trust boundary than a private overlay, the shared-secret header
  is load-bearing, not defence in depth.
- **Remote mode reuses the same transport rather than adding a service.**
  `/key` is a second capability on the existing listener; the focused terminal
  alone determines whether input reaches Claude Code or Codex CLI.
- **Injection sits behind an interface** so a Wayland (`ydotool`) backend can
  replace X11 (`xdotool`) without touching the HTTP layer — see §11.

## 5. Architecture

Two components: a browser page served by the Linux service itself, and the
Linux service that receives from it.

**A. Browser page** — the sole, cross-platform input method, built by this
project. Works on iOS Safari or Android Chrome via each platform's own native
on-screen-keyboard dictation, with no app install.

**B. Linux service** — an HP EliteDesk running Linux Mint (Cinnamon, X11 by
default; verify with `echo $XDG_SESSION_TYPE` before assuming):

- HTTP listener bound to the box's LAN IP, never all interfaces
- `/type` receiving a raw POST text body; `/key` receiving a named action
- Auth via a shared-secret `X-Auth` header on every endpoint
- Injects into the focused window via `xdotool` (X11), behind an abstraction
  that a `ydotool` backend can be swapped into later for Wayland
- Runs as a `systemd --user` service, `WantedBy=default.target`

**Data flow:** phone dictates via the browser page → raw text POSTed to
`/type` → listener validates the auth header → text is split on `\n` →
xdotool types each line, with a `Return` keypress between lines → text appears
in the focused window.

Diagram source: `docs/architecture.d2`. Render on demand with
`d2 docs/architecture.d2 docs/architecture.svg` — the `.d2` is the source of
truth; the rendered SVG is not committed.

### 5.1 Remote mode

The same page and process add a second capability alongside dictation:

- A persistent per-browser target selector for **Claude Code** or **Codex
  CLI**. It changes only the remote controls; dictation and Send always POST
  to `/type` and remain target-agnostic.
- `POST /key` takes a named action string, mapped server-side to
  `xdotool key <combo>` against a fixed allowlist — mechanically distinct from
  `/type`'s literal-text typing.
- Two button categories, since they are mechanically different:
  - **Key-combo buttons** (a single `xdotool key` call): Tab, Shift+Tab,
    Enter, Esc, Ctrl+C, and 1/2/3 for navigation, interruption, and numbered
    prompts.
  - **Quick-command macros** (types literal text, then Enter, via the
    `/type` path rather than `/key`): separate user-configurable lists per
    target. Claude starts with `/model`, `/context`, `/cost`, `/vis`; Codex
    starts with `/model`, `/new`, `/resume`, `/status`. Editable from the page
    and persisted server-side.
  - **Codex workflow controls**: when Codex is selected, a prominent
    **Plan ↔ Default** button sends Shift+Tab, and **Permissions** types and
    submits `/permissions`. Codex's approval policy is separate from its
    Plan/Default toggle.

## 6. Components

| Path | Role |
|---|---|
| `linux_listener.py` | HTTP listener — routing, `X-Auth` check, body-size limits, config loading; owns the injection lock |
| `injection.py` | `InjectionBackend` interface, `XdotoolBackend`, `YdotoolBackend` stub, and the `KEY_ACTIONS` allowlist |
| `macros_store.py` | Per-target macro persistence to `~/.config/talk-to-terminal/macros.json` |
| `web/index.html` | Phone page — dictation box, target selector, remote controls, macro editor |
| `talk-to-terminal.service` | systemd user unit |
| `config.env.example` | Template for `~/.config/talk-to-terminal/config.env` |
| `docs/architecture.d2` | Architecture diagram source |

## 7. Functional requirements

- **Dictation endpoint** — `POST /type` accepts a raw text body, protected by
  a shared-secret header (`X-Auth`).
- **Newline handling** — multi-line dictated text is split on `\n`; a `Return`
  keypress is sent between lines rather than a literal newline character.
- **Target coverage** — must work correctly when the focused window is a GUI
  text editor, VS Code's editor pane, or a Claude Code or Codex CLI session
  running inside a terminal.
- **No per-app changes** — injection happens at the OS/X11 level.
- **Configurability** — listen host/port and shared secret come from env vars
  or a config file, never hardcoded in source.
- **Unattended operation** — runs as a systemd user service, restarting on
  failure, starting with the graphical session.
- **Latency** — text should appear within roughly 1 second of the POST
  arriving, under normal conditions.
- **Key endpoint** — `POST /key` accepts a named key/combo, validated against
  an allowlist, mapped to the correct `xdotool key` syntax.
- **Editable macros** — macro lists are user-configurable from the page,
  persisted separately for Claude Code and Codex, and are not hardcoded as the
  only available commands.
- **Target-appropriate controls** — Claude Code retains a compact Shift+Tab
  permission-mode control; Codex promotes Shift+Tab as **Plan ↔ Default** and
  exposes `/permissions`. Esc / Ctrl+C / 1-2-3 remain smaller secondary
  controls.

## 8. Operational requirements

- **Security** — bind only to the box's LAN interface address by default,
  never `0.0.0.0`, plus the shared-secret header, which is load-bearing on an
  open LAN rather than pure defence in depth. Document how to find and set the
  LAN IP.
- **Privacy** — no persistence of dictated text; nothing is logged or stored
  beyond the immediate request handling.
- **Reliability** — errors (auth failures, injection failures) are logged to
  stderr/journal without crashing the service.
- **Robustness** — malformed or empty requests are handled gracefully.

## 9. Milestones

- [x] M1 — Config-driven listener: `DICTATION_HOST` and `DICTATION_SHARED_SECRET` required with no fallback, everything else env-driven
- [x] M2 — Injection behind an interface: `InjectionBackend` ABC, `XdotoolBackend`, and a `YdotoolBackend` stub for Wayland
- [x] M3 — systemd user unit verified to start with correct DISPLAY/XAUTHORITY, after switching `WantedBy=` to `default.target` (see §11)
- [x] M4 — Terminal-reliability question resolved against a Claude Code session: clean at default settings with real iPhone dictation, short and long passages (see §11)
- [x] M5 — Structured logging of auth failures and injection errors to stderr/journal, never logging dictated text content
- [x] M6 — README covering setup and troubleshooting for the DISPLAY/XAUTHORITY and Wayland cases
- [x] M7 — Remote mode: browser page served by the same listener, `POST /key` with a server-side allowlist, editable per-target macro lists persisted to `~/.config/talk-to-terminal/macros.json`
- [x] M8 — Target selector with independent Claude Code and Codex CLI macro profiles, plus Codex Plan ↔ Default and Permissions controls

## 10. Acceptance criteria

1. [x] Start the service on the EliteDesk. — running as `talk-to-terminal.service`, active/enabled.
2. [x] From the iPhone, on the same LAN/Wi-Fi, dictate a passage. — done, including a long multi-clause passage beyond the original two-sentence target.
3. Confirm identical, complete, correctly-ordered text appears in each target,
   tested separately with that window focused at the moment of dictation:
   - [x] Claude Code terminal — confirmed, short and long passages, user-verified against actual spoken content.
   - [x] Codex CLI terminal — confirmed from real dictation.
   - [x] GUI text editor — confirmed from real dictation.
   - [x] VS Code buffer — confirmed.
4. [x] Confirm a request without the correct `X-Auth` header is rejected (401) and types nothing. — confirmed, both via curl and via the real iPhone browser page.
5. [x] Confirm the service survives a restart of the graphical session, or the README documents the manual restart step required. — confirmed.
6. [ ] Remote mode: verify `/key` rejects an off-allowlist action with 400 and presses nothing, presses the correct combo for a valid action such as `tab`, and returns 401 on `/key` or `/macros*` with a wrong or missing `X-Auth`.
7. [x] Remote mode: adding and removing a macro from the Remote tab updates `GET /macros` immediately (no restart), and the change survives a service restart (file-backed persistence).
8. [x] Remote mode: exercised against real, focused Claude Code and Codex CLI terminal sessions. Verified Tab/Shift+Tab/Enter/Esc/Ctrl+C/1-2-3 and at least one macro per target; for Codex, also verified Plan ↔ Default and `/permissions` against the semantics in §11.

<!-- Checkbox rules — this file is the ONLY source the Trello sync reads.
     `- [ ]` for unordered work, `N. [ ]` where order is the point. Both parse
     the same; the list marker is stripped before hashing, so renumbering or
     inserting a step never strands a card.
     One physical line per task — only the first line reaches the card.
     Never reword a pending task in place: card identity is a hash of the task
     text, so an edit strands the old card and creates a new one. To retire a
     task, check it off; to change its meaning, check the old one and add a
     new line. -->

## 11. Open questions

- **Terminal input reliability — RESOLVED for the Claude Code CLI case.**
  Tested live from real iPhone dictation (not a curl simulation) into an
  active Claude Code terminal session: a short phrase ("Check 123 from
  iPhone") and a long ~50-word run-on sentence with no punctuation breaks both
  arrived complete, correctly ordered, and byte-for-byte as spoken —
  user-confirmed against their actual intent, not just visual inspection. No
  reliability knobs were needed; `DICTATION_TYPE_DELAY_MS`,
  `DICTATION_CHUNK_SIZE`, and `DICTATION_INJECTION_MODE=paste` all remain at
  their zero/off defaults. If drops are ever seen against a different target,
  the fallback order remains:
  1. an inter-character delay (`xdotool type --delay <ms>`)
  2. chunking long text into smaller bursts with brief pauses between
  3. as a fallback for terminal targets specifically, clipboard-based
     injection (`xclip` + paste keystroke) instead of simulated typing
- **X11 vs Wayland.** Assume X11 per Mint Cinnamon's default; confirm with
  `echo $XDG_SESSION_TYPE` first. If Wayland, the injection backend needs to be
  `ydotool` instead (requires `input` group membership and its own daemon) —
  the injection call is already behind an interface so this swap doesn't touch
  the HTTP layer.
- **`WantedBy=graphical-session.target` — RESOLVED, do not use.** On this box
  (Mint Cinnamon), `graphical-session.target` is never reliably activated by
  the session, so a unit `WantedBy=` only that target silently never
  auto-starts on login/reboot despite showing `enabled`. Fixed by switching to
  `WantedBy=default.target`, which fires reliably on every login;
  `DISPLAY`/`XAUTHORITY` are already present in the user systemd instance's
  environment regardless of which target triggered the start (confirmed via
  `systemctl --user show-environment`). Verify with `systemctl --user
  is-enabled talk-to-terminal.service` and `systemctl --user list-units
  --type=service --all` after any reboot — these are **user** services,
  invisible to plain `systemctl` without `--user`.
- **DISPLAY/XAUTHORITY for the systemd user service.** User systemd services
  don't always inherit the graphical session's `DISPLAY` / `XAUTHORITY`
  cleanly, depending on the display manager. Verify the service actually has X
  access after `systemctl --user start`; if not, set `Environment=DISPLAY=:0`
  and/or `Environment=XAUTHORITY=...` explicitly in the unit (confirm the exact
  `XAUTHORITY` path via `echo $XAUTHORITY` in an active desktop session — it
  varies by display manager).
- **Claude Code keybinding semantics — reference, not open**, kept here so the
  implementer doesn't have to re-verify: Shift+Tab cycles plan mode /
  accept-edits / auto mode; Esc interrupts, double-Esc opens the rewind menu;
  Ctrl+C cancels the current task without exiting; plan/permission approval
  prompts are numbered menus confirmed with Enter; `/model`, `/context`, and
  `/cost` are typed slash commands, not keystrokes — which is why they go
  through the macro (`/type`) path rather than `/key`.
- **Codex CLI keybinding semantics — reference, not open:** Shift+Tab toggles
  Default ↔ Plan mode. It does not cycle approval policies; `/permissions`
  opens Codex's approval-policy controls. The browser page must present these
  as separate actions and must not apply Codex desktop behaviour to the
  terminal CLI target.

## 12. Files

- `project_spec.md` — this file
- `CLAUDE.md` — build/run commands and the invariants that fail silently
- `README.md` — setup steps for the browser page, and troubleshooting
- `docs/architecture.d2` — architecture diagram source
- `linux_listener.py` — Python stdlib HTTP server, shared-secret auth,
  xdotool-based typing, newline → Return handling
- `injection.py` — injection backends and the `/key` action allowlist
- `macros_store.py` — per-target macro persistence
- `web/index.html` — the phone page
- `talk-to-terminal.service` — systemd user unit
- `config.env.example` — config template; the real `config.env` lives in
  `~/.config/talk-to-terminal/` and is never committed
