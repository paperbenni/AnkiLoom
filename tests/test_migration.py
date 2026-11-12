"""Explicit recreation is the only Yanki path; retries must never duplicate it."""

import json
from copy import deepcopy

import pytest
from click.testing import CliRunner
from filelock import FileLock

from ankiloom.anki import AnkiConnect
from ankiloom.cli import cli
from ankiloom.migration import RECOVERY_PREFIX, YANKI_MODELS
from ankiloom.models import CSS, fields
from ankiloom.storage import State
from ankiloom.sync import snapshot

SOURCES = {
    "basic": "Question\n\n---\n\nAnswer",
    "reverse": "Question\n\n---\n\n---\n\nAnswer\n\n---\n\nExtra",
    "cloze": "~~Paris~~ is in ~~France~~.",
    "type": "Capital?\n\n_Paris_",
}


def old_note(collection, root, kind="basic", name="card.md"):
    note_id = collection.note(
        model=YANKI_MODELS[kind],
        fields={**dict.fromkeys(fields(kind), "old"), "YankiNamespace": "Yanki"},
    )
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nnoteId: {note_id}\ntags: [topic]\n---\n\n" + SOURCES[kind])
    return note_id, path


def migrate(server, root, *args):
    return CliRunner().invoke(
        cli, ["migrate-yanki", str(root), "--url", server[1], "--json", *args]
    )


def sync(server, root, *args):
    return CliRunner().invoke(cli, ["sync", str(root), "--url", server[1], "--json", *args])


