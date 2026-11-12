"""Preflight the entire input, then journal and apply each note independently."""

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from .cards import MODELS, Card
from .errors import LoomError, PreflightError
from .models import ensure_model
from .progress import ProgressCallback, ProgressUpdate, no_progress
from .storage import metadata_source, write_metadata

MANAGED = "ankiloom::managed"
IDENTITY_PREFIX = "ankiloom::id::"
CREATION_PREFIX = "ankiloom::create::"


def snapshot(note):
    return {key: note[key] for key in ("model", "fields", "tags", "decks", "cards")}


def compatible_partial(remote, before, target):
    """Accept only an interrupted write's old/new values, including deck/tag steps."""
    if remote["model"] != before["model"]:
        return False
    if remote["cards"] != before["cards"] and not (
        remote["model"] == MODELS["cloze"] and set(before["cards"]).issubset(remote["cards"])
    ):
        return False
    for key, value in remote["fields"].items():
        if value not in (before["fields"].get(key), target["fields"].get(key)):
            return False
    for key in ("tags", "decks"):
        # Tag removal then addition is two calls; accept the intermediate set too.
        if remote[key] not in (before[key], target[key]) and (
            key != "tags" or remote[key] != sorted(set(before[key]) & set(target[key]))
        ):
            return False
    return True


def creation_tag(token: str) -> str:
    return CREATION_PREFIX + token


def internal_tag(tag: str) -> bool:
    return tag.startswith((IDENTITY_PREFIX, CREATION_PREFIX))


def creation_fingerprint(card: Card) -> str:
    """Match an interrupted creation after a rename, independent of its deck."""
    payload = {"model": MODELS[card.kind], "fields": card.fields}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def relative_path(card: Card, root: Path) -> str:
    return card.path.relative_to(root).as_posix()


def pending_assignments(cards, pending, root):
    """Associate interrupted creations by noteId, source location, then content."""
    assignments = {}
    used = set()
    by_note = {}
    for token, record in pending.items():
        note_id = record.get("noteId")
        if note_id is not None:
            by_note.setdefault(note_id, []).append(token)
    for card in cards:
        if card.key in assignments or not card.note_id:
            continue
        tokens = [token for token in by_note.get(card.note_id, []) if token not in used]
        if not tokens:
            continue
        if len(tokens) > 1:
            raise LoomError(
                f"Multiple interrupted creations are journaled for Anki note {card.note_id}; "
                "resolve them in .ankiloom/state.json.",
                "state",
            )
        assignments[card.key] = tokens[0]
        used.add(tokens[0])
    by_path = {}
    for token, record in pending.items():
        by_path.setdefault((record["path"], record.get("section")), []).append(token)
    for card in cards:
        if card.key in assignments:
            continue
        tokens = [
            token
            for token in by_path.get((relative_path(card, root), card.section), [])
            if token not in used
            and (
                card.section is None or pending[token]["fingerprint"] == creation_fingerprint(card)
            )
        ]
        if not tokens:
            continue
        if len(tokens) > 1:
            raise LoomError(
                f"Multiple interrupted creations are journaled for {relative_path(card, root)}; "
                "resolve them in .ankiloom/state.json.",
                "state",
            )
        assignments[card.key] = tokens[0]
        used.add(tokens[0])
    unmatched_cards = [card for card in cards if card.key not in assignments and not card.note_id]
    unmatched_tokens = [token for token in pending if token not in used]
    cards_by_fingerprint = {}
    tokens_by_fingerprint = {}
    for card in unmatched_cards:
        cards_by_fingerprint.setdefault(creation_fingerprint(card), []).append(card)
    for token in unmatched_tokens:
        tokens_by_fingerprint.setdefault(pending[token]["fingerprint"], []).append(token)
    for fingerprint, matching_cards in cards_by_fingerprint.items():
        tokens = tokens_by_fingerprint.get(fingerprint, [])
        if not tokens:
            continue
        if len(matching_cards) != 1 or len(tokens) != 1:
            raise LoomError(
                "An interrupted creation matches multiple Markdown files; restore its original "
                "path or resolve .ankiloom/state.json manually.",
                "conflict",
            )
        assignments[matching_cards[0].key] = tokens[0]
        used.add(tokens[0])
    return assignments


