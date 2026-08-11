# iPhone dictation -> Linux keystrokes

Dictate on your iPhone using Apple's own on-device dictation, and have the
text typed straight into whatever's focused on your Linux box — text
editor, VS Code, a terminal running Claude Code, anything. A small
browser page (section 6) also lets you drive a focused Claude Code
session directly — Tab/Enter/Esc, approval menus, and custom macros
like `/model` or `/cost` — without dictating each command. Transport is
your local LAN (iPhone and this box on the same Wi-Fi/router) — see
`project_spec.md` for the full design and rationale.

## 1. Linux side setup

```bash
sudo apt install xdotool xclip   # xclip only needed for the paste fallback (section 4)
```

The service runs directly out of this checkout (`~/workspace/iphone_dict_capture/`)
— no separate copy step, so a `git pull` here and a service restart is all
an update takes. Keep the checkout where the systemd unit expects it
(`~/workspace/iphone_dict_capture/`), or edit `ExecStart` in
`dictation-bridge.service` if you keep it elsewhere.

Create your config from the template — this holds the shared secret, so
it's kept out of the app directory and out of git:

```bash
mkdir -p ~/.config/dictation-bridge
cp config.env.example ~/.config/dictation-bridge/config.env
```

Edit `~/.config/dictation-bridge/config.env`:

- `DICTATION_HOST` — this box's LAN IP (find it with `ip -4 addr show`,
  or `hostname -I`). Never `0.0.0.0` — the listener refuses to start with
  that value (see project_spec.md section 5).
- `DICTATION_SHARED_SECRET` — generate one with `openssl rand -hex 32`.

Install and start it as a **user** service (not system-wide) so it
inherits your graphical session's DISPLAY automatically:

```bash
mkdir -p ~/.config/systemd/user
cp dictation-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dictation-bridge.service
systemctl --user status dictation-bridge.service
journalctl --user -u dictation-bridge.service -f   # watch logs (never logs dictated text)
```

If xdotool silently does nothing, it's almost always a DISPLAY/XAUTHORITY
mismatch — see the "Troubleshooting" section below and the commented-out
lines in `dictation-bridge.service`.

Quick manual test from the same machine:

```bash
curl -i -X POST http://localhost:8766/type \
  -H "X-Auth: <your secret>" \
  --data "hello from curl"
```

Click into a text editor first — the text should get typed there. A
request with a wrong/missing `X-Auth` should come back `401` and type
nothing:

```bash
curl -i -X POST http://localhost:8766/type -H "X-Auth: wrong" --data "nope"
```

## 2. Find your LAN address

```bash
ip -4 addr show    # or: hostname -I
```

Use the address on your actual LAN interface (e.g. `eno1`/`wlan0`), not
`docker0` or `127.0.0.1`. You'll POST to
`http://<that-ip>:8766/type` from the iPhone, as long as it's on the same
network — no port forwarding needed, but also no protection beyond the
shared secret once you're both on that network (see project_spec.md
section 5 — the secret is load-bearing here, not just defense in depth).

## 3. iOS Shortcut ("Dictate to Linux")

1. Shortcuts app -> new Shortcut, name it "Dictate to Linux".
2. Add action **Dictate Text**. Set "Stop Listening" to whichever feels
   natural (After Pause is usually best for continuous use).
