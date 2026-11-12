import json
from copy import deepcopy

import pytest
from click.testing import CliRunner
from filelock import FileLock

from ankiloom.cli import cli


def invoke(server, root, *args):
    return CliRunner().invoke(cli, ["sync", str(root), "--url", server[1], "--json", *args])


def make(root, name="card.md", note_id=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        (f"---\nnoteId: {note_id}\ntags: [topic]\n---\n\n" if note_id else "")
        + "Question\n\n---\n\nAnswer"
    )
    return path


def test_create_update_and_idempotence(server, tmp_path):
    collection, _ = server
    path = make(tmp_path, "course/card.md")
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    note = next(iter(collection.notes.values()))
    assert note["deck"] == "course"
    source = path.read_text()
    assert "noteId:" in source and "loomId:" not in source
    assert not any(t.startswith(("ankiloom::id::", "ankiloom::create::")) for t in note["tags"])
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert state["version"] == 2 and state["pendingCreations"] == {}
    card_ids = note["cards"][:]
    collection.calls.clear()
    assert invoke(server, tmp_path).exit_code == 0
    assert not {"addNote", "updateNoteFields", "storeMediaFile", "addTags"} & set(collection.calls)
    path.write_text(path.read_text().replace("Answer", "Updated"))
    assert invoke(server, tmp_path).exit_code == 0
    assert "Updated" in note["fields"]["Back"]
    assert note["cards"] == card_ids and note["reviews"] == 0


def test_adopt_preserves_model_id_reviews_and_unrelated_tags(server, tmp_path):
    collection, _ = server
    note_id = collection.note(fields={"Front": "old front", "Back": "old back", "Personal": "keep"})
    path = make(tmp_path, note_id=note_id)
    assert invoke(server, tmp_path).exit_code == 3
    before = deepcopy(collection.notes)
    source = path.read_bytes()
    local_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = invoke(server, tmp_path, "--adopt", "--dry-run")
    assert result.exit_code == 0, result.output
    assert collection.notes == before and path.read_bytes() == source
    assert local_before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert invoke(server, tmp_path, "--adopt").exit_code == 0
    note = collection.notes[note_id]
    assert len(collection.notes) == 1
    assert note["modelName"] == "AnkiLoom - Basic" and note["reviews"] == 42
    assert note["fields"]["Personal"] == "keep"
    assert "personal" in note["tags"]


def test_all_preflight_before_mutations(server, tmp_path):
    collection, _ = server
    make(tmp_path, "a.md")
    make(tmp_path, "b.md", note_id=9999)
    result = invoke(server, tmp_path)
    assert result.exit_code == 3
    assert not collection.notes and "createModel" not in collection.calls
    assert "loomId" not in (tmp_path / "a.md").read_text()
    assert "noteId" not in (tmp_path / "a.md").read_text()


@pytest.mark.parametrize("edit", ["fields", "tags", "deck"])
def test_remote_edit_conflicts_and_force(server, tmp_path, edit):
    collection, _ = server
    make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    note = next(iter(collection.notes.values()))
    if edit == "fields":
        note["fields"]["Back"] = "Edited in Anki"
    elif edit == "tags":
        note["tags"].append("manual")
    else:
        note["deck"] = "manual"
    assert invoke(server, tmp_path).exit_code == 3
    assert invoke(server, tmp_path, "--force").exit_code == 0
    assert "Answer" in note["fields"]["Back"]


