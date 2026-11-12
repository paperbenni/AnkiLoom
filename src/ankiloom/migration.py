"""One explicit Yanki replacement path; ordinary sync only knows native models."""

import base64
import json
import re
import uuid
from collections import Counter

from filelock import FileLock

from .cards import MODELS, scan
from .configuration import client_for, config
from .errors import LoomError, PreflightError
from .models import ensure_model, fields
from .progress import ProgressUpdate, no_progress
from .storage import State, _validate_snapshot, atomic_write, metadata_source, write_metadata
from .sync import MANAGED, internal_tag, snapshot

YANKI_MODELS = {
    "basic": "Yanki - Basic",
    "reverse": "Yanki - Basic (and reversed card with extra)",
    "cloze": "Yanki - Cloze",
    "type": "Yanki - Basic (type in the answer)",
}
RECOVERY_PREFIX = "ankiloom::migrate::"


def load_journal(path, endpoint):
    if not path.exists():
        return {"version": 1, "endpoint": endpoint, "notes": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != 1 or data["endpoint"] != endpoint:
            raise ValueError("version or AnkiConnect URL differs")
        records = data["notes"]
        if not isinstance(records, dict):
            raise TypeError("invalid note records")
        tokens, replacements = set(), set()
        for old_id, record in records.items():
            if not old_id.isdecimal() or int(old_id) <= 0:
                raise ValueError("invalid old note ID")
            _validate_snapshot(record["before"])
            _validate_snapshot(record["target"])
            if not isinstance(record["sourceTags"], list) or any(
                not isinstance(tag, str) for tag in record["sourceTags"]
            ):
                raise TypeError("invalid source tags")
            token = record["token"]
            if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
                raise ValueError("invalid recovery token")
            if token in tokens:
                raise ValueError("duplicate recovery token")
            tokens.add(token)
            if "replacementId" in record:
                new_id = record["replacementId"]
                if type(new_id) is not int or new_id <= 0 or new_id in replacements:
                    raise ValueError("invalid replacement ID")
                replacements.add(new_id)
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise LoomError(
            f"Invalid migration journal {path}; restore it from a backup: {exc}", "state"
        ) from exc


def save_journal(path, journal):
    atomic_write(path, json.dumps(journal, indent=2, sort_keys=True) + "\n")


def target_for(card, old, previous_tags):
    return {
        "model": MODELS[card.kind],
        "fields": card.fields,
        "tags": sorted(
            {tag for tag in old["tags"] if not internal_tag(tag)} - set(previous_tags)
            | set(card.tags)
            | {MANAGED}
        ),
        "decks": [card.deck],
        "cards": [],
    }


def verify_replacement(note, record):
    target = record["target"]
    tag = RECOVERY_PREFIX + record["token"]
    actual = snapshot(note)
    actual["tags"] = [value for value in actual["tags"] if value != tag]
    if not note["cards"] or actual != {**target, "cards": note["cards"]}:
        raise LoomError(
            f"Replacement note {note['id']} changed or is incomplete. Restore its content, "
            "tags and deck before rerunning migrate-yanki.",
            "conflict",
        )


def check_source(card):
    if card.path.read_bytes().decode("utf-8") != card.source:
        raise LoomError(
            f"{card.location()}: edited during migration; restore it and rerun.", "conflict"
        )


def prepare(cards, client, state, journal):
    """Resolve every old/replacement identity and validate the entire batch first."""
    records = journal["notes"]
    by_replacement = {r["replacementId"]: old for old, r in records.items() if "replacementId" in r}
    matches = client.find_identities([RECOVERY_PREFIX + r["token"] for r in records.values()])
    ids = {card.note_id for card in cards if card.note_id}
    ids.update(int(old) for old in records)
    ids.update(by_replacement)
    ids.update(note_id for found in matches.values() for note_id in found)
    remote = client.notes(list(ids))
    entries, problems, claimed = [], [], set()
    available = client.call("modelNames")
    for card in cards:
        if not card.note_id:
            continue
        try:
            old_id = by_replacement.get(card.note_id, str(card.note_id))
            record: dict | None = records.get(old_id)
            old = remote.get(int(old_id))
            if record is None:
                old = client.require_note(remote, card.note_id)
                if old["model"] == MODELS[card.kind]:
                    continue
                if old["model"] != YANKI_MODELS[card.kind]:
                    raise LoomError("Expected the matching supported Yanki note type.", "model")
                expected_fields = fields(card.kind) + ["YankiNamespace"]
                if set(old["fields"]) != set(expected_fields):
                    raise LoomError(
                        "Modified Yanki fields are unsupported; no notes were replaced.", "model"
                    )
                previous_tags = state.notes.get(old_id, {}).get("sourceTags", [])
                record = {
                    "before": snapshot(old),
                    "target": target_for(card, old, previous_tags),
                    "sourceTags": previous_tags,
                    "token": uuid.uuid4().hex,
                }
                records[old_id] = record
            if old_id in claimed:
                raise LoomError("Two Markdown notes claim the same migration.", "duplicate")
            claimed.add(old_id)
            if record["before"]["model"] != YANKI_MODELS[card.kind]:
                raise LoomError(
                    "The note kind changed during migration; restore its Markdown.", "conflict"
                )
            if target_for(card, record["before"], record["sourceTags"]) != record["target"]:
                raise LoomError(
                    "Markdown changed during migration; restore it and rerun migrate-yanki.",
                    "conflict",
                )
            metadata_source(card, noteId=1, remove=("loomId",) if "loomId" in card.meta else ())
            found = matches.get(RECOVERY_PREFIX + record["token"], [])
            if len(found) > 1:
                raise LoomError(
                    "Multiple notes have the migration recovery tag; resolve the duplicates.",
                    "conflict",
                )
            new_id = record.get("replacementId")
            if new_id and found and found != [new_id]:
                raise LoomError("Migration journal and recovery tag disagree.", "conflict")
            new_id = new_id or (found[0] if found else None)
            if new_id:
                replacement = client.require_note(remote, new_id)
                verify_replacement(replacement, record)
                record["replacementId"] = new_id
            if old:
                if snapshot(old) != record["before"]:
                    raise LoomError(
                        "The Yanki note changed during migration; restore it before retrying.",
                        "conflict",
                    )
                baseline = state.notes.get(old_id)
                if baseline and baseline["snapshot"] != snapshot(old):
                    raise LoomError(
                        "The Yanki note changed since its last sync; resolve those edits first.",
                        "conflict",
                    )
            elif not new_id:
                raise LoomError(
                    "The original Yanki note is missing and no replacement exists.", "missing"
                )
            entries.append((card, old_id, record))
        except LoomError as exc:
            if exc.code in {"connection", "anki"}:
                raise
            problems.append({"path": card.location(), "message": str(exc), "code": exc.code})
    if set(records) - claimed:
        problems.append(
            {
                "path": "migration",
                "message": "Restore Markdown claiming every unfinished migration before retrying.",
                "code": "missing",
            }
        )
    for kind in {card.kind for card, _, _ in entries}:
        if MODELS[kind] in available and client.call(
            "modelFieldNames", modelName=MODELS[kind]
        ) != fields(kind):
            problems.append(
                {
                    "path": MODELS[kind],
                    "message": "Destination model has incompatible fields.",
                    "code": "model",
                }
            )
    if problems:
        raise PreflightError(problems)
    return entries, available


def apply_replacements(entries, available, client, state, path, journal, progress):
    # Persist all old identities and creation tokens before the first Anki write.
    save_journal(path, journal)
    for index, (card, old_id, record) in enumerate(entries):
        progress(ProgressUpdate("Replacing Yanki notes", index, len(entries), card.location()))
        check_source(card)
        tag = RECOVERY_PREFIX + record["token"]
        target = record["target"]
        new_id = record.get("replacementId")
        if not new_id:
            if snapshot(client.note(int(old_id))) != record["before"]:
                raise LoomError("The Yanki note changed before replacement; rerun.", "conflict")
            ensure_model(client, card.kind, available)
            client.call("createDeck", deck=card.deck)
            for filename, data in card.media.items():
                client.call(
                    "storeMediaFile", filename=filename, data=base64.b64encode(data).decode()
                )
            new_id = client.call(
                "addNote",
                note={
                    "deckName": card.deck,
                    "modelName": target["model"],
                    "fields": target["fields"],
                    "tags": sorted([*target["tags"], tag]),
                    "options": {"allowDuplicate": True},
                },
            )
            if type(new_id) is not int or new_id <= 0:
                raise LoomError(
                    "No replacement ID returned; rerun migrate-yanki to recover.", "anki"
                )
            record["replacementId"] = new_id
            save_journal(path, journal)
        verify_replacement(client.note(new_id), record)
        check_source(card)
        write_metadata(card, noteId=new_id, remove=("loomId",) if "loomId" in card.meta else ())
        old = client.notes([int(old_id)]).get(int(old_id))
        if old:
            if snapshot(old) != record["before"]:
                raise LoomError(
                    "The Yanki note changed before deletion; restore it and rerun migrate-yanki.",
                    "conflict",
                )
            verify_replacement(client.note(new_id), record)
            check_source(card)
            client.call("deleteNotes", notes=[int(old_id)])
        # Keep recovery breadcrumbs until both Markdown and the sync journal are safe.
        state.notes.pop(old_id, None)
        client.call("removeTags", notes=[new_id], tags=tag)
        actual = client.note(new_id)
        verify_replacement(actual, record)
        state.notes[str(new_id)] = {"snapshot": snapshot(actual), "sourceTags": card.tags}
        state.save()
        del journal["notes"][old_id]
        save_journal(path, journal)
    path.unlink(missing_ok=True)


def migrate_yanki(root, deck, exclude, url, timeout, dry_run, *, progress=no_progress):
    root = root.resolve()
    deck, exclude, url = config(root, deck, exclude, url)
    client = client_for(url, timeout)

    def run():
        cards = scan(root, deck, exclude, progress=progress)
        state = State(root, url)
        path = root / ".ankiloom" / "yanki-migration.json"
        journal = load_journal(path, url)
        progress(ProgressUpdate("Connecting to Anki"))
        client.connect()
        entries, available = prepare(cards, client, state, journal)
        changes = [
            {
                "path": card.location(root),
                "action": "replace",
                "noteId": int(old_id),
                "replacementId": record.get("replacementId"),
                "deck": card.deck,
                "kind": card.kind,
            }
            for card, old_id, record in entries
        ]
        if not dry_run and entries:
            apply_replacements(entries, available, client, state, path, journal, progress)
            for change, (card, _, _) in zip(changes, entries):
                change["replacementId"] = card.note_id
        elif not dry_run and path.exists():
            path.unlink()
        return {
            "ok": True,
            "dryRun": dry_run,
            "resetsHistory": True,
            "changes": changes,
            "summary": dict(Counter(change["action"] for change in changes)),
        }

    if dry_run:
        return run()
    if not root.is_dir():
        raise LoomError(f"Card root is not a directory: {root}", "input")
    directory = root / ".ankiloom"
    directory.mkdir(exist_ok=True)
    with FileLock(directory / "sync.lock", timeout=0):
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        return run()
