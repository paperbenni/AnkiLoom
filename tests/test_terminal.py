"""Presentation, machine output and request-count regressions."""

import io
import json

from click.testing import CliRunner
from rich.console import Console

from ankiloom import service, terminal
from ankiloom.anki import AnkiConnect
from ankiloom.cli import cli, skill_text
from ankiloom.progress import ProgressUpdate
from ankiloom.terminal import SyncDisplay


def make(root, name="card.md", note_id=None):
    path = root / name
    path.write_text((f"---\nnoteId: {note_id}\n---\n" if note_id else "") + "Q\n\n---\n\nA")
    return path


def invoke(server, root, *global_options, json_output=False):
    args = [*global_options, "sync", str(root), "--url", server[1]]
    if json_output:
        args.append("--json")
    return CliRunner().invoke(cli, args, color=True)


def test_unchanged_sync_uses_three_requests_for_44_notes(monkeypatch, server, tmp_path):
    for i in range(44):
        make(tmp_path, f"card-{i}.md")
    assert invoke(server, tmp_path, json_output=True).exit_code == 0
    calls = []
    original = AnkiConnect.call

    def counted(self, action, **params):
        calls.append(action)
        return original(self, action, **params)

    monkeypatch.setattr(AnkiConnect, "call", counted)
    result = invoke(server, tmp_path, json_output=True)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["summary"] == {"unchanged": 44}
    assert calls == ["version", "notesInfo", "cardsInfo"]


def test_recheck_before_write_still_blocks_concurrent_anki_edit(monkeypatch, server, tmp_path):
    path = make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    path.write_text(path.read_text().replace("\nA", "\nUpdated"))
    original = service.apply

    def edited_apply(entries, removed, client, state, **kwargs):
        next(iter(server[0].notes.values()))["fields"]["Back"] = "External edit"
        return original(entries, removed, client, state, **kwargs)

    monkeypatch.setattr(service, "apply", edited_apply)
    result = invoke(server, tmp_path, json_output=True)
    assert result.exit_code == 3
    assert "changed during sync" in result.stdout
    assert next(iter(server[0].notes.values()))["fields"]["Back"] == "External edit"


def test_duplicate_errors_group_once_but_json_keeps_every_path(server, tmp_path):
    for i in range(44):
        make(tmp_path, f"card-{i}.md", note_id=server[0].note())
    result = invoke(server, tmp_path, json_output=True)
    assert result.exit_code == 3
    error = json.loads(result.stdout)["error"]
    assert len(error["details"]) == 44
    assert error["message"].count("Existing note needs explicit adoption") == 1
    assert "41 more" in error["message"]
    verbose = invoke(server, tmp_path, "--verbose")
    assert "41 more" not in verbose.output and "card-43.md" in verbose.output


def test_color_always_overrides_no_color_and_never_disables_color(server, tmp_path):
    make(tmp_path)
    runner = CliRunner()
    args = ["sync", str(tmp_path), "--url", server[1]]
    colored = runner.invoke(cli, ["--color", "always", *args], env={"NO_COLOR": "1"}, color=True)
    assert colored.exit_code == 0, colored.output
    assert "\x1b[" in colored.stdout
    plain = runner.invoke(cli, ["--color", "never", *args], env={"FORCE_COLOR": "1"}, color=True)
    assert plain.exit_code == 0 and "\x1b[" not in plain.stdout
    auto = runner.invoke(cli, args, env={"NO_COLOR": "1"}, color=True)
    assert auto.exit_code == 0 and "\x1b[" not in auto.stdout


def test_json_stays_clean_with_forced_color_and_progress(server, tmp_path):
    make(tmp_path)
    result = invoke(server, tmp_path, "--color", "always", "--progress", json_output=True)
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"]
    assert "\x1b" not in result.stdout and result.stderr == ""


def test_summary_hides_unchanged_paths_unless_verbose(server, tmp_path):
    make(tmp_path)
    assert invoke(server, tmp_path).exit_code == 0
    result = invoke(server, tmp_path)
    assert "up to date" in result.stdout and "card.md" not in result.stdout
    verbose = invoke(server, tmp_path, "--verbose")
    assert "unchanged" in verbose.stdout and "card.md" in verbose.stdout


def test_progress_precedes_network_error_and_can_be_disabled(tmp_path):
    make(tmp_path)
    runner = CliRunner()
    args = ["sync", str(tmp_path), "--url", "http://127.0.0.1:1", "--timeout", "0.1"]
    result = runner.invoke(cli, ["--progress", *args])
    assert result.exit_code == 4
    assert result.stderr.index("Connecting to Anki") < result.stderr.index("Error")
    quiet = runner.invoke(cli, ["--no-progress", *args])
    assert quiet.exit_code == 4 and "Connecting to Anki…" not in quiet.stderr


def test_live_progress_handles_indeterminate_phases_and_cleans_up(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = io.StringIO()
    out = Console(file=stream, force_terminal=True, width=100, color_system=None)
    monkeypatch.setattr(terminal, "console", lambda **kwargs: out)
    monkeypatch.setattr(terminal, "preferences", lambda: {"progress": True})
    with SyncDisplay() as display:
        display.update(ProgressUpdate("Reading Markdown", 0, 44))
        display.update(ProgressUpdate("Connecting to Anki"))
        assert display.live is not None and display.live.tasks[0].total is None
        display.update(ProgressUpdate("Checking notes", 44, 44))
    assert display.live is None
    assert "Connecting to Anki" in stream.getvalue()


def test_help_and_skill_reference_share_definitions_without_ansi():
    result = CliRunner().invoke(cli, ["--color", "always", "--help"], color=True)
    assert result.exit_code == 0 and "\x1b[" in result.stdout
    text = skill_text()
    assert "--color" in text and "--no-progress" in text and "--verbose" in text
    assert "\x1b" not in text
