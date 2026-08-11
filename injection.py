"""Keystroke-injection backends for the dictation bridge.

Kept behind the InjectionBackend interface so the HTTP layer never has to
change when swapping X11 (xdotool) for Wayland (ydotool) — see
project_spec.md section 3 and the "X11 vs Wayland" open question.
"""

import subprocess
import time
from abc import ABC, abstractmethod


class InjectionBackend(ABC):
    @abstractmethod
    def type_text(self, text: str) -> None:
        """Inject text into whatever window currently has focus."""


def _chunks(s: str, size: int):
    for i in range(0, len(s), size):
        yield s[i : i + size]


class XdotoolBackend(InjectionBackend):
    """X11 backend. Two delivery modes:

    - "type" (default): xdotool type + a Return keypress between lines.
      Reliability knobs (delay_ms, chunk_size) exist because fast synthetic
      key bursts can be dropped/reordered by some terminal emulators — see
      project_spec.md section 6.
    - "paste": set the clipboard (xclip) and send one paste keystroke for
      the whole utterance, letting the target app's own paste handling
      (e.g. a terminal's bracketed paste) reproduce the newlines. Intended
      as the last-resort fallback for terminal targets specifically.
    """

    def __init__(
        self,
        delay_ms: int = 0,
        chunk_size: int = 0,
        chunk_pause_ms: int = 50,
        paste_mode: bool = False,
        paste_key_combo: str = "ctrl+shift+v",
        **_ignored,
    ):
        self.delay_ms = delay_ms
        self.chunk_size = chunk_size
        self.chunk_pause_ms = chunk_pause_ms
        self.paste_mode = paste_mode
        self.paste_key_combo = paste_key_combo

    def type_text(self, text: str) -> None:
        if self.paste_mode:
            self._paste(text)
        else:
            self._type(text)

    def _type(self, text: str) -> None:
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if line:
                self._type_line(line)
            if i < len(lines) - 1:
                self._run(["xdotool", "key", "--clearmodifiers", "Return"])

    def _type_line(self, line: str) -> None:
        if self.chunk_size > 0:
            for chunk in _chunks(line, self.chunk_size):
                self._type_raw(chunk)
                if self.chunk_pause_ms:
                    time.sleep(self.chunk_pause_ms / 1000)
        else:
            self._type_raw(line)

    def _type_raw(self, s: str) -> None:
        cmd = ["xdotool", "type", "--clearmodifiers"]
        if self.delay_ms:
            cmd += ["--delay", str(self.delay_ms)]
        cmd.append(s)
        self._run(cmd)

    def _paste(self, text: str) -> None:
        subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text.encode("utf-8"),
            check=True,
            timeout=5,
        )
        self._run(["xdotool", "key", "--clearmodifiers", self.paste_key_combo])

    @staticmethod
    def _run(cmd) -> None:
        subprocess.run(cmd, check=True, timeout=10)


class YdotoolBackend(InjectionBackend):
    """Wayland stub. Not implemented yet — see project_spec.md section 6.

    To implement: install ydotool + run ydotoold, add the service user to
    the `input` group, then mirror XdotoolBackend using `ydotool type` /
    `ydotool key` in place of the xdotool calls. The HTTP layer and config
    (DICTATION_BACKEND=ydotool) already route to this class unchanged.
    """

    def __init__(self, **_ignored):
        pass

    def type_text(self, text: str) -> None:
        raise NotImplementedError(
            "ydotool backend is a stub — implement type_text() in "
            "injection.YdotoolBackend before setting DICTATION_BACKEND=ydotool"
        )


def get_backend(name: str, **kwargs) -> InjectionBackend:
    if name == "xdotool":
        return XdotoolBackend(**kwargs)
    if name == "ydotool":
        return YdotoolBackend(**kwargs)
    raise ValueError(f"unknown injection backend: {name!r}")
