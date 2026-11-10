"""Shared collection settings and AnkiConnect construction."""

import os
import tomllib

from .anki import AnkiConnect
from .errors import LoomError


def config(root, deck, exclude, url=None):
    path = root / "ankiloom.toml"
    values = {}
    if path.exists():
        try:
            values = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise LoomError(f"Invalid {path}: {exc}", "config") from exc
        unknown = set(values) - {"deck", "exclude", "url"}
        if unknown:
            raise LoomError(f"Unknown settings in {path}: {', '.join(sorted(unknown))}", "config")
        if any(not isinstance(values[k], str) for k in ("deck", "url") if k in values):
            raise LoomError(f"deck and url in {path} must be strings.", "config")
        if "exclude" in values and (
            not isinstance(values["exclude"], list)
            or any(not isinstance(p, str) for p in values["exclude"])
        ):
            raise LoomError(f"exclude in {path} must be an array of glob strings.", "config")
    return (
        deck if deck is not None else values.get("deck", ""),
        tuple(values.get("exclude", [])) + exclude,
        url or values.get("url", "http://127.0.0.1:8765"),
    )


def client_for(url, timeout):
    return AnkiConnect(url or "http://127.0.0.1:8765", os.environ.get("ANKICONNECT_KEY"), timeout)
