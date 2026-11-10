"""Atomic metadata updates and local sync journal."""

import json
import os
import re
import tempfile
from pathlib import Path

from .cards import frontmatter
from .errors import LoomError

STATE_VERSION = 2


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        if path.exists() and hasattr(os, "fchmod"):
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


def metadata_source(card, *, remove=(), **values):
    if card.section is not None:
        from .multi import metadata_source as multi_metadata_source

        if remove or set(values) != {"noteId"}:
            raise LoomError("Multi-card metadata supports only noteId.", "parse")
        return multi_metadata_source(card, values["noteId"])
    current = card.source
    _, _, end = frontmatter(current)
    newline = "\r\n" if "\r\n" in current else "\n"
    lines = current.splitlines(keepends=True)
    if end:
        head = "".join(lines[: end - 1])
        tail = "".join(lines[end - 1 :])
    else:
        head, tail = "---" + newline, "---" + newline + newline + current
    for key in remove:
        pattern = re.compile(rf"^{re.escape(key)}:")
        filtered = [line for line in head.splitlines(keepends=True) if not pattern.match(line)]
        if len(filtered) == len(head.splitlines(keepends=True)) and key in card.meta:
            # Indented/flow YAML identity keys cannot be safely edited in place.
            raise LoomError(
                f"{card.path}: remove {key} from its own unindented YAML line.", "parse"
            )
        head = "".join(filtered)
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
    try:
        updated, _, _ = frontmatter(source)
    except LoomError as exc:
        raise LoomError(
            "Cannot update sync IDs in this frontmatter. Use block-style YAML with each key on its own line.",
            "parse",
        ) from exc
    if any(updated.get(key) != value for key, value in values.items()):
        raise LoomError(
            "Cannot update sync IDs in this frontmatter; use simple block-style YAML keys.",
            "parse",
        )
    if any(key in updated for key in remove):
        raise LoomError(
            "Cannot remove legacy sync IDs from this frontmatter; use simple block-style YAML keys.",
            "parse",
        )
    return source


def write_metadata(card, *, remove=(), **values):
    # Preserve comments, formatting, unknown frontmatter and the exact card body.
    if card.path.read_bytes().decode("utf-8") != card.source:
        raise LoomError(
            f"{card.path}: file changed during sync; rerun with the latest content.", "conflict"
        )
    source = metadata_source(card, remove=remove, **values)
    atomic_write(card.path, source)
    card.source = source
    for key in remove:
        card.meta.pop(key, None)
    card.meta.update(values)


def _validate_snapshot(snap):
    if not isinstance(snap, dict):
        raise TypeError("invalid note snapshot")
    if not isinstance(snap["fields"], dict) or not isinstance(snap["model"], str):
        raise TypeError("invalid note snapshot")
    if any(not isinstance(snap[k], list) for k in ("tags", "decks", "cards")):
        raise ValueError("invalid note snapshot lists")


def _validate_notes(data, *, legacy=False):
    notes = data["notes"]
    if not isinstance(notes, dict):
        raise TypeError("invalid note records")
    for note_id, record in notes.items():
        if not note_id.isdecimal() or not isinstance(record, dict):
            raise ValueError("invalid note record")
        _validate_snapshot(record["snapshot"])
        if not isinstance(record["sourceTags"], list):
            raise TypeError("invalid source tags")
        if legacy:
            if not isinstance(record["loomId"], str):
                raise TypeError("invalid identity")
        elif "loomId" in record and not isinstance(record["loomId"], str):
            raise TypeError("invalid legacy identity")
        if "pending" in record:
            _validate_snapshot(record["pending"])


def _validate_creations(data):
    creations = data["pendingCreations"]
    if not isinstance(creations, dict):
        raise TypeError("invalid pending creations")
    for token, record in creations.items():
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
            raise ValueError("invalid creation token")
        if not isinstance(record, dict):
            raise TypeError("invalid creation record")
        if not isinstance(record.get("path"), str) or not record["path"]:
            raise TypeError("invalid creation path")
        if not isinstance(record.get("fingerprint"), str) or not record["fingerprint"]:
            raise TypeError("invalid creation fingerprint")
        if "noteId" in record and (type(record["noteId"]) is not int or record["noteId"] <= 0):
            raise ValueError("invalid creation note ID")
        if "section" in record and (type(record["section"]) is not int or record["section"] < 0):
            raise ValueError("invalid creation section")


class State:
    def __init__(self, root: Path, endpoint: str):
        self.path = root / ".ankiloom" / "state.json"
        self.migrated = False
        self.data = {
            "version": STATE_VERSION,
            "endpoint": endpoint,
            "notes": {},
            "pendingCreations": {},
        }
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text())
                if not isinstance(loaded, dict):
                    raise TypeError("unknown state schema")
                version = loaded.get("version")
                if version == 1:
                    _validate_notes(loaded, legacy=True)
                    loaded["version"] = STATE_VERSION
                    loaded.setdefault("pendingCreations", {})
                    self.migrated = True
                elif version != STATE_VERSION:
                    raise ValueError("unknown state schema")
                _validate_notes(loaded)
                _validate_creations(loaded)
                if loaded["endpoint"] != endpoint:
                    raise LoomError(
                        "This root was synced to another AnkiConnect URL. Use the original --url, or a separate root and Anki profile.",
                        "config",
                    )
                self.data = loaded
            except (ValueError, KeyError, TypeError) as exc:
                raise LoomError(
                    f"Invalid sync journal {self.path}; restore it from a backup: {exc}", "state"
                ) from exc

    @property
    def notes(self):
        return self.data["notes"]

    @property
    def pending_creations(self):
        return self.data["pendingCreations"]

    def save(self):
        self.data["version"] = STATE_VERSION
        atomic_write(self.path, json.dumps(self.data, indent=2, sort_keys=True) + "\n")
        self.migrated = False
