"""Exercise the long-running watcher deterministically with real HTTP syncs."""

import json

from click.testing import CliRunner
from filelock import FileLock

from ankiloom import watch as watch_module
from ankiloom.cli import cli
from ankiloom.service import SyncOptions
from ankiloom.watch import watch_folder


def card(root, name="card.md"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Question\n\n---\n\nAnswer")
    return path


class Clock:
    def __init__(self, steps, ticks):
        self.now = 0.0
        self.tick = 0
        self.steps = steps
        self.ticks = ticks

    def sleep(self, seconds):
        self.tick += 1
        if self.tick > self.ticks:
            raise KeyboardInterrupt
        self.now += seconds
        if self.tick in self.steps:
            self.steps[self.tick]()

    def monotonic(self):
        return self.now


def install_clock(monkeypatch, steps=None, ticks=5):
    clock = Clock(steps or {}, ticks)
    monkeypatch.setattr(watch_module, "sleep", clock.sleep)
    monkeypatch.setattr(watch_module, "monotonic", clock.monotonic)
    return clock


def run(monkeypatch, server, root, steps=None, ticks=5, **kwargs):
    install_clock(monkeypatch, steps, ticks)
    events = []
    options = SyncOptions(root=root, url=server[1], **kwargs)
    watch_folder(options, events.append, retry_delay=2)
    return events


def syncs(events):
    return [e for e in events if e["event"] == "sync"]


def test_initial_sync_does_not_loop_on_own_ids_or_journal(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    events = run(monkeypatch, server, tmp_path)
    assert len(syncs(events)) == 1
    assert len(server[0].notes) == 1
    source = path.read_text()
    assert "noteId:" in source and "loomId:" not in source
    assert events[-1]["event"] == "stopped"


def test_multi_card_metadata_writes_do_not_trigger_another_sync(monkeypatch, server, tmp_path):
    path = tmp_path / "study.md"
    path.write_text("---\nankiloom: multi\n---\nQ :: A\nR :: B\n\n## Third\n\n---\n\nC\n")
    events = run(monkeypatch, server, tmp_path)
    assert len(syncs(events)) == 1
    assert len(server[0].notes) == 3
    assert path.read_text().count("<!-- ankiloom noteId:") == 3


def test_burst_of_edits_is_debounced(monkeypatch, server, tmp_path):
    path = card(tmp_path)

    def edit(number):
        def save():
            text = path.read_text().split("Answer")[0]
            path.write_text(text + f"Answer {number}")

        return save

    events = run(monkeypatch, server, tmp_path, {1: edit(1), 2: edit(2), 3: edit(3)}, ticks=7)
    assert len(syncs(events)) == 2
    assert "Answer 3" in next(iter(server[0].notes.values()))["fields"]["Back"]


def test_media_change_triggers_sync(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    image = tmp_path / "diagram.png"
    image.write_bytes(b"old")
    path.write_text(path.read_text() + "\n\n![diagram](diagram.png)")
    events = run(monkeypatch, server, tmp_path, {1: lambda: image.write_bytes(b"new")})
    assert len(syncs(events)) == 2
    assert server[0].calls.count("storeMediaFile") == 2


def test_excluded_hidden_and_state_files_are_ignored(monkeypatch, server, tmp_path):
    card(tmp_path)
    (tmp_path / "drafts").mkdir()
    (tmp_path / "ankiloom.toml").write_text('exclude = ["drafts/**"]')
    events = run(
        monkeypatch,
        server,
        tmp_path,
        {
            1: lambda: (tmp_path / "drafts" / "bad.md").write_text("not a card"),
            2: lambda: (tmp_path / ".editor-swap").write_text("temporary"),
            3: lambda: (tmp_path / ".ankiloom" / "other.json").write_text("{}"),
        },
    )
    assert len(syncs(events)) == 1


def test_config_is_reloaded_on_change(monkeypatch, server, tmp_path):
    card(tmp_path)
    events = run(
        monkeypatch,
        server,
        tmp_path,
        {
            1: lambda: (tmp_path / "ankiloom.toml").write_text('deck = "New"'),
        },
    )
    assert len(syncs(events)) == 2
    assert next(iter(server[0].notes.values()))["deck"] == "New"


def test_edits_during_sync_are_not_swallowed(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    real_sync = watch_module.sync_once
    first = True

    def editing_sync(options, **kwargs):
        nonlocal first
        result = real_sync(options, **kwargs)
        if first:
            first = False
            path.write_text(path.read_text().replace("Answer", "Edited during sync"))
        return result

    monkeypatch.setattr(watch_module, "sync_once", editing_sync)
    events = run(monkeypatch, server, tmp_path)
    assert len(syncs(events)) == 2
    assert "Edited during sync" in next(iter(server[0].notes.values()))["fields"]["Back"]


def test_create_move_delete_without_pruning(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    folder = tmp_path / "course"
    folder.mkdir()
    moved = folder / "moved.md"
    events = run(
        monkeypatch,
        server,
        tmp_path,
        {
            1: lambda: path.rename(moved),
            3: lambda: card(tmp_path, "new.md"),
            5: moved.unlink,
        },
        ticks=8,
    )
    assert len(syncs(events)) == 4
    assert len(server[0].notes) == 2
    assert "deleteNotes" not in server[0].calls
    assert any(note["deck"] == "course" for note in server[0].notes.values())


def test_validation_error_waits_for_fixed_card(monkeypatch, server, tmp_path):
    path = tmp_path / "card.md"
    path.write_text("incomplete")
    events = run(monkeypatch, server, tmp_path, {1: lambda: card(tmp_path)})
    assert [e["event"] for e in events] == ["watching", "error", "sync", "stopped"]
    assert events[1]["retryIn"] is None
    assert len(server[0].notes) == 1


def test_invalid_config_can_be_fixed_while_watching(monkeypatch, server, tmp_path):
    card(tmp_path)
    config = tmp_path / "ankiloom.toml"
    config.write_text("invalid = [")
    events = run(monkeypatch, server, tmp_path, {1: lambda: config.write_text('deck = "Fixed"')})
    assert [e["event"] for e in events] == ["watching", "error", "sync", "stopped"]
    assert next(iter(server[0].notes.values()))["deck"] == "Fixed"


def test_connection_failure_retries_without_file_edit(monkeypatch, server, tmp_path):
    card(tmp_path)
    server[0].fail_after = "version"
    events = run(monkeypatch, server, tmp_path)
    assert events[1]["event"] == "error" and events[1]["retryIn"] == 2
    assert len(syncs(events)) == 1 and syncs(events)[0]["trigger"] == "retry"
    assert len(server[0].notes) == 1


def test_lost_create_response_recovers_without_duplicates(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    server[0].fail_after = "addNote"
    events = run(monkeypatch, server, tmp_path, ticks=7)
    assert len(syncs(events)) == 1
    assert len(server[0].notes) == 1 and "noteId:" in path.read_text()


def test_busy_lock_retries_after_other_sync_finishes(monkeypatch, server, tmp_path):
    card(tmp_path)
    directory = tmp_path / ".ankiloom"
    directory.mkdir()
    lock = FileLock(directory / "sync.lock")
    with lock:
        events = run(monkeypatch, server, tmp_path, {1: lock.release})
    assert events[1]["event"] == "error" and events[1]["retryIn"] == 2
    assert len(syncs(events)) == 1


def test_conflict_waits_and_does_not_force_overwrite(monkeypatch, server, tmp_path):
    path = card(tmp_path)

    def edit_both_sides():
        next(iter(server[0].notes.values()))["fields"]["Back"] = "Anki edit"
        path.write_text(path.read_text().replace("Answer", "Markdown edit"))

    events = run(monkeypatch, server, tmp_path, {1: edit_both_sides}, ticks=15)
    assert len(syncs(events)) == 1
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1 and errors[0]["retryIn"] is None
    assert next(iter(server[0].notes.values()))["fields"]["Back"] == "Anki edit"


def test_dry_run_never_writes_ids_or_anki(monkeypatch, server, tmp_path):
    path = card(tmp_path)
    events = run(
        monkeypatch,
        server,
        tmp_path,
        {
            1: lambda: path.write_text(path.read_text().replace("Answer", "Edited")),
        },
        dry_run=True,
    )
    assert len(syncs(events)) == 2 and all(e["dryRun"] for e in syncs(events))
    assert not server[0].notes and not server[0].models
    assert "noteId:" not in path.read_text() and not (tmp_path / ".ankiloom").exists()


def test_json_cli_emits_events_and_ctrl_c_stops_cleanly(monkeypatch, server, tmp_path):
    card(tmp_path)
    install_clock(monkeypatch, ticks=3)
    result = CliRunner().invoke(cli, ["watch", str(tmp_path), "--url", server[1], "--json"])
    assert result.exit_code == 0, result.output
    assert [json.loads(line)["event"] for line in result.output.splitlines()] == [
        "watching",
        "sync",
        "stopped",
    ]
