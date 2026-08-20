"""Persistence for the user-configurable macro list (FR11).

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
DEFAULT_MACROS = ["/model", "/context", "/cost", "/vis"]
MAX_MACRO_TEXT_BYTES = 2048


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _seed() -> dict:
    data = {"macros": [{"id": _new_id(), "text": text} for text in DEFAULT_MACROS]}
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


def load() -> dict:
    if not MACROS_PATH.exists():
        return _seed()
    with open(MACROS_PATH, "r") as f:
        return json.load(f)


def add(text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("macro text must not be empty")
    if len(text.encode("utf-8")) > MAX_MACRO_TEXT_BYTES:
        raise ValueError("macro text too long")

    data = load()
    macro = {"id": _new_id(), "text": text}
    data["macros"].append(macro)
    _write(data)
    return macro


def remove(macro_id: str) -> bool:
    data = load()
    before = len(data["macros"])
    data["macros"] = [m for m in data["macros"] if m["id"] != macro_id]
    if len(data["macros"]) == before:
        return False
    _write(data)
    return True
