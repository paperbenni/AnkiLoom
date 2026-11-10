"""Debounced polling with the same journaled sync operation as one-shot sync."""

import hashlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

from filelock import Timeout

from .cards import visible_files
from .configuration import config
from .errors import LoomError, operation_error
from .service import SyncOptions, sync_once


def tree_snapshot(options: SyncOptions) -> dict[Path, str]:
    root = options.root
    try:
        _, excludes, _ = config(root, options.deck, options.exclude, options.url)
        paths = list(visible_files(root, excludes))
    except LoomError:
        # A partially edited config must not prevent detection of its next save.
        paths = list(visible_files(root, options.exclude))
    settings = root / "ankiloom.toml"
    if settings.is_file() and settings not in paths:
        paths.append(settings)
    snapshot = {}
    for path in paths:
        if path.is_symlink():
            # Track the link, without reading content outside the root.
            snapshot[path] = "symlink:" + str(path.readlink())
            continue
        try:
            with path.open("rb") as stream:
                snapshot[path] = hashlib.file_digest(stream, "sha256").hexdigest()
        except FileNotFoundError:
            # Editors commonly replace a file between directory listing and open.
            continue
    return snapshot


def watch_folder(
    options: SyncOptions,
    on_event: Callable[[dict], None],
    *,
    interval: float = 1.0,
    debounce: float = 0.5,
    retry_delay: float = 10.0,
) -> None:
    root = options.root.resolve()
    if not root.is_dir():
        raise LoomError(f"Card root is not a directory: {root}", "input")
    if options.prune or options.force or options.adopt:
        raise LoomError("Use one-shot sync for adoption, forced overwrites or pruning.", "input")
    options = replace(options, root=root)
    baseline = tree_snapshot(options)
    pending = None
    changed_at = 0.0
    retry_at = None
    trigger = "initial"
    on_event({"ok": True, "event": "watching", "root": str(root)})
    try:
        while True:
            if trigger:
                observed = tree_snapshot(options)
                try:
                    result = sync_once(options)
                except (LoomError, OSError, Timeout) as exc:
                    error = operation_error(exc)
                    recoverable = error.code == "connection" or isinstance(exc, Timeout)
                    retry_at = monotonic() + retry_delay if recoverable else None
                    baseline = observed
                    on_event(
                        {
                            "ok": False,
                            "event": "error",
                            "trigger": trigger,
                            "retryIn": retry_delay if recoverable else None,
                            "error": {"code": error.code, "message": str(error)},
                        }
                    )
                else:
                    baseline = observed
                    # Ignore precisely the sources produced by our sync. Do not take a
                    # fresh tree snapshot: that would swallow edits made during sync.
                    baseline.update(
                        {
                            path: hashlib.sha256(source.encode("utf-8")).hexdigest()
                            for path, source in result.sources.items()
                        }
                    )
                    retry_at = None
                    on_event({**result.report, "event": "sync", "trigger": trigger})
                trigger = ""
                pending = None
            sleep(interval)
            current = tree_snapshot(options)
            now = monotonic()
            if current != baseline:
                if current != pending:
                    pending, changed_at = current, now
                if now - changed_at >= debounce:
                    trigger = "change"
            else:
                pending = None
            if not trigger and pending is None and retry_at is not None and now >= retry_at:
                trigger = "retry"
    except KeyboardInterrupt:
        on_event({"ok": True, "event": "stopped", "root": str(root)})