@dataclass
class Entry:
    card: Card
    action: str
    remote: dict | None
    target: dict
    creation: str | None = None

    def report(self, root: Path):
        return {
            "path": self.card.location(root),
            "action": self.action,
            "noteId": self.remote["id"] if self.remote else None,
            "deck": self.card.deck,
            "kind": self.card.kind,
            "fieldsChanged": [
                key
                for key, value in self.card.fields.items()
                if not self.remote or self.remote["fields"].get(key) != value
            ],
            "tagsAdded": sorted(
                tag
                for tag in set(self.target["tags"])
                - set(self.remote["tags"] if self.remote else [])
                if not internal_tag(tag)
            ),
            "tagsRemoved": sorted(
                tag
                for tag in set(self.remote["tags"] if self.remote else [])
                - set(self.target["tags"])
                if not internal_tag(tag)
            ),
        }


def plan(
    cards,
    client,
    state,
    root,
    adopt=False,
    force=False,
    prune=False,
    *,
    progress: ProgressCallback = no_progress,
):
    progress(ProgressUpdate("Connecting to Anki"))
    client.connect()
    pending = state.pending_creations
    progress(ProgressUpdate("Looking up note identities", total=len(cards) + len(pending)))
    identities = [IDENTITY_PREFIX + c.meta["loomId"] for c in cards if c.meta.get("loomId")]
    identity_matches = client.find_identities(identities)
    token_matches = client.find_identities([creation_tag(token) for token in pending])
    assignments = pending_assignments(cards, pending, root)
    note_ids = {c.note_id for c in cards if c.note_id}
    note_ids.update(note_id for matches in identity_matches.values() for note_id in matches)
    note_ids.update(note_id for matches in token_matches.values() for note_id in matches)
    note_ids.update(record["noteId"] for record in pending.values() if "noteId" in record)
    progress(ProgressUpdate("Reading Anki notes", total=len(note_ids)))
    remote_notes = client.notes(list(note_ids))
    progress(ProgressUpdate("Reading Anki notes", len(note_ids), len(note_ids)))
    entries, problems, used = [], [], set()
    for index, card in enumerate(cards):
        progress(ProgressUpdate("Checking notes", index, len(cards), card.location(root)))
        try:
            path = relative_path(card, root)
            loom_id = card.meta.get("loomId")
            identity = IDENTITY_PREFIX + loom_id if loom_id else None
            matches = identity_matches.get(identity, []) if identity else []
            if len(matches) > 1:
                raise LoomError(
                    f"Multiple Anki notes have identity {loom_id}; resolve the duplicates in Anki.",
                    "conflict",
                )
            token = assignments.get(card.key)
            pending_record = pending.get(token) if token else None
            token_notes = token_matches.get(creation_tag(token), []) if token else []
            if len(token_notes) > 1:
                raise LoomError(
                    f"Multiple Anki notes have interrupted-creation token {token}; resolve the duplicates in Anki.",
                    "conflict",
                )
            note_id = card.note_id
            if card.note_id and matches and matches != [card.note_id]:
                raise LoomError(
                    "Legacy noteId and loomId point at different Anki notes; remove the loomId to trust noteId.",
                    "conflict",
                )
            if not note_id and matches:
                note_id = matches[0]
            if pending_record:
                recorded = pending_record.get("noteId")
                found = token_notes[0] if token_notes else None
                if recorded and note_id and note_id != recorded:
                    raise LoomError(
                        f"Interrupted creation belongs to Anki note {recorded}, but Markdown has noteId {note_id}; restore the original noteId or resolve the journal manually.",
                        "conflict",
                    )
                if found and note_id and note_id != found:
                    raise LoomError(
                        f"Interrupted creation token belongs to Anki note {found}, but Markdown has noteId {note_id}; restore the original noteId or resolve the journal manually.",
                        "conflict",
                    )
                note_id = note_id or recorded or found
                pending_record["path"] = path
                if card.section is not None:
                    pending_record["section"] = card.section
                pending_record["fingerprint"] = creation_fingerprint(card)
            if (
                pending_record
                and note_id is not None
                and pending_record.get("noteId") == note_id
                and note_id not in remote_notes
            ):
                raise LoomError(
                    f"Interrupted creation journal points to Anki note {note_id}, which no longer exists. Restore it from an Anki backup, or remove the pendingCreations entry from .ankiloom/state.json to create a new note.",
                    "missing",
                )
            if note_id in used:
                raise LoomError(f"Another file resolves to Anki note {note_id}.", "duplicate")
            if note_id:
                used.add(note_id)
            remote = client.require_note(remote_notes, note_id) if note_id else None
            baseline = state.notes.get(str(note_id)) if note_id else None
            metadata_source(
                card,
                remove=("loomId",) if "loomId" in card.meta else (),
                noteId=card.note_id or 1,
            )
            if remote:
                if remote["model"] != MODELS[card.kind]:
                    raise LoomError(
                        f"Note type is {remote['model']!r}, but Markdown requires {card.kind}. Sync accepts only matching AnkiLoom models. For Yanki notes, run migrate-yanki first.",
                        "model",
                    )
                if not set(card.fields).issubset(remote["fields"]):
                    raise LoomError("The existing note model is missing required fields.", "model")
                owned = bool(
                    (pending_record and pending_record.get("noteId") == note_id)
                    or (identity and identity in remote["tags"])
                )
                if token and creation_tag(token) in remote["tags"]:
                    owned = True
                if not baseline and not adopt and not owned:
                    raise LoomError(
                        "Existing note needs explicit adoption. Preview with sync --adopt --dry-run, then sync --adopt to retain its ID and review history.",
                        "adoption",
                    )
                if (
                    baseline
                    and baseline.get("loomId")
                    and loom_id
                    and baseline["loomId"] != loom_id
                ):
                    raise LoomError(
                        "Legacy loomId differs from the local journal; restore the original loomId, or remove both IDs to create a new note.",
                        "conflict",
                    )
                current = snapshot(remote)
                if baseline and not force and current != baseline["snapshot"]:
                    pending_target = baseline.get("pending")
                    if not pending_target or not compatible_partial(
                        current, baseline["snapshot"], pending_target
                    ):
                        raise LoomError(
                            "Anki changed since the last sync. Copy wanted edits into Markdown, then use --force to explicitly overwrite Anki's version.",
                            "conflict",
                        )
                fields = {**remote["fields"], **card.fields}
                old_tags = set(baseline.get("sourceTags", [])) if baseline else set()
                tags = (set(remote["tags"]) - old_tags) | set(card.tags) | {MANAGED}
                tags = {tag for tag in tags if not internal_tag(tag)}
                target = {**current, "fields": fields, "tags": sorted(tags), "decks": [card.deck]}
                action = (
                    "adopt"
                    if not baseline
                    else (
                        "unchanged"
                        if current == target and not baseline.get("pending")
                        else "update"
                    )
                )
            else:
                token = token or uuid.uuid4().hex
                pending_record = pending.get(token)
                if pending_record is None:
                    pending_record = {
                        "path": path,
                        "fingerprint": creation_fingerprint(card),
                    }
                    pending[token] = pending_record
                else:
                    pending_record["path"] = path
                    pending_record["fingerprint"] = creation_fingerprint(card)
                target = {
                    "model": MODELS[card.kind],
                    "fields": card.fields,
                    "tags": sorted(set(card.tags) | {MANAGED}),
                    "decks": [card.deck],
                    "cards": [],
                }
                action = "create"
            if remote and not card.note_id and not token:
                # Legacy recovery must survive removal of its identity tag before
                # noteId reaches Markdown, just like an interrupted new creation.
                token = uuid.uuid4().hex
                pending[token] = {
                    "path": path,
                    "fingerprint": creation_fingerprint(card),
                    "noteId": remote["id"],
                }
            if token:
                if card.section is None:
                    pending[token].pop("section", None)
                else:
                    pending[token]["section"] = card.section
            entries.append(Entry(card, action, remote, target, token))
        except LoomError as exc:
            if exc.code in {"connection", "anki"}:
                raise
            problems.append({"path": card.location(), "message": str(exc), "code": exc.code})
    progress(ProgressUpdate("Checking notes", len(cards), len(cards)))
    new_kinds = {e.card.kind for e in entries if e.action == "create"}
    available = client.call("modelNames") if new_kinds else []
    for kind in new_kinds:
        if MODELS[kind] in available:
            expected = ["Front", "Back"] + (["Extra"] if kind == "reverse" else [])
            if client.call("modelFieldNames", modelName=MODELS[kind]) != expected:
                problems.append(
                    {
                        "path": MODELS[kind],
                        "code": "model",
                        "message": f"Model {MODELS[kind]} has incompatible fields; restore its schema in Anki.",
                    }
                )
    if problems:
        raise PreflightError(problems)
    stale_creations = []
    used_tokens = {entry.creation for entry in entries if entry.creation}
    for token, record in pending.items():
        if token in used_tokens:
            continue
        note_id = record.get("noteId")
        matches = token_matches.get(creation_tag(token), [])
        if len(matches) > 1:
            raise LoomError(
                f"Multiple Anki notes have interrupted-creation token {token}; resolve the duplicates in Anki.",
                "conflict",
            )
        found = matches[0] if matches else None
        if note_id and found and note_id != found:
            raise LoomError(
                f"Interrupted creation journal disagrees with Anki note {found}; resolve the duplicate or restore the journal.",
                "conflict",
            )
        note_id = note_id or found
        if note_id is not None and note_id in remote_notes:
            raise LoomError(
                f"Interrupted creation for {record['path']} produced Anki note {note_id}, but no Markdown file claims it. Restore the card file, or remove the note and the pendingCreations entry manually.",
                "conflict",
            )
        stale_creations.append(token)
    removed = []
    if prune:
        if not cards:
            raise LoomError(
                "Refusing to prune an empty card root. Restore the input directory first.", "input"
            )
        for note_id, record in state.notes.items():
            if int(note_id) not in used:
                if record.get("pendingDelete") and not client.call(
                    "findNotes", query=f"nid:{note_id}"
                ):
                    removed.append(
                        {
                            "id": int(note_id),
                            "decks": record["snapshot"]["decks"],
                            "alreadyDeleted": True,
                        }
                    )
                    continue
                remote = client.note(int(note_id))
                if snapshot(remote) != record["snapshot"] or MANAGED not in remote["tags"]:
                    raise LoomError(
                        f"Note {note_id} changed in Anki; refusing to prune it.", "conflict"
                    )
                removed.append(remote)
    return entries, removed, stale_creations


