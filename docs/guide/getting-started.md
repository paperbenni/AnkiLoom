# Getting started

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).
For syncing, run Anki desktop with [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
installed. You can use any text editor; Obsidian is not required.

Run without a permanent installation:

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.7.0 ankiloom check ./cards
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.7.0 ankiloom sync ./cards --dry-run
```

Or install the command:

```sh
uv tool install git+https://github.com/paperbenni/AnkiLoom@v0.7.0
ankiloom check ./cards
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

Python 3.11 or newer; uv can provision Python. Releases include a wheel and
source archive. This package is distributed from GitHub, **not PyPI**.

Coming from Yanki? Follow the [migration guide](./migration.md) before syncing existing notes.

## Keep syncing as you edit

After your first successful sync, run `ankiloom watch ./cards`. It syncs on
startup and after saves settle. See [Watch a folder](./watch.md) for retries,
conflicts and JSON events.