def test_lost_create_response_does_not_duplicate(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    collection.fail_after = "addNote"
    assert invoke(server, tmp_path).exit_code == 4
    assert len(collection.notes) == 1
    source = path.read_text()
    assert "noteId:" not in source and "loomId:" not in source
    note = next(iter(collection.notes.values()))
    creation_tags = [t for t in note["tags"] if t.startswith("ankiloom::create::")]
    assert len(creation_tags) == 1
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert list(state["pendingCreations"]) == [creation_tags[0].removeprefix("ankiloom::create::")]
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and "noteId:" in path.read_text()
    assert not any(t.startswith("ankiloom::create::") for t in note["tags"])
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert state["pendingCreations"] == {}


def test_lost_create_response_survives_rename(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    collection.fail_after = "addNote"
    assert invoke(server, tmp_path).exit_code == 4
    assert len(collection.notes) == 1
    renamed = tmp_path / "course" / "renamed.md"
    renamed.parent.mkdir()
    path.rename(renamed)
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1
    note = next(iter(collection.notes.values()))
    assert note["deck"] == "course"
    assert "noteId:" in renamed.read_text() and not path.exists()
    assert not any(t.startswith("ankiloom::create::") for t in note["tags"])
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert state["pendingCreations"] == {}


@pytest.mark.parametrize("action", ["createDeck", "addNote"])
def test_interrupted_create_batch_resumes_uncreated_notes(server, tmp_path, action):
    collection, _ = server
    paths = [make(tmp_path, name) for name in ("a.md", "b.md")]
    collection.fail_after = action
    assert invoke(server, tmp_path).exit_code == 4
    original_ids = set(collection.notes)
    state_path = tmp_path / ".ankiloom" / "state.json"
    before = state_path.read_bytes()
    sources = [path.read_bytes() for path in paths]
    notes = deepcopy(collection.notes)
    preview = invoke(server, tmp_path, "--dry-run")
    assert preview.exit_code == 0, preview.output
    assert state_path.read_bytes() == before
    assert [path.read_bytes() for path in paths] == sources
    assert collection.notes == notes
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 2 and original_ids <= set(collection.notes)
    assert all("noteId:" in path.read_text() for path in paths)
    assert all(
        not any(tag.startswith("ankiloom::create::") for tag in note["tags"])
        for note in collection.notes.values()
    )
    assert json.loads(state_path.read_text())["pendingCreations"] == {}


def test_lost_create_response_after_journal_note_id_saved(monkeypatch, server, tmp_path):
    from ankiloom import sync as sync_module

    collection, _ = server
    path = make(tmp_path)
    original = sync_module.write_metadata

    def fail_metadata(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sync_module, "write_metadata", fail_metadata)
    assert invoke(server, tmp_path).exit_code == 2
    assert len(collection.notes) == 1
    assert "noteId:" not in path.read_text()
    note = next(iter(collection.notes.values()))
    assert any(t.startswith("ankiloom::create::") for t in note["tags"])
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    _token, record = next(iter(state["pendingCreations"].items()))
    assert record["noteId"] == note["noteId"]
    monkeypatch.setattr(sync_module, "write_metadata", original)
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and "noteId:" in path.read_text()
    assert not any(t.startswith("ankiloom::create::") for t in note["tags"])
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert state["pendingCreations"] == {}


def test_dry_run_after_lost_create_preserves_journal(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    collection.fail_after = "addNote"
    assert invoke(server, tmp_path).exit_code == 4
    state_path = tmp_path / ".ankiloom" / "state.json"
    before = state_path.read_bytes()
    source = path.read_bytes()
    assert invoke(server, tmp_path, "--dry-run").exit_code == 0
    assert state_path.read_bytes() == before and path.read_bytes() == source
    assert len(collection.notes) == 1


def test_interrupted_creation_with_deleted_known_note_is_not_recreated(
    monkeypatch, server, tmp_path
):
    from ankiloom import sync as sync_module

    collection, _ = server
    path = make(tmp_path)
    original = sync_module.write_metadata

    def fail_metadata(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sync_module, "write_metadata", fail_metadata)
    assert invoke(server, tmp_path).exit_code == 2
    monkeypatch.setattr(sync_module, "write_metadata", original)
    assert "noteId:" not in path.read_text()
    state_path = tmp_path / ".ankiloom" / "state.json"
    before = state_path.read_bytes()
    state = json.loads(before)
    assert next(iter(state["pendingCreations"].values()))["noteId"] in collection.notes
    collection.notes.clear()
    collection.calls.clear()
    result = invoke(server, tmp_path)
    assert result.exit_code == 3
    assert "which no longer exists" in result.output
    assert "addNote" not in collection.calls and not collection.notes
    assert state_path.read_bytes() == before


@pytest.mark.parametrize("action", ["updateNoteFields", "changeDeck", "removeTags", "addTags"])
def test_lost_update_response_can_resume(server, tmp_path, action):
    collection, _ = server
    note_id = collection.note()
    path = make(tmp_path, note_id=note_id)
    assert invoke(server, tmp_path, "--adopt").exit_code == 0
    path.write_text(path.read_text().replace("Answer", "New answer").replace("topic", "newtopic"))
    path.rename(tmp_path / "renamed.md")
    (tmp_path / "course").mkdir()
    (tmp_path / "renamed.md").rename(tmp_path / "course" / "renamed.md")
    collection.fail_after = action
    assert invoke(server, tmp_path).exit_code == 4
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and collection.notes[note_id]["deck"] == "course"
    assert (
        "newtopic" in collection.notes[note_id]["tags"]
        and "topic" not in collection.notes[note_id]["tags"]
    )


def test_missing_remote_note_does_not_recreate(server, tmp_path):
    collection, _ = server
    make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    collection.notes.clear()
    assert invoke(server, tmp_path).exit_code == 3
    assert not collection.notes


def test_explicit_prune_and_empty_root_guard(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    make(tmp_path, "keep.md")
    assert invoke(server, tmp_path).exit_code == 0
    path.unlink()
    assert invoke(server, tmp_path).exit_code == 0 and len(collection.notes) == 2
    assert (
        invoke(server, tmp_path, "--prune", "--dry-run").exit_code == 0
        and len(collection.notes) == 2
    )
    assert invoke(server, tmp_path, "--prune").exit_code == 0 and len(collection.notes) == 1
    (tmp_path / "keep.md").unlink()
    assert invoke(server, tmp_path, "--prune").exit_code == 2 and len(collection.notes) == 1


def test_prune_remote_changes_refused(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    make(tmp_path, "keep.md")
    assert invoke(server, tmp_path).exit_code == 0
    note_id = next(iter(collection.notes))
    path.unlink()
    collection.notes[note_id]["fields"]["Front"] = "manual change"
    assert invoke(server, tmp_path, "--prune").exit_code == 3
    assert len(collection.notes) == 2


def test_sync_lock(server, tmp_path):
    make(tmp_path)
    (tmp_path / ".ankiloom").mkdir()
    with FileLock(tmp_path / ".ankiloom" / "sync.lock"):
        result = invoke(server, tmp_path)
    assert result.exit_code == 3 and "holds" in result.output


def test_note_type_change_refused_even_with_force(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    path.write_text(path.read_text().replace("Question\n\n---\n\nAnswer", "~~Cloze~~"))
    assert invoke(server, tmp_path, "--force").exit_code == 3
    assert len(collection.notes) == 1


def test_deck_move_and_tag_removal(server, tmp_path):
    collection, _ = server
    path = make(tmp_path, "a/card.md", note_id=collection.note())
    assert invoke(server, tmp_path, "--adopt").exit_code == 0
    (tmp_path / "b").mkdir()
    new = tmp_path / "b" / "card.md"
    path.rename(new)
    new.write_text(new.read_text().replace("tags: [topic]", "tags: []"))
    assert invoke(server, tmp_path).exit_code == 0
    note = next(iter(collection.notes.values()))
    assert note["deck"] == "b" and "topic" not in note["tags"] and "personal" in note["tags"]


def test_model_schema_preflight_in_dry_run(server, tmp_path):
    collection, _ = server
    collection.models["AnkiLoom - Basic"] = {"fields": ["Wrong"]}
    make(tmp_path)
    result = invoke(server, tmp_path, "--dry-run")
    assert result.exit_code == 3 and not collection.notes


def test_json_error_contract(server, tmp_path):
    make(tmp_path, note_id=123)
    result = invoke(server, tmp_path)
    data = json.loads(result.output)
    assert data["ok"] is False and data["error"]["code"] == "preflight"


def test_lost_delete_response_recovers(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    make(tmp_path, "keep.md")
    assert invoke(server, tmp_path).exit_code == 0
    path.unlink()
    collection.fail_after = "deleteNotes"
    assert invoke(server, tmp_path, "--prune").exit_code == 4
    assert len(collection.notes) == 1
    result = invoke(server, tmp_path, "--prune")
    assert result.exit_code == 0, result.output
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    assert len(state["notes"]) == 1


def test_corrupt_journal_has_actionable_error(server, tmp_path):
    make(tmp_path)
    (tmp_path / ".ankiloom").mkdir()
    (tmp_path / ".ankiloom" / "state.json").write_text('{"version": 1, "notes": {"123": {}}}')
    result = invoke(server, tmp_path)
    assert result.exit_code == 3 and "Invalid sync journal" in result.output


def test_unwritable_metadata_fails_before_any_anki_writes(server, tmp_path):
    collection, _ = server
    make(tmp_path, "a.md")
    path = make(tmp_path, "z.md")
    path.write_text("---\n{tags: [test]}\n---\nQ\n\n---\n\nA")
    result = invoke(server, tmp_path)
    assert result.exit_code == 3 and "block-style YAML" in result.output
    assert not collection.notes
    assert "loomId" not in (tmp_path / "a.md").read_text()
    assert "noteId" not in (tmp_path / "a.md").read_text()


def test_recovered_update_finalizes_pending_journal(server, tmp_path):
    collection, _ = server
    path = make(tmp_path, note_id=collection.note())
    assert invoke(server, tmp_path, "--adopt").exit_code == 0
    path.write_text(path.read_text().replace("topic", "second"))
    collection.fail_after = "addTags"
    assert invoke(server, tmp_path).exit_code == 4
    assert invoke(server, tmp_path).exit_code == 0
    state = json.loads((tmp_path / ".ankiloom" / "state.json").read_text())
    record = next(iter(state["notes"].values()))
    assert "pending" not in record and record["sourceTags"] == ["second"]
    path.write_text(path.read_text().replace("second", "third"))
    assert invoke(server, tmp_path).exit_code == 0
    tags = next(iter(collection.notes.values()))["tags"]
    assert "third" in tags and "second" not in tags


def test_legacy_loom_id_only_recovers_interrupted_create(server, tmp_path):
    collection, _ = server
    loom_id = "a" * 32
    note_id = collection.note(
        model="AnkiLoom - Basic",
        fields={"Front": "old", "Back": "old"},
        tags=["ankiloom::managed", "ankiloom::id::" + loom_id],
    )
    path = tmp_path / "card.md"
    path.write_text(f"---\nloomId: {loom_id}\n---\n\nQuestion\n\n---\n\nAnswer")
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and note_id in collection.notes
    source = path.read_text()
    assert "noteId:" in source and "loomId:" not in source
    tags = collection.notes[note_id]["tags"]
    assert not any(t.startswith(("ankiloom::id::", "ankiloom::create::")) for t in tags)


@pytest.mark.parametrize("rename", [False, True])
def test_legacy_recovery_survives_lost_identity_removal_response(server, tmp_path, rename):
    collection, _ = server
    loom_id = "a" * 32
    note_id = collection.note(
        model="AnkiLoom - Basic",
        fields={"Front": "old", "Back": "old"},
        tags=["ankiloom::managed", "ankiloom::id::" + loom_id],
    )
    collection.models["AnkiLoom - Basic"]["fields"] = ["Front", "Back"]
    path = tmp_path / "card.md"
    path.write_text(f"---\nloomId: {loom_id}\n---\n\nQuestion\n\n---\n\nAnswer")
    cards = collection.notes[note_id]["cards"][:]
    collection.fail_after = "removeTags"
    assert invoke(server, tmp_path).exit_code == 4
    assert "noteId:" not in path.read_text()
    assert "ankiloom::id::" + loom_id not in collection.notes[note_id]["tags"]
    state_path = tmp_path / ".ankiloom" / "state.json"
    state = json.loads(state_path.read_text())
    assert next(iter(state["pendingCreations"].values()))["noteId"] == note_id
    if rename:
        renamed = tmp_path / "course" / "renamed.md"
        renamed.parent.mkdir()
        path.rename(renamed)
        path = renamed
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert list(collection.notes) == [note_id]
    note = collection.notes[note_id]
    assert note["cards"] == cards and note["reviews"] == 42
    assert f"noteId: {note_id}" in path.read_text() and "loomId:" not in path.read_text()
    assert json.loads(state_path.read_text())["pendingCreations"] == {}


def test_v1_journal_and_loom_id_migrate(server, tmp_path):
    collection, _ = server
    path = make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    note_id = next(iter(collection.notes))
    loom_id = "b" * 32
    source = path.read_text()
    path.write_text(source.replace("---\n", f"---\nloomId: {loom_id}\n", 1))
    note = collection.notes[note_id]
    note["tags"] = sorted(set(note["tags"]) | {"ankiloom::id::" + loom_id})
    state_path = tmp_path / ".ankiloom" / "state.json"
    state = json.loads(state_path.read_text())
    record = state["notes"][str(note_id)]
    record["loomId"] = loom_id
    record["snapshot"]["tags"] = sorted(
        set(record["snapshot"]["tags"]) | {"ankiloom::id::" + loom_id}
    )
    state["version"] = 1
    state.pop("pendingCreations", None)
    state_path.write_text(json.dumps(state))
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    source = path.read_text()
    assert "noteId:" in source and "loomId:" not in source
    assert not any(t.startswith("ankiloom::id::") for t in note["tags"])
    migrated = json.loads(state_path.read_text())
    assert migrated["version"] == 2
    assert "loomId" not in migrated["notes"][str(note_id)]
    assert migrated["pendingCreations"] == {}


def test_dry_run_create_does_not_create_local_state(server, tmp_path):
    make(tmp_path)
    assert invoke(server, tmp_path, "--dry-run").exit_code == 0
    assert not (tmp_path / ".ankiloom").exists()
    assert not server[0].notes and not server[0].models


def test_stale_pending_creation_without_note_is_cleared(server, tmp_path):
    collection, _ = server
    make(tmp_path, "keep.md")
    token = "c" * 32
    state_path = tmp_path / ".ankiloom" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "version": 2,
                "endpoint": server[1],
                "notes": {},
                "pendingCreations": {token: {"path": "missing.md", "fingerprint": "d" * 64}},
            }
        )
    )
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1
    state = json.loads(state_path.read_text())
    assert state["pendingCreations"] == {}


def test_orphaned_interrupted_creation_blocks_sync(server, tmp_path):
    collection, _ = server
    token = "e" * 32
    note_id = collection.note(tags=["ankiloom::managed", "ankiloom::create::" + token])
    make(tmp_path, "keep.md")
    state_path = tmp_path / ".ankiloom" / "state.json"
    state_path.parent.mkdir()
    state_path.write_text(
        json.dumps(
            {
                "version": 2,
                "endpoint": server[1],
                "notes": {},
                "pendingCreations": {token: {"path": "missing.md", "fingerprint": "d" * 64}},
            }
        )
    )
    result = invoke(server, tmp_path)
    assert result.exit_code == 3
    assert "no Markdown file claims it" in result.output
    assert list(collection.notes) == [note_id]
