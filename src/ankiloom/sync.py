"""Preflight the entire input, then journal and apply each note independently."""

import base64
import uuid
from dataclasses import dataclass
from pathlib import Path

from .cards import MODELS, YANKI_MODELS, Card
from .errors import LoomError, PreflightError
from .progress import ProgressCallback, ProgressUpdate, no_progress
from .storage import metadata_source, write_metadata

MANAGED = "ankiloom::managed"
CSS = """.card {font-family: system-ui, sans-serif; font-size: 20px; text-align: left;}
.ankiloom {max-width: 65ch; margin: auto; padding: 0 1rem;}
img, video {max-width: 100%; height: auto;}
table {border-collapse: collapse;} th, td {border: 1px solid gray; padding: .3rem .7rem;}
pre {overflow-x: auto;}"""


def templates(kind):
    if kind == "cloze":
        return [
            {"Name": "Cloze", "Front": "{{cloze:Front}}", "Back": "{{cloze:Front}}<br>{{Back}}"}
        ]
    if kind == "type":
        return [
            {
                "Name": "Type Answer",
                "Front": "{{Front}}<br>{{type:Back}}",
                "Back": "{{Front}}<hr>{{type:Back}}",
            }
        ]
    result = [
        {"Name": "Forward", "Front": "{{Front}}", "Back": "{{FrontSide}}<hr id=answer>{{Back}}"}
    ]
    if kind == "reverse":
        result[0]["Back"] += "<hr>{{Extra}}"
        result.append(
            {
                "Name": "Reverse",
                "Front": "{{Back}}",
                "Back": "{{FrontSide}}<hr id=answer>{{Front}}<hr>{{Extra}}",
            }
        )
    return result


def snapshot(note):
    return {key: note[key] for key in ("model", "fields", "tags", "decks", "cards")}


def compatible_partial(remote, before, target):
    """Accept only an interrupted write's old/new values, including deck/tag steps."""
    if remote["model"] != before["model"]:
        return False
    if remote["cards"] != before["cards"] and not (
        remote["model"] in (MODELS["cloze"], YANKI_MODELS["cloze"])
        and set(before["cards"]).issubset(remote["cards"])
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


@dataclass
class Entry:
    card: Card
    action: str
    remote: dict | None
    target: dict
    loom_id: str

    def report(self, root: Path):
        return {
            "path": str(self.card.path.relative_to(root)),
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
                set(self.target["tags"]) - set(self.remote["tags"] if self.remote else [])
            ),
            "tagsRemoved": sorted(
                set(self.remote["tags"] if self.remote else []) - set(self.target["tags"])
            ),
        }


def plan(
    cards,
    client,
    state,
    adopt=False,
    force=False,
    prune=False,
    *,
    progress: ProgressCallback = no_progress,
):
    progress(ProgressUpdate("Connecting to Anki"))
    client.connect()
    progress(ProgressUpdate("Looking up note identities", total=len(cards)))
    identities = ["ankiloom::id::" + c.meta["loomId"] for c in cards if c.meta.get("loomId")]
    identity_matches = client.find_identities(identities)
    note_ids = {c.note_id for c in cards if c.note_id}
    note_ids.update(note_id for matches in identity_matches.values() for note_id in matches)
    progress(ProgressUpdate("Reading Anki notes", total=len(note_ids)))
    remote_notes = client.notes(list(note_ids))
    progress(ProgressUpdate("Reading Anki notes", len(note_ids), len(note_ids)))
    entries, problems, used = [], [], set()
    for index, card in enumerate(cards):
        progress(ProgressUpdate("Checking notes", index, len(cards), card.path.name))
        try:
            loom_id = card.meta.get("loomId") or uuid.uuid4().hex
            metadata_source(card, loomId=loom_id, noteId=card.note_id or 1)
            identity = "ankiloom::id::" + loom_id
            matches = identity_matches.get(identity, [])
            if len(matches) > 1:
                raise LoomError(
                    f"Multiple Anki notes have identity {loom_id}; resolve the duplicates in Anki.",
                    "conflict",
                )
            note_id = card.note_id or (matches[0] if matches else None)
            if card.note_id and matches and matches != [card.note_id]:
                raise LoomError("noteId and loomId point at different Anki notes.", "conflict")
            if note_id in used:
                raise LoomError(f"Another file resolves to Anki note {note_id}.", "duplicate")
            if note_id:
                used.add(note_id)
            remote = client.require_note(remote_notes, note_id) if note_id else None
            baseline = state.notes.get(str(note_id)) if note_id else None
            if remote:
                if remote["model"] not in (MODELS[card.kind], YANKI_MODELS[card.kind]):
                    raise LoomError(
                        f"Note type is {remote['model']!r}, but Markdown requires {card.kind}. Type changes would risk review history; migrate the model in Anki first.",
                        "model",
                    )
                if not set(card.fields).issubset(remote["fields"]):
                    raise LoomError("The existing note model is missing required fields.", "model")
                if not baseline and not adopt and identity not in remote["tags"]:
                    raise LoomError(
                        "Existing note needs explicit adoption. Preview with sync --adopt --dry-run, then sync --adopt to retain its ID and review history.",
                        "adoption",
                    )
                if baseline and baseline.get("loomId") != loom_id:
                    raise LoomError(
                        "Sync identity differs from the local journal; restore the file's loomId.",
                        "conflict",
                    )
                current = snapshot(remote)
                if baseline and not force and current != baseline["snapshot"]:
                    pending = baseline.get("pending")
                    if not pending or not compatible_partial(
                        current, baseline["snapshot"], pending
                    ):
                        raise LoomError(
                            "Anki changed since the last sync. Copy wanted edits into Markdown, then use --force to explicitly overwrite Anki's version.",
                            "conflict",
                        )
                fields = {**remote["fields"], **card.fields}
                old_tags = set(baseline.get("sourceTags", [])) if baseline else set()
                tags = (set(remote["tags"]) - old_tags) | set(card.tags) | {MANAGED, identity}
                # Don't allow a second sync identity on an adopted note.
                if any(t.startswith("ankiloom::id::") and t != identity for t in tags):
                    raise LoomError("This Anki note already belongs to another loomId.", "conflict")
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
                target = {
                    "model": MODELS[card.kind],
                    "fields": card.fields,
                    "tags": sorted(set(card.tags) | {MANAGED, identity}),
                    "decks": [card.deck],
                    "cards": [],
                }
                action = "create"
            entries.append(Entry(card, action, remote, target, loom_id))
        except LoomError as exc:
            if exc.code in {"connection", "anki"}:
                raise
            problems.append({"path": str(card.path), "message": str(exc), "code": exc.code})
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
    return entries, removed


