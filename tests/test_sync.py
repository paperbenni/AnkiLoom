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
    assert "noteId:" in path.read_text() and "loomId:" in path.read_text()
    card_ids = note["cards"][:]
    collection.calls.clear()
    assert invoke(server, tmp_path).exit_code == 0
    assert not {"addNote", "updateNoteFields", "storeMediaFile", "addTags"} & set(collection.calls)
    path.write_text(path.read_text().replace("Answer", "Updated"))
    assert invoke(server, tmp_path).exit_code == 0
    assert "Updated" in note["fields"]["Back"]
    assert note["cards"] == card_ids and note["reviews"] == 42


def test_adopt_preserves_model_id_reviews_and_unrelated_tags(server, tmp_path):
    collection, _ = server
    note_id = collection.note()
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
    assert note["modelName"] == "Yanki - Basic" and note["reviews"] == 42
    assert note["fields"]["YankiNamespace"] == "Yanki" and "personal" in note["tags"]


def test_all_preflight_before_mutations(server, tmp_path):
    collection, _ = server
    make(tmp_path, "a.md")
    make(tmp_path, "b.md", note_id=9999)
    result = invoke(server, tmp_path)
    assert result.exit_code == 3
    assert not collection.notes and "createModel" not in collection.calls
    assert "loomId" not in (tmp_path / "a.md").read_text()


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
    assert "loomId:" in path.read_text() and "noteId:" not in path.read_text()
    result = invoke(server, tmp_path)
    assert result.exit_code == 0, result.output
    assert len(collection.notes) == 1 and "noteId:" in path.read_text()


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
