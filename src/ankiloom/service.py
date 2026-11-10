"""One journaled sync operation shared by the CLI and folder watcher."""

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock

from .cards import scan
from .configuration import client_for, config
from .errors import LoomError
from .progress import ProgressCallback, ProgressUpdate, no_progress
from .storage import State
from .sync import apply, plan


@dataclass(frozen=True)
class SyncOptions:
    root: Path
    deck: str | None = None
    exclude: tuple[str, ...] = ()
    url: str | None = None
    timeout: float = 15.0
    dry_run: bool = False
    adopt: bool = False
    force: bool = False
    prune: bool = False
    ankiweb: bool = False


@dataclass
class SyncResult:
    report: dict
    sources: dict[Path, str]


def sync_once(options: SyncOptions, *, progress: ProgressCallback = no_progress) -> SyncResult:
    progress(ProgressUpdate("Reading settings"))
    root = options.root.resolve()
    deck, exclude, url = config(root, options.deck, options.exclude, options.url)
    client = client_for(url, options.timeout)

    def run() -> SyncResult:
        cards = scan(root, deck, exclude, progress=progress)
        state = State(root, url)
        entries, removed, stale_creations = plan(
            cards,
            client,
            state,
            root,
            options.adopt,
            options.force,
            options.prune,
            progress=progress,
        )
        changes = [entry.report(root) for entry in entries]
        changes += [
            {
                "path": f"noteId:{r['id']}",
                "action": "delete",
                "noteId": r["id"],
                "deck": ", ".join(r["decks"]),
            }
            for r in removed
        ]
        if not options.dry_run:
            apply(
                entries,
                removed,
                client,
                state,
                stale_creations=stale_creations,
                progress=progress,
            )
            for change, entry in zip(changes, entries):
                change["noteId"] = entry.card.note_id
                change["path"] = entry.card.location(root)
            if options.ankiweb:
                progress(ProgressUpdate("Syncing AnkiWeb"))
                client.call("sync")
        return SyncResult(
            report={
                "ok": True,
                "dryRun": options.dry_run,
                "changes": changes,
                "summary": dict(sorted(Counter(c["action"] for c in changes).items())),
            },
            sources={card.path: card.source for card in cards},
        )

    if options.dry_run:
        return run()
    if not root.is_dir():
        raise LoomError(f"Card root is not a directory: {root}", "input")
    directory = root / ".ankiloom"
    directory.mkdir(exist_ok=True)
    ignore = directory / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    with FileLock(directory / "sync.lock", timeout=0):
        return run()