def ensure_model(client, kind, available):
    name = MODELS[kind]
    fields = ["Front", "Back"] + (["Extra"] if kind == "reverse" else [])
    if name in available:
        actual = client.call("modelFieldNames", modelName=name)
        if actual != fields:
            raise LoomError(
                f"Model {name} has unexpected fields: {actual}; expected {fields}.", "model"
            )
    else:
        client.call(
            "createModel",
            modelName=name,
            inOrderFields=fields,
            css=CSS,
            isCloze=kind == "cloze",
            cardTemplates=templates(kind),
        )
        available.append(name)


def apply(entries, removed, client, state, *, progress: ProgressCallback = no_progress):
    progress(ProgressUpdate("Applying changes", total=len(entries) + len(removed)))
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
            raise LoomError(f"{card.path}: edited during sync; rerun.", "conflict")
        # A no-op needs no second collection read. Recheck before every write,
        # including recovery of a missing numeric ID in the source file.
        needs_write = entry.action != "unchanged" or card.note_id != remote["id"]
        if needs_write and remote and snapshot(client.note(remote["id"])) != snapshot(remote):
            raise LoomError(f"Anki note {remote['id']} changed during sync; rerun.", "conflict")
        if entry.action == "unchanged":
            if card.note_id != remote["id"]:
                write_metadata(card, noteId=remote["id"])
            continue
        if not card.meta.get("loomId"):
            write_metadata(card, loomId=entry.loom_id)
        if remote:
            note_id = remote["id"]
            previous = state.notes.get(str(note_id), {})
            state.notes[str(note_id)] = {
                "loomId": entry.loom_id,
                "snapshot": snapshot(remote),
                "pending": target,
                "sourceTags": previous.get("sourceTags", []),
            }
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
                    "tags": target["tags"],
                    "options": {"allowDuplicate": True},
                },
            )
            if type(note_id) is not int or note_id <= 0:
                raise LoomError(
                    "AnkiConnect did not return a new note ID; rerun to recover by loomId.", "anki"
                )
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
        if card.note_id != note_id:
            write_metadata(card, noteId=note_id)
        actual = client.note(note_id)
        expected = {**target, "cards": actual["cards"]}
        if snapshot(actual) != expected:
            raise LoomError(
                f"Anki note {note_id} does not match the applied changes. Close its editor and rerun; the journal was retained.",
                "conflict",
            )
        state.notes[str(note_id)] = {
            "loomId": entry.loom_id,
            "snapshot": snapshot(actual),
            "sourceTags": card.tags,
        }
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

    progress(
        ProgressUpdate("Sync complete", len(entries) + len(removed), len(entries) + len(removed))
    )
