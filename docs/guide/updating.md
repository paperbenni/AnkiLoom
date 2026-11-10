# Updating AnkiLoom

If you installed AnkiLoom with `uv tool install`:

```sh
ankiloom update
```

This selects the latest published stable release from
[paperbenni/AnkiLoom](https://github.com/paperbenni/AnkiLoom/releases) and shows
the old and new version. Updating leaves your cards and Anki collection alone.

## Releases and the latest commit

```sh
ankiloom update --check
ankiloom update --head --check
ankiloom update --head
```

The default channel is the **latest stable release**. `--head` selects the latest
commit on GitHub's default branch, including changes that have not been released.
Use it when you want to try unreleased changes.

`--check` shows whether an update is available without installing it.

An up-to-date installation is left alone. An installed package whose version is
newer than the selected channel is kept; update does not silently downgrade it.
Pass `--head` each time you want unreleased changes; ordinary `update` selects a release.

## Update other installation types

`ankiloom update` can replace a standard GitHub installation made with
`uv tool install`. For editable checkouts, pipx, project environments, forks,
or tools installed with custom requirements, it gives manual instructions.
`--check` works in all of these environments.

If you use `uvx`, update the version in your command instead. For a command
available across terminal sessions, install it with:

```sh
uv tool install git+https://github.com/paperbenni/AnkiLoom
```

If your current AnkiLoom is too old to have the update command, bootstrap once:

```sh
uv tool install --force git+https://github.com/paperbenni/AnkiLoom
```

Update a source checkout with `git pull` and `uv sync`. If you installed its CLI
with `just install`, rerun that command after pulling changes. For a pinned
`uvx` command in a script or justfile, change its tag or commit to select a
newer version.

Use `ankiloom update` to advance an installation pinned to an older release.
`uv tool upgrade ankiloom` keeps the source version you originally requested.

## Output and failures

For automation:

```sh
ankiloom update --check --json
```

JSON is a single object containing `status`, `channel`, `installation`,
`currentVersion`, `targetVersion`, `currentCommit`, `targetCommit`, and `ref`.
A successful install also includes `installedVersion` and `installedCommit`.
Statuses are `up_to_date`, `update_available`, `updated`, or `ahead`.

Use `--timeout` to adjust the GitHub request timeout in seconds. A failed
update includes uv's error message. Unsupported installations exit 2;
check/install/verification failures exit 5. Ctrl+C exits 130.
If installation was interrupted, run
`ankiloom --version` to check its state before retrying.

Updates happen only when explicitly requested. Other commands make no background
GitHub version checks and never install updates automatically.
