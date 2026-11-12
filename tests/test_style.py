from click.testing import CliRunner

from ankiloom.cli import cli, skill_text
from ankiloom.models import CSS


def test_style_default_custom_and_preview(server, tmp_path):
    collection, url = server
    collection.models["AnkiLoom - Basic"] = {"fields": ["Front", "Back"], "css": "custom"}
    collection.models["Yanki - Basic"] = {"css": "legacy"}
    runner = CliRunner()
    args = ["style", "--url", url]
    assert runner.invoke(cli, [*args, "--default", "--dry-run"]).exit_code == 0
    assert collection.models["AnkiLoom - Basic"]["css"] == "custom"
    result = runner.invoke(cli, [*args, "--default"])
    assert result.exit_code == 0, result.output
    assert collection.models["AnkiLoom - Basic"]["css"] == CSS
    assert collection.models["Yanki - Basic"]["css"] == "legacy"
    path = tmp_path / "custom.css"
    path.write_text(".card { color: red; }")
    assert runner.invoke(cli, [*args, str(path)]).exit_code == 0
    assert collection.models["AnkiLoom - Basic"]["css"] == path.read_text()
    assert runner.invoke(cli, [*args]).exit_code == 2
    assert runner.invoke(cli, [*args, str(path), "--default"]).exit_code == 2
    text = skill_text()
    assert "--default" in text and "migrate-yanki" in text and "--reset-history" in text
    assert "--include-yanki" not in text


def test_sync_preserves_custom_styles(server, tmp_path):
    collection, url = server
    path = tmp_path / "card.md"
    path.write_text("Q\n\n---\n\nA")
    runner = CliRunner()
    args = ["sync", str(tmp_path), "--url", url]
    assert runner.invoke(cli, args).exit_code == 0
    collection.models["AnkiLoom - Basic"]["css"] = "custom"
    path.write_text(path.read_text().replace("\nA", "\nUpdated"))
    assert runner.invoke(cli, args).exit_code == 0
    assert collection.models["AnkiLoom - Basic"]["css"] == "custom"