def apply(
    entries,
    removed,
    client,
    state,
    *,
    stale_creations=(),
    progress: ProgressCallback = no_progress,
):
    progress(ProgressUpdate("Applying changes", total=len(entries) + len(removed)))
    if stale_creations:
        for token in stale_creations:
            state.pending_creations.pop(token, None)
        state.save()
    available = client.call("modelNames") if any(e.action == "create" for e in entries) else []
    # Validate all existing destination model schemas before writing any notes.
    for kind in {e.card.kind for e in entries if e.action == "create"}:
        if MODELS[kind] in available:
            actual = client.call("modelFieldNames", modelName=MODELS[kind])
            expected = ["Front", "Back"] + (["Extra"] if kind == "reverse" else [])
            if actual != expected:
                raise LoomError(f"Model {MODELS[kind]} has unexpected fields: {actual}", "model")
    for index, entry in enumerate(entries):
        progress(
            ProgressUpdate(
                "Applying changes", index, len(entries) + len(removed), entry.card.path.name
            )
        )
        card, remote, target = entry.card, entry.remote, entry.target
        if card.path.read_bytes().decode("utf-8") != card.source:
            raise LoomError(f"{card.location()}: edited during sync; rerun.", "conflict")
        legacy = "loomId" in card.meta
        creation = entry.creation
        pending_record = None
        if creation:
            pending_record = state.pending_creations.get(creation)
            if pending_record is None:
                raise LoomError(
                    f"{card.path}: interrupted-creation journal entry disappeared during sync; rerun from a backup of .ankiloom/state.json.",
                    "state",
                )
            if remote and pending_record.get("noteId") is None:
                pending_record["noteId"] = remote["id"]
            # Persist the token, path and known noteId before mutating Anki.
            state.save()
        # A no-op needs no second collection read. Recheck before every write,
        # including recovery of a missing numeric ID in the source file.
        needs_write = entry.action != "unchanged" or card.note_id != remote["id"] or legacy
        if needs_write and remote and snapshot(client.note(remote["id"])) != snapshot(remote):
            raise LoomError(f"Anki note {remote['id']} changed during sync; rerun.", "conflict")
        if entry.action == "unchanged":
            if card.note_id != remote["id"] or legacy:
                write_metadata(
                    card,
                    remove=("loomId",) if legacy else (),
                    noteId=remote["id"],
                )
            if creation:
                state.pending_creations.pop(creation, None)
                state.save()
            continue
        if remote:
            note_id = remote["id"]
            previous = state.notes.get(str(note_id), {})
            pending_state = {
                "snapshot": snapshot(remote),
                "pending": target,
                "sourceTags": previous.get("sourceTags", []),
            }
            if previous.get("loomId"):
                pending_state["loomId"] = previous["loomId"]
            state.notes[str(note_id)] = pending_state
            state.save()
        for filename, data in card.media.items():
            client.call("storeMediaFile", filename=filename, data=base64.b64encode(data).decode())
        if not remote:
            ensure_model(client, card.kind, available)
            client.call("createDeck", deck=card.deck)
            note_id = client.call(
                "addNote",
                note={
                    "deckName": card.deck,
                    "modelName": target["model"],
                    "fields": target["fields"],
                    "tags": sorted(set(target["tags"]) | {creation_tag(creation)}),
                    "options": {"allowDuplicate": True},
                },
            )
            if type(note_id) is not int or note_id <= 0:
                raise LoomError(
                    "AnkiConnect did not return a new note ID; rerun to recover from the local journal.",
                    "anki",
                )
            assert pending_record is not None
            pending_record["noteId"] = note_id
            state.save()
        else:
            if remote["fields"] != target["fields"]:
                client.call("updateNoteFields", note={"id": note_id, "fields": card.fields})
            if remote["decks"] != target["decks"]:
                client.call("createDeck", deck=card.deck)
                client.call("changeDeck", cards=remote["cards"], deck=card.deck)
            remove = sorted(set(remote["tags"]) - set(target["tags"]))
            add = sorted(set(target["tags"]) - set(remote["tags"]))
            if remove:
                client.call("removeTags", notes=[note_id], tags=" ".join(remove))
            if add:
                client.call("addTags", notes=[note_id], tags=" ".join(add))
        if card.note_id != note_id or legacy:
            write_metadata(
                card,
                remove=("loomId",) if legacy else (),
                noteId=note_id,
            )
        if not remote and creation:
            # Keep the breadcrumb tag until noteId is safely in the Markdown.
            client.call("removeTags", notes=[note_id], tags=creation_tag(creation))
        actual = client.note(note_id)
        expected = {**target, "cards": actual["cards"]}
        if snapshot(actual) != expected:
            raise LoomError(
                f"Anki note {note_id} does not match the applied changes. Close its editor and rerun; the journal was retained.",
                "conflict",
            )
        state.notes[str(note_id)] = {
            "snapshot": snapshot(actual),
            "sourceTags": card.tags,
        }
        if creation:
            state.pending_creations.pop(creation, None)
        state.save()
    for index, remote in enumerate(removed, start=len(entries)):
        progress(ProgressUpdate("Removing missing notes", index, len(entries) + len(removed)))
        if remote.get("alreadyDeleted"):
            del state.notes[str(remote["id"])]
            state.save()
            continue
        if snapshot(client.note(remote["id"])) != snapshot(remote):
            raise LoomError(f"Anki note {remote['id']} changed before pruning; rerun.", "conflict")
        state.notes[str(remote["id"])]["pendingDelete"] = True
        state.save()
        client.call("deleteNotes", notes=[remote["id"]])
        del state.notes[str(remote["id"])]
        state.save()

    if state.migrated:
        state.save()
    progress(
        ProgressUpdate("Sync complete", len(entries) + len(removed), len(entries) + len(removed))
    )
