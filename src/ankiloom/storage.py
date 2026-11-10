"""Atomic metadata updates and local sync journal."""

import json
import os
import re
import tempfile
from pathlib import Path

from .cards import frontmatter
from .errors import LoomError


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        if path.exists():
            os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_metadata(card, **values):
    # Preserve comments, formatting, unknown frontmatter and the exact card body.
    current = card.path.read_bytes().decode("utf-8")
    if current != card.source:
        raise LoomError(
            f"{card.path}: file changed during sync; rerun with the latest content.", "conflict"
        )
    _, _, end = frontmatter(current)
    newline = "\r\n" if "\r\n" in current else "\n"
    lines = current.splitlines(keepends=True)
    if end:
        head = "".join(lines[: end - 1])
        tail = "".join(lines[end - 1 :])
    else:
        head, tail = "---" + newline, "---" + newline + newline + current
    for key, value in values.items():
        pattern = rf"(?m)^{key}:.*$"
        if re.search(pattern, head):
            head = re.sub(pattern, f"{key}: {value}" + ("\r" if newline == "\r\n" else ""), head)
        else:
            # Indented/flow YAML identity keys cannot be safely edited in place.
            if key in card.meta:
                raise LoomError(
                    f"{card.path}: write {key} on its own unindented YAML line.", "parse"
                )
            head += f"{key}: {value}" + newline
    source = head + tail
    atomic_write(card.path, source)
    card.source = source
    card.meta.update(values)


class State:
    def __init__(self, root: Path, endpoint: str):
        self.path = root / ".ankiloom" / "state.json"
        self.data = {"version": 1, "endpoint": endpoint, "notes": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
                if self.data["version"] != 1 or not isinstance(self.data["notes"], dict):
                    raise ValueError("unknown state schema")
                if self.data["endpoint"] != endpoint:
                    raise LoomError(
                        "This root was synced to another AnkiConnect URL. Use the original --url, or a separate root and Anki profile.",
                        "config",
                    )
            except (ValueError, KeyError, TypeError) as exc:
                raise LoomError(
                    f"Invalid sync journal {self.path}; restore it from a backup: {exc}", "state"
                ) from exc

    @property
    def notes(self):
        return self.data["notes"]

    def save(self):
        atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True) + "\n")
