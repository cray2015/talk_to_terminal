"""Persistence for the user-configurable, per-tool macro lists (FR11).

Macros are short text snippets (e.g. "/model") typed via the same path
as dictated text, then submitted with a `/key enter` press — see the
"Remote mode" section of project_spec.md. Stored as JSON so they can be
added/removed from the browser page with no service restart.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path

MACROS_PATH = Path.home() / ".config" / "talk-to-terminal" / "macros.json"
DEFAULT_MACROS = {
    "claude": ["/model", "/context", "/cost", "/vis"],
    "codex": ["/model", "/new", "/resume", "/status"],
}
VALID_TARGETS = frozenset(DEFAULT_MACROS)
MAX_MACRO_TEXT_BYTES = 2048


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _seed() -> dict:
    data = {
        "profiles": {
            target: [{"id": _new_id(), "text": text} for text in defaults]
            for target, defaults in DEFAULT_MACROS.items()
        }
    }
    _write(data)
    return data


def _write(data: dict) -> None:
    MACROS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=MACROS_PATH.parent, prefix=".macros-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, MACROS_PATH)
    except BaseException:
        os.unlink(tmp_path)
        raise


def _validate_target(target: str) -> str:
    if not isinstance(target, str) or target not in VALID_TARGETS:
        raise ValueError("unknown target")
    return target


def _migrate(data: dict) -> tuple[dict, bool]:
    """Convert the original single-list file without losing Claude macros."""
    if "profiles" in data:
        return data, False
    if isinstance(data.get("macros"), list):
        return {
            "profiles": {
                "claude": data["macros"],
                "codex": [{"id": _new_id(), "text": text} for text in DEFAULT_MACROS["codex"]],
            }
        }, True
    return _seed(), False


def load() -> dict:
    if not MACROS_PATH.exists():
        return _seed()
    with open(MACROS_PATH, "r") as f:
        data = json.load(f)
    data, changed = _migrate(data)
    if changed:
        _write(data)
    return data


def list_for(target: str) -> list[dict]:
    target = _validate_target(target)
    data = load()
    return data["profiles"][target]


def add(target: str, text: str) -> dict:
    target = _validate_target(target)
    text = text.strip()
    if not text:
        raise ValueError("macro text must not be empty")
    if len(text.encode("utf-8")) > MAX_MACRO_TEXT_BYTES:
        raise ValueError("macro text too long")

    data = load()
    macro = {"id": _new_id(), "text": text}
    data["profiles"][target].append(macro)
    _write(data)
    return macro


def remove(target: str, macro_id: str) -> bool:
    target = _validate_target(target)
    data = load()
    macros = data["profiles"][target]
    before = len(macros)
    data["profiles"][target] = [m for m in macros if m["id"] != macro_id]
    if len(data["profiles"][target]) == before:
        return False
    _write(data)
    return True
