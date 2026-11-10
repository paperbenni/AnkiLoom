"""Update decisions and installer failures without altering the test environment."""

import base64
import json
import subprocess
from dataclasses import replace
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest
from click.testing import CliRunner

from ankiloom import update as updater
from ankiloom.cli import cli
from ankiloom.errors import LoomError
from ankiloom.update import Installation, Target, update_installation

OLD = "a" * 40
NEW = "b" * 40


@pytest.fixture
def managed(monkeypatch, tmp_path):
    prefix = tmp_path / "ankiloom"
    prefix.mkdir()
    (prefix / "uv-receipt.toml").write_text('[tool]\nrequirements = [{ name = "ankiloom" }]')
    installation = Installation("0.3.0", prefix, "uv-tool", "uv-test", OLD, updater.REPOSITORY)
    monkeypatch.setattr(updater, "detect_installation", lambda: installation)
    monkeypatch.setattr(
        updater,
        "resolve_target",
        lambda **kwargs: Target("0.4.0", "v0.4.0", NEW, "head" if kwargs["head"] else "release"),
    )
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "uv output", "uv diagnostics")

    monkeypatch.setattr(updater, "run_process", run)
    monkeypatch.setattr(
        updater, "installed_after_update", lambda prefix: {"version": "0.4.0", "commit": NEW}
    )
    return installation, calls


def test_release_update_delegates_to_uv_and_verifies_result(managed):
    _, calls = managed
    report = update_installation()
    assert report["status"] == "updated"
    assert report["currentVersion"] == "0.3.0" and report["installedVersion"] == "0.4.0"
    assert len(calls) == 1 and calls[0][:3] == ["uv-test", "tool", "install"]
    assert calls[0][-1] == f"git+{updater.REPOSITORY}@{NEW}"


def test_check_does_not_run_installer(managed):
    _, calls = managed
    report = update_installation(check=True)
    assert report["status"] == "update_available" and report["check"] is True
    assert calls == []


@pytest.mark.parametrize(
    ("current", "target", "status"), [("0.4.0", "0.4.0", "up_to_date"), ("0.5.0", "0.4.0", "ahead")]
)
def test_no_update_or_implicit_downgrade(managed, monkeypatch, current, target, status):
    installation, calls = managed
    monkeypatch.setattr(
        updater, "detect_installation", lambda: replace(installation, version=current)
    )
    monkeypatch.setattr(
        updater, "resolve_target", lambda **kwargs: Target(target, "v" + target, NEW, "release")
    )
    assert update_installation()["status"] == status
    assert calls == []


def test_head_compares_commits_even_when_versions_match(managed, monkeypatch):
    installation, calls = managed
    monkeypatch.setattr(
        updater, "detect_installation", lambda: replace(installation, version="0.4.0")
    )
    report = update_installation(head=True)
    assert report["status"] == "updated" and report["currentCommit"] == OLD
    assert report["installedCommit"] == NEW and len(calls) == 1


def test_matching_head_commit_does_not_reinstall(managed, monkeypatch):
    installation, calls = managed
    monkeypatch.setattr(
        updater, "detect_installation", lambda: replace(installation, version="0.4.0", commit=NEW)
    )
    assert update_installation(head=True)["status"] == "up_to_date"
    assert calls == []


@pytest.mark.parametrize("kind", ["editable", "pipx", "virtualenv", "python"])
def test_other_installations_get_manual_instructions_but_can_check(managed, monkeypatch, kind):
    installation, calls = managed
    monkeypatch.setattr(updater, "detect_installation", lambda: replace(installation, kind=kind))
    with pytest.raises(LoomError) as exc:
        update_installation()
    assert exc.value.code == "installation"
    assert update_installation(check=True)["status"] == "update_available"
    assert calls == []


def test_custom_requirements_are_not_silently_lost(managed):
    installation, calls = managed
    (installation.prefix / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{name="ankiloom"}, {name="other"}]'
    )
    with pytest.raises(LoomError, match="custom requirements"):
        update_installation()
    assert calls == []


def test_fork_is_not_replaced_with_official_repo(managed, monkeypatch):
    installation, calls = managed
    monkeypatch.setattr(
        updater,
        "detect_installation",
        lambda: replace(installation, source="https://github.com/someone/fork"),
    )
    with pytest.raises(LoomError, match="another source"):
        update_installation()
    assert calls == []


def test_installer_failure_is_actionable(managed, monkeypatch):
    monkeypatch.setattr(
        updater,
        "run_process",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, "", "Build failed"),
    )
    with pytest.raises(LoomError, match="Build failed") as exc:
        update_installation()
    assert exc.value.code == "update"