@pytest.mark.parametrize("kind", SOURCES)
def test_recreation_then_ordinary_sync(server, tmp_path, kind):
    collection, _ = server
    old_id, path = old_note(collection, tmp_path, kind, "course/card.md")
    unreferenced = collection.note(model=YANKI_MODELS["basic"])
    before = deepcopy(collection.notes[unreferenced])
    assert sync(server, tmp_path, "--adopt").exit_code == 3
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["resetsHistory"] and payload["summary"] == {"replace": 1}
    new_id = payload["changes"][0]["replacementId"]
    assert new_id != old_id and old_id not in collection.notes
    assert f"noteId: {new_id}" in path.read_text()
    note = collection.notes[new_id]
    assert note["reviews"] == 0
    assert note["modelName"].startswith("AnkiLoom - ")
    assert set(note["fields"]) == set(fields(kind))
    assert set(note["tags"]) == {"personal", "topic", "ankiloom::managed"}
    assert note["deck"] == "course"
    assert all('class="ankiloom"' in value for value in note["fields"].values())
    assert all("yanki" not in value for value in note["fields"].values())
    assert collection.notes[unreferenced] == before
    assert collection.models[note["modelName"]]["css"] == CSS
    assert not (tmp_path / ".ankiloom" / "yanki-migration.json").exists()
    collection.calls.clear()
    result = sync(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["summary"] == {"unchanged": 1}
    assert "addNote" not in collection.calls and "deleteNotes" not in collection.calls
    assert migrate(server, tmp_path, "--reset-history").exit_code == 0
    assert "addNote" not in collection.calls


def test_requires_explicit_history_reset(server, tmp_path):
    old_note(server[0], tmp_path)
    result = migrate(server, tmp_path)
    assert result.exit_code == 2 and "--reset-history" in result.output
    assert not server[0].calls and not (tmp_path / ".ankiloom").exists()


def snapshot_files(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_dry_run_changes_nothing(server, tmp_path):
    collection, _ = server
    old_note(collection, tmp_path)
    notes = deepcopy(collection.notes)
    files = snapshot_files(tmp_path)
    result = migrate(server, tmp_path, "--dry-run")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["summary"] == {"replace": 1}
    assert collection.notes == notes and snapshot_files(tmp_path) == files
    assert not (tmp_path / ".ankiloom").exists()
    assert not {"addNote", "deleteNotes", "createModel"} & set(collection.calls)


@pytest.mark.parametrize(
    "action",
    ["createModel", "createDeck", "storeMediaFile", "addNote", "deleteNotes", "removeTags"],
)
def test_lost_response_recovers_without_duplicate(server, tmp_path, action):
    collection, _ = server
    old_id, path = old_note(collection, tmp_path)
    path.write_text(path.read_text() + "\n\n![image](image.png)")
    (tmp_path / "image.png").write_bytes(b"image")
    collection.fail_after = action
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 4, result.output
    files, notes = snapshot_files(tmp_path), deepcopy(collection.notes)
    preview = migrate(server, tmp_path, "--dry-run")
    assert preview.exit_code == 0, preview.output
    assert snapshot_files(tmp_path) == files and collection.notes == notes
    created = {i for i in collection.notes if i != old_id}
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and old_id not in collection.notes
    assert created <= set(collection.notes)
    assert sum(c == "addNote" for c in collection.calls) == 1
    assert not any(
        t.startswith(RECOVERY_PREFIX) for n in collection.notes.values() for t in n["tags"]
    )
    assert sync(server, tmp_path).exit_code == 0


def test_metadata_failure_keeps_original_and_recovers_after_rename(monkeypatch, server, tmp_path):
    from ankiloom import migration

    collection, _ = server
    old_id, path = old_note(collection, tmp_path)
    original = migration.write_metadata

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(migration, "write_metadata", fail)
    assert migrate(server, tmp_path, "--reset-history").exit_code == 2
    assert old_id in collection.notes and len(collection.notes) == 2
    assert f"noteId: {old_id}" in path.read_text()
    path.rename(tmp_path / "renamed.md")
    monkeypatch.setattr(migration, "write_metadata", original)
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and old_id not in collection.notes
    assert sum(c == "addNote" for c in collection.calls) == 1


@pytest.mark.parametrize("problem", ["missing", "schema", "kind", "metadata", "destination"])
def test_all_inputs_preflight_before_replacement(server, tmp_path, problem):
    collection, _ = server
    old_note(collection, tmp_path, name="a.md")
    old_id, path = old_note(collection, tmp_path, name="z.md")
    if problem == "missing":
        del collection.notes[old_id]
    elif problem == "schema":
        collection.notes[old_id]["fields"]["Custom"] = "precious"
    elif problem == "kind":
        path.write_text(path.read_text().replace(SOURCES["basic"], SOURCES["cloze"]))
    elif problem == "metadata":
        path.write_text(f"---\n{{noteId: {old_id}}}\n---\n\n" + SOURCES["basic"])
    else:
        collection.models["AnkiLoom - Basic"] = {"fields": ["Wrong"]}
    notes, files = deepcopy(collection.notes), snapshot_files(tmp_path)
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 3, result.output
    assert collection.notes == notes
    assert not {"addNote", "deleteNotes", "createModel"} & set(collection.calls)
    assert all(
        path.read_bytes() == content
        for name, content in files.items()
        for path in [tmp_path / name]
    )


@pytest.mark.parametrize("changed", ["source", "original", "replacement", "replacement_deleted"])
def test_interrupted_migration_refuses_changed_inputs(server, tmp_path, changed):
    collection, _ = server
    old_id, path = old_note(collection, tmp_path)
    collection.fail_after = "addNote"
    assert migrate(server, tmp_path, "--reset-history").exit_code == 4
    new_id = next(i for i in collection.notes if i != old_id)
    if changed == "source":
        path.write_text(path.read_text().replace("Answer", "Edited"))
    elif changed == "original":
        collection.notes[old_id]["fields"]["Back"] = "Edited"
    elif changed == "replacement":
        collection.notes[new_id]["fields"]["Back"] = "Edited"
    else:
        # Record a known replacement ID: a known missing note must never be recreated.
        journal_path = tmp_path / ".ankiloom" / "yanki-migration.json"
        journal = json.loads(journal_path.read_text())
        journal["notes"][str(old_id)]["replacementId"] = new_id
        journal_path.write_text(json.dumps(journal))
        del collection.notes[new_id]
    collection.calls.clear()
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 3, result.output
    assert "addNote" not in collection.calls and "deleteNotes" not in collection.calls
    assert old_id in collection.notes


def test_duplicate_recovery_tags_block_writes(server, tmp_path):
    collection, _ = server
    old_note(collection, tmp_path)
    collection.fail_after = "addNote"
    assert migrate(server, tmp_path, "--reset-history").exit_code == 4
    replacement = next(
        n for n in collection.notes.values() if n["modelName"].startswith("AnkiLoom")
    )
    collection.note(fields=replacement["fields"], tags=replacement["tags"])
    collection.calls.clear()
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 3 and "Multiple notes" in result.output
    assert "addNote" not in collection.calls and "deleteNotes" not in collection.calls


def test_migration_uses_sync_lock(server, tmp_path):
    old_note(server[0], tmp_path)
    (tmp_path / ".ankiloom").mkdir()
    with FileLock(tmp_path / ".ankiloom" / "sync.lock"):
        assert migrate(server, tmp_path, "--reset-history").exit_code == 3
    assert not server[0].calls


def test_multi_card_migration_updates_only_matching_ids(server, tmp_path):
    collection, _ = server
    ids = [
        collection.note(
            model=YANKI_MODELS["basic"],
            fields={"Front": "old", "Back": "old", "YankiNamespace": "Yanki"},
        )
        for _ in range(2)
    ]
    path = tmp_path / "multi.md"
    path.write_text(
        "---\nankiloom: multi\n---\n"
        + "\n".join(
            f"Q{i} :: A{i} <!-- ankiloom noteId: {note_id} -->" for i, note_id in enumerate(ids)
        )
    )
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    assert not set(ids) & set(collection.notes)
    assert all(f"noteId: {note_id}" in path.read_text() for note_id in collection.notes)
    assert sync(server, tmp_path).exit_code == 0


@pytest.mark.parametrize("failure", ["replacement_id", "state", "completion"])
def test_journal_save_failure_recovers_older_adopted_notes(monkeypatch, server, tmp_path, failure):
    from ankiloom import migration

    collection, url = server
    old_id, path = old_note(collection, tmp_path)
    collection.notes[old_id]["tags"].append("previous_topic")
    state = State(tmp_path, url)
    state.notes[str(old_id)] = {
        "snapshot": snapshot(AnkiConnect(url).note(old_id)),
        "sourceTags": ["previous_topic"],
    }
    state.save()
    original_journal, original_state = migration.save_journal, State.save
    calls = 0

    def journal_save(*args):
        nonlocal calls
        calls += 1
        if calls == {"replacement_id": 2, "completion": 3}.get(failure):
            raise OSError("disk full")
        original_journal(*args)

    def state_save(*args):
        raise OSError("disk full")

    monkeypatch.setattr(migration, "save_journal", journal_save)
    if failure == "state":
        monkeypatch.setattr(State, "save", state_save)
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 2, result.output
    monkeypatch.setattr(migration, "save_journal", original_journal)
    monkeypatch.setattr(State, "save", original_state)
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and old_id not in collection.notes
    note = next(iter(collection.notes.values()))
    assert "previous_topic" not in note["tags"] and "personal" in note["tags"]
    assert sum(c == "addNote" for c in collection.calls) == 1
    assert sync(server, tmp_path).exit_code == 0
    path.write_text(path.read_text().replace("tags: [topic]", "tags: []"))
    assert sync(server, tmp_path).exit_code == 0
    assert "topic" not in note["tags"]


def test_edit_during_creation_does_not_overwrite_source_or_delete_original(
    monkeypatch, server, tmp_path
):
    collection, _ = server
    old_id, path = old_note(collection, tmp_path)
    original = collection.action
    changed = path.read_text().replace("Answer", "Edited during migration")

    def action(name, params):
        result = original(name, params)
        if name == "addNote":
            path.write_text(changed)
        return result

    monkeypatch.setattr(collection, "action", action)
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 3, result.output
    assert old_id in collection.notes and len(collection.notes) == 2
    assert path.read_text() == changed
    assert "deleteNotes" not in collection.calls


def test_partial_multi_card_batch_recovers_completed_and_unfinished_replacements(
    monkeypatch, server, tmp_path
):
    collection, _ = server
    ids = [old_note(collection, tmp_path, name=f"{i}.md")[0] for i in range(2)]
    original = collection.action
    creates = 0

    def action(name, params):
        nonlocal creates
        result = original(name, params)
        if name == "addNote":
            creates += 1
            if creates == 2:
                collection.fail_after = name
        return result

    monkeypatch.setattr(collection, "action", action)
    assert migrate(server, tmp_path, "--reset-history").exit_code == 4
    assert ids[0] not in collection.notes and ids[1] in collection.notes
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 0, result.output
    assert creates == 2 and len(collection.notes) == 2
    assert not set(ids) & set(collection.notes)
    assert sync(server, tmp_path).exit_code == 0


def test_corrupt_migration_journal_blocks_writes(server, tmp_path):
    old_note(server[0], tmp_path)
    directory = tmp_path / ".ankiloom"
    directory.mkdir()
    path = directory / "yanki-migration.json"
    path.write_text('{"version": 1, "endpoint": "wrong", "notes": {}}')
    result = migrate(server, tmp_path, "--reset-history")
    assert result.exit_code == 3 and "Invalid migration journal" in result.output
    assert not server[0].calls
