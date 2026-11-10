"""Explicit GitHub updates delegated to uv's tool installer."""

import base64
import json
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import distribution
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from .errors import LoomError
from .progress import ProgressCallback, ProgressUpdate, no_progress

REPOSITORY = "https://github.com/paperbenni/AnkiLoom"
API = "https://api.github.com/repos/paperbenni/AnkiLoom"
INSTALL_HELP = f"uv tool install git+{REPOSITORY}"


@dataclass(frozen=True)
class Installation:
    version: str
    prefix: Path
    kind: str
    uv: str | None
    commit: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class Target:
    version: str
    ref: str
    commit: str
    channel: str

    @property
    def source(self) -> str:
        return f"git+{REPOSITORY}@{self.commit}"


def run_process(args: list[str], *, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise LoomError(
            "Update command timed out. Check the installed version before retrying.", "update"
        ) from exc
    except OSError as exc:
        raise LoomError(f"Could not run update command: {exc}", "update") from exc


def detect_installation() -> Installation:
    dist = distribution("ankiloom")
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
        if not isinstance(direct, dict) or any(
            not isinstance(direct.get(key, {}), dict) for key in ("vcs_info", "dir_info")
        ):
            raise ValueError("invalid direct URL metadata")
    except (ValueError, TypeError) as exc:
        raise LoomError(
            "Cannot read AnkiLoom's installation metadata; update it with its installer.",
            "installation",
        ) from exc
    prefix = Path(sys.prefix).resolve()
    uv = shutil.which("uv")
    source = direct.get("url")
    commit = direct.get("vcs_info", {}).get("commit_id")
    if (source is not None and not isinstance(source, str)) or (
        commit is not None and not isinstance(commit, str)
    ):
        raise LoomError("Invalid source or commit in installation metadata.", "installation")
    kind = "virtualenv" if sys.prefix != sys.base_prefix else "python"
    if direct.get("dir_info", {}).get("editable"):
        kind = "editable"
    elif (prefix / "pipx_metadata.json").is_file():
        kind = "pipx"
    elif uv:
        result = run_process([uv, "tool", "dir"], timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            tool_dir = Path(result.stdout.strip()).resolve()
            if prefix == tool_dir / "ankiloom" and (prefix / "uv-receipt.toml").is_file():
                kind = "uv-tool"
    return Installation(dist.version, prefix, kind, uv, commit, source)


def github_json(path: str, *, timeout: float) -> dict:
    request = Request(
        f"{API}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AnkiLoom updater",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except HTTPError as exc:
        message = (
            "GitHub API rate limit reached; try again later."
            if exc.code == 429
            or (exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0")
            else f"GitHub returned HTTP {exc.code} for {path}."
        )
        raise LoomError(message, "update") from exc
    except (URLError, OSError, ValueError, UnicodeError) as exc:
        raise LoomError(f"Could not check GitHub for updates: {exc}", "update") from exc
    if not isinstance(data, dict):
        raise LoomError("GitHub returned an unexpected update response.", "update")
    return data


def version(value: object) -> Version:
    if not isinstance(value, str):
        raise LoomError(f"Invalid update version: {value!r}", "update")
    try:
        return Version(value)
    except InvalidVersion as exc:
        raise LoomError(f"Invalid update version: {value!r}", "update") from exc


def commit_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value):
        raise LoomError("GitHub returned an invalid commit ID.", "update")
    return value


def resolve_target(*, head: bool, timeout: float) -> Target:
    if head:
        commit_info = github_json("commits/HEAD", timeout=timeout)
        ref = commit_id(commit_info.get("sha"))
        commit = ref
        content = github_json(f"contents/pyproject.toml?ref={quote(ref, safe='')}", timeout=timeout)
        try:
            source = base64.b64decode(content["content"], validate=False).decode("utf-8")
            target_version = tomllib.loads(source)["project"]["version"]
        except (KeyError, ValueError, TypeError, UnicodeError) as exc:
            raise LoomError("Could not read the version at GitHub HEAD.", "update") from exc
    else:
        release = github_json("releases/latest", timeout=timeout)
        ref = release.get("tag_name", "")
        if not isinstance(ref, str) or not ref or release.get("draft") or release.get("prerelease"):
            raise LoomError("GitHub did not return a published stable release.", "update")
        target_version = ref.removeprefix("v")
        parsed = version(target_version)
        if parsed.is_prerelease or parsed.is_devrelease:
            raise LoomError(
                "The latest release has a prerelease version; refusing to select it.", "update"
            )
        commit = github_json(f"commits/{quote(ref, safe='')}", timeout=timeout).get("sha", "")
    commit = commit_id(commit)
    if not isinstance(target_version, str):
        raise LoomError("GitHub returned an invalid package version.", "update")
    version(target_version)
    return Target(target_version, ref, commit, "head" if head else "release")


def validate_installation(installation: Installation) -> str:
    if installation.kind != "uv-tool" or installation.uv is None:
        advice = {
            "editable": "This is an editable checkout. Update it with git pull and uv sync.",
            "pipx": "This installation is managed by pipx. Update it with pipx, or install with uv.",
        }.get(
            installation.kind,
            "This is not a permanent uv tool installation (uvx and project environments are not updated in place).",
        )
        raise LoomError(f"{advice}\nFor a permanent installation: {INSTALL_HELP}", "installation")
    if installation.source and urlparse(installation.source).scheme != "file":
        parsed = urlparse(installation.source)
        if (
            parsed.hostname != "github.com"
            or parsed.path.lower().removesuffix(".git") != "/paperbenni/ankiloom"
        ):
            raise LoomError(
                "This installation comes from another source. Use its original installer to update it.",
                "installation",
            )
    try:
        receipt = tomllib.loads((installation.prefix / "uv-receipt.toml").read_text())
        requirements = receipt["tool"]["requirements"]
        if (
            len(requirements) != 1
            or requirements[0]["name"] != "ankiloom"
            or requirements[0].get("extras")
        ):
            raise LoomError(
                "This uv tool has custom requirements. Use uv directly to preserve them while updating.",
                "installation",
            )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LoomError(
            "Cannot inspect this uv tool's requirements; update it with uv directly.",
            "installation",
        ) from exc
    return installation.uv


def installed_after_update(prefix: Path) -> dict:
    python = prefix / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    result = run_process(
        [
            str(python),
            "-c",
            (
                "import json; from importlib.metadata import distribution; "
                "d = distribution('ankiloom'); "
                "u = json.loads(d.read_text('direct_url.json') or '{}'); "
                "print(json.dumps({'version': d.version, 'commit': u.get('vcs_info', {}).get('commit_id')}))"
            ),
        ],
        timeout=30,
    )
    try:
        installed = json.loads(result.stdout)
        if result.returncode or not isinstance(installed, dict):
            raise ValueError("verification failed")
        return installed
    except ValueError as exc:
        raise LoomError(
            "uv completed, but the updated installation could not be verified. Run ankiloom --version.",
            "update",
        ) from exc


def update_installation(
    *,
    head: bool = False,
    check: bool = False,
    timeout: float = 30,
    progress: ProgressCallback = no_progress,
) -> dict:
    progress(ProgressUpdate("Detecting installation"))
    installation = detect_installation()
    # A check is read-only and works even from a checkout or disposable uvx env.
    uv = validate_installation(installation) if not check else None
    progress(ProgressUpdate("Checking GitHub HEAD" if head else "Checking latest GitHub release"))
    target = resolve_target(head=head, timeout=timeout)
    current_version, target_version = version(installation.version), version(target.version)
    if current_version > target_version:
        status = "ahead"
    elif current_version < target_version or (head and installation.commit != target.commit):
        status = "update_available"
    else:
        status = "up_to_date"
    report = {
        "ok": True,
        "event": "update",
        "status": status,
        "check": check,
        "channel": target.channel,
        "installation": installation.kind,
        "currentVersion": installation.version,
        "targetVersion": target.version,
        "currentCommit": installation.commit,
        "targetCommit": target.commit,
        "ref": target.ref,
    }
    if check or status != "update_available":
        return report
    if uv is None:
        raise LoomError("uv is required to update this installation.", "installation")
    progress(ProgressUpdate(f"Installing {target.version} from GitHub"))
    result = run_process(
        [
            uv,
            "tool",
            "install",
            "--force",
            "--reinstall",
            "--no-progress",
            "--color",
            "never",
            target.source,
        ]
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[-4000:]
        raise LoomError(
            f"uv could not update AnkiLoom (exit {result.returncode}).\n{detail}", "update"
        )
    progress(ProgressUpdate("Verifying installed version"))
    installed = installed_after_update(installation.prefix)
    if (
        version(installed.get("version", "")) != target_version
        or installed.get("commit") != target.commit
    ):
        raise LoomError(
            "The installed version or commit does not match the requested update. Run ankiloom --version and inspect the uv installation.",
            "update",
        )
    report.update(
        status="updated", installedVersion=installed["version"], installedCommit=installed["commit"]
    )
    return report
