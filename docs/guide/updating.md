# Updating AnkiLoom

For a permanent uv tool installation:

```sh
ankiloom update
```

This selects the latest published stable release from
[paperbenni/AnkiLoom](https://github.com/paperbenni/AnkiLoom/releases), delegates
installation to uv, then verifies the installed package version and Git commit.
The result shows the old and new version. Cards and Anki are not accessed.

## Releases and the latest commit

```sh
ankiloom update --check
ankiloom update --head --check
ankiloom update --head
```

The default channel is the **latest stable release**. `--head` selects the latest
commit on GitHub's default branch, including changes that have not been released.
HEAD updates compare commit IDs even if the package version has not changed.
Both channels install the exact resolved commit, so a branch or tag moving
during installation cannot change the selected target.

`--check` only reports the current and target versions/commits. It does not run
the installer. Unknown commit provenance is treated as an available HEAD update.

An up-to-date installation is left alone. An installed package whose version is
newer than the selected channel is kept; update does not silently downgrade it.
The channel is selected per invocation, rather than being saved in card settings.

## Installation detection

Automatic replacement is supported for a permanent `uv tool install` environment.
AnkiLoom checks the running environment against `uv tool dir` and the tool receipt,
so a command running through `uvx` cannot accidentally update another installation.

Editable checkouts, pipx, ordinary Python/project environments, fork sources and
uv tools with additional/custom requirements get manual instructions. Their
installations are not overwritten. `--check` still works in those environments.

For a permanent installation:

```sh
uv tool install git+https://github.com/paperbenni/AnkiLoom
```

If your current AnkiLoom is too old to have the update command, bootstrap once:

```sh
uv tool install --force git+https://github.com/paperbenni/AnkiLoom
```

A source checkout is updated with `git pull` and `uv sync`. For a pinned `uvx`
command in a script or justfile, change its explicit tag or commit to select a
newer version. Running `update` in a disposable `uvx` environment is refused.

The updater resolves GitHub itself, so future `ankiloom update` invocations can
advance a previously pinned release or commit. A plain `uv tool upgrade ankiloom`
continues to respect whatever source constraint was last installed.

## Output and failures

The normal Rich progress/color controls apply. For automation:

```sh
ankiloom update --check --json
```

JSON is a single object containing `status`, `channel`, `installation`,
`currentVersion`, `targetVersion`, `currentCommit`, `targetCommit`, and `ref`.
A successful install also includes `installedVersion` and `installedCommit`.
Statuses are `up_to_date`, `update_available`, `updated`, or `ahead`.

GitHub requests have a configurable timeout (`--timeout`, in seconds). Installer
output is captured so it cannot corrupt JSON; a failed update includes uv's error
message. Unsupported installations exit 2; check/install/verification failures
exit 5. Ctrl+C exits 130. If installation was interrupted, run
`ankiloom --version` to check its state before retrying.

Updates happen only when explicitly requested. Other commands make no background
GitHub version checks and never install updates automatically.