3. Add action **Get Contents of URL**:
   - URL: `http://<lan-ip>:8766/type`
   - Method: POST
   - Headers: `X-Auth` = `<your secret>`
   - Request Body: **File** (not JSON or Form — Form multipart-encodes
     with field names/boundaries, which this listener doesn't parse).
     Tap the File field and pick the "Dictated Text" variable from step 2;
     Shortcuts sends its raw bytes as the body, which is what the
     listener expects (it just reads `Content-Length` bytes as UTF-8).
4. Add the Shortcut to your Home Screen, and/or assign it to the Action
   Button or Back Tap (Settings -> Accessibility -> Touch -> Back Tap)
   for one-tap access from anywhere.

## 4. Terminal reliability (read before relying on this for Claude Code)

`xdotool type` sends synthetic X11 key events. Some terminal emulators or
TUI apps — including a Claude Code CLI session — may drop or reorder
characters when text arrives in a fast burst. This hasn't been tested
against live dictation yet; when you do, work down this list in
`~/.config/dictation-bridge/config.env` if you see drops:

1. `DICTATION_TYPE_DELAY_MS` — adds a per-character delay to `xdotool
   type` (try `20`–`50`).
2. `DICTATION_CHUNK_SIZE` / `DICTATION_CHUNK_PAUSE_MS` — splits each line
   into smaller bursts with a pause between them.
3. `DICTATION_INJECTION_MODE=paste` — last resort for terminal targets:
   instead of simulating keypresses, the whole utterance is put on the
   clipboard (`xclip`) and pasted with one keystroke
   (`DICTATION_PASTE_KEY_COMBO`, default `ctrl+shift+v` — the usual
   terminal paste binding; GUI apps typically want `ctrl+v` instead, so
   this mode is meant for terminal-focused use, not as the global
   default).

Restart the service after editing the config
(`systemctl --user restart dictation-bridge.service`).

## 5. Troubleshooting

**xdotool does nothing / errors about no display:**
The `systemd --user` service doesn't always inherit `DISPLAY`/`XAUTHORITY`
from the graphical session depending on the display manager. Check what
the service actually sees:

```bash
systemctl --user show-environment | grep -E 'DISPLAY|XAUTHORITY'
```

Compare against an active desktop terminal:

```bash
echo $DISPLAY $XAUTHORITY
```

If they differ (or the service's are empty), uncomment the `Environment=`
lines in `dictation-bridge.service`, set them to the values from `echo`
above, then `systemctl --user daemon-reload && systemctl --user restart
dictation-bridge.service`.

**Confirming X11 vs Wayland:**

```bash
echo $XDG_SESSION_TYPE
```

If this says `wayland`, `xdotool` won't work — set
`DICTATION_BACKEND=ydotool` and implement `YdotoolBackend.type_text()` in
`injection.py` first (it's currently a stub that raises
`NotImplementedError`; requires installing `ydotool` + `ydotoold` and
adding the service user to the `input` group).

**Service doesn't survive a graphical-session restart:**
Since the unit is `WantedBy=graphical-session.target`, it should restart
automatically with the session. If it doesn't come back after a logout/
login or reboot, run `systemctl --user enable --now
dictation-bridge.service` manually as a workaround and note that here.

## 6. Browser remote page

The listener also serves a small browser page — a Dictate tab (a
browser-based alternative to the iOS Shortcut) and a Remote tab for
driving a focused Claude Code session without dictating each command.
No separate service and no new dependency: it's the same
`dictation-bridge.service` process, same port.

**Deploying this for the first time** still needs the normal update
steps — `git pull` in the checkout, then
`systemctl --user restart dictation-bridge.service` — same as any other
code change. After that, editing the macro list from the page itself
does **not** require a restart (see below).

Open `http://<lan-ip>:8766/` on your phone (or desktop) browser. On
first load you'll be asked for the shared secret — the same value as
`DICTATION_SHARED_SECRET` in `config.env`. It's saved in the browser's
`localStorage` so you only enter it once per device; note that anything
in `localStorage` is visible to anyone with devtools access to that
browser, which is an accepted trade-off consistent with the existing
threat model (anyone who has the secret can already `curl /type`
directly — the browser is just another such client). Use "Change
secret" if you ever need to re-enter it (e.g. after rotating
`DICTATION_SHARED_SECRET`).

**Dictate tab**: a text box that POSTs to `/type`, same as the iOS
Shortcut. iOS Safari's on-screen keyboard mic button works in any
focused text field, so this doubles as a real dictation path from the
browser, not just a paste box.

**Remote tab**: buttons that POST to the new `/key` endpoint (a named
action, validated server-side against a fixed allowlist, mapped to
`xdotool key <combo>` — see `project_spec.md` section 3, "Remote mode")
and to a macro list (typed literal text + Enter). Tied to actual Claude
Code behavior:

- **Tab / Shift+Tab / Enter** (primary row) — Shift+Tab cycles plan
  mode/accept-edits/auto mode; Enter confirms whatever's focused,
  including numbered approval/plan menus.
- **Macros** (primary row, next to nav) — a user-editable list of text
  snippets, starting with `/model`, `/context`, `/cost`, `/vis`. Tap
  "+ Add" to add one, tap the "×" on a chip to remove it. Edits are
  saved to `~/.config/dictation-bridge/macros.json` immediately —
  **no service restart needed** to pick them up, since the file is read
  fresh on every request. Clicking a macro types the literal text, then
  presses Enter (two separate calls under the hood, not a trick with a
  trailing newline — see `project_spec.md` for why).
- **Esc / Ctrl+C / 1 / 2 / 3** (secondary row, smaller) — occasional-use
  actions: Esc interrupts (double-Esc opens the rewind menu), Ctrl+C
  cancels the current task without exiting, and 1/2/3 pick options in
  numbered plan/permission menus (still confirmed with Enter).

Manual checks, same style as section 1's curl test:

```bash
curl -i -X POST http://localhost:8766/key -H "X-Auth: <your secret>" --data "tab"
curl -i -X POST http://localhost:8766/key -H "X-Auth: <your secret>" --data "bogus"   # 400, not in the allowlist
curl -i http://localhost:8766/macros -H "X-Auth: <your secret>"                        # seeded macro list
```

## Notes

- LAN binding + the shared secret means anyone else on your network could
  reach the endpoint, but only someone with the secret can get it to type
  anything.
- Works identically across GUI apps because it's simulating real keyboard
  input at the X11 level — nothing app-specific to configure per tool.
  Terminal targets may need the reliability knobs in section 4.
- No dictated text is ever logged — only line counts, auth failures, and
  injection errors go to the journal.
- If you switch this box to Wayland later, see "Confirming X11 vs
  Wayland" above — the HTTP layer doesn't change either way.