@pytest.mark.parametrize(
    "installed", [{"version": "0.3.0", "commit": NEW}, {"version": "0.4.0", "commit": OLD}]
)
def test_wrong_version_or_commit_is_not_reported_as_success(managed, monkeypatch, installed):
    monkeypatch.setattr(updater, "installed_after_update", lambda prefix: installed)
    with pytest.raises(LoomError, match="does not match"):
        update_installation()


def test_json_is_one_result_without_uv_noise(managed):
    result = CliRunner().invoke(cli, ["--color", "always", "--progress", "update", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"] == "updated"
    assert "\x1b" not in result.stdout and result.stderr == ""


def test_cli_update_error_has_documented_exit_code(managed, monkeypatch):
    monkeypatch.setattr(
        updater,
        "resolve_target",
        lambda **kwargs: (_ for _ in ()).throw(LoomError("Network unavailable", "update")),
    )
    result = CliRunner().invoke(cli, ["update", "--check", "--json"])
    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["code"] == "update"


def test_target_resolution_distinguishes_release_from_head(monkeypatch):
    paths = []

    def github(path, **kwargs):
        paths.append(path)
        if path == "releases/latest":
            return {"tag_name": "v0.4.0", "draft": False, "prerelease": False}
        if path.startswith("commits/"):
            return {"sha": NEW}
        return {"content": base64.b64encode(b'[project]\nversion="0.4.0"').decode()}

    monkeypatch.setattr(updater, "github_json", github)
    release = updater.resolve_target(head=False, timeout=1)
    assert release.channel == "release" and paths == ["releases/latest", "commits/v0.4.0"]
    paths.clear()
    head = updater.resolve_target(head=True, timeout=1)
    assert head.channel == "head" and paths == [
        "commits/HEAD",
        f"contents/pyproject.toml?ref={NEW}",
    ]


@pytest.mark.parametrize(
    "payload",
    [{"tag_name": "v0.5.0rc1"}, {"tag_name": "invalid"}, {"tag_name": "v0.4.0", "draft": True}],
)
def test_bad_or_prerelease_release_is_rejected(monkeypatch, payload):
    monkeypatch.setattr(updater, "github_json", lambda *args, **kwargs: payload)
    with pytest.raises(LoomError):
        updater.resolve_target(head=False, timeout=1)


def test_invalid_head_sha_has_actionable_error(monkeypatch):
    monkeypatch.setattr(updater, "github_json", lambda *args, **kwargs: {"sha": None})
    with pytest.raises(LoomError, match="invalid commit"):
        updater.resolve_target(head=True, timeout=1)


def test_http_failure_is_reported_without_traceback(monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(updater, "urlopen", unavailable)
    with pytest.raises(LoomError, match="offline"):
        updater.github_json("releases/latest", timeout=1)


def test_rate_limit_error_is_explicit(monkeypatch):
    def limited(*args, **kwargs):
        headers = Message()
        headers["X-RateLimit-Remaining"] = "0"
        raise HTTPError("https://api.github.com", 403, "Forbidden", headers, None)

    monkeypatch.setattr(updater, "urlopen", limited)
    with pytest.raises(LoomError, match="rate limit"):
        updater.github_json("releases/latest", timeout=1)


class Distribution:
    version = "0.3.0"

    def __init__(self, direct):
        self.direct = direct

    def read_text(self, filename):
        return json.dumps(self.direct)


@pytest.mark.parametrize(
    ("editable", "in_tools", "expected"),
    [(False, True, "uv-tool"), (True, True, "editable"), (False, False, "virtualenv")],
)
def test_manager_detection_does_not_confuse_uvx_or_editable_with_tools(
    monkeypatch, tmp_path, editable, in_tools, expected
):
    tools = tmp_path / "tools"
    prefix = (tools if in_tools else tmp_path / "cache") / "ankiloom"
    prefix.mkdir(parents=True)
    (prefix / "uv-receipt.toml").write_text('[tool]\nrequirements=[{name="ankiloom"}]')
    monkeypatch.setattr(updater.sys, "prefix", str(prefix))
    monkeypatch.setattr(updater.sys, "base_prefix", str(tmp_path / "python"))
    monkeypatch.setattr(
        updater,
        "distribution",
        lambda name: Distribution({"url": updater.REPOSITORY, "dir_info": {"editable": editable}}),
    )
    monkeypatch.setattr(updater.shutil, "which", lambda name: "uv-test")
    monkeypatch.setattr(
        updater,
        "run_process",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, str(tools), ""),
    )
    assert updater.detect_installation().kind == expected


def test_interrupted_update_has_specific_structured_advice(managed, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(updater, "run_process", interrupted)
    result = CliRunner().invoke(cli, ["update", "--json"])
    assert result.exit_code == 130
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "interrupted" and "ankiloom --version" in error["message"]
