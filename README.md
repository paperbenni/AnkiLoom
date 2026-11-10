# AnkiLoom

**Markdown flashcards → Anki. No Obsidian, custom regexes, or background service.**

One Markdown file per note. A horizontal rule separates the question and answer;
folders become decks. Sync through AnkiConnect, preserving existing review history.

**[Documentation](https://paperbenni.xyz/AnkiLoom/)** ·
[Card format](https://paperbenni.xyz/AnkiLoom/guide/card-format.html) ·
[Migrate from Yanki](https://paperbenni.xyz/AnkiLoom/guide/migration.html) ·
[CLI reference](https://paperbenni.xyz/AnkiLoom/reference/cli.html)

```markdown
Frobenius norm

---

Square every entry, sum them, then take the square root.
```

## Run it

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).
Validation works offline:

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.1.0 ankiloom check ./cards
```

Or install the CLI:

```sh
uv tool install git+https://github.com/paperbenni/AnkiLoom@v0.1.0
ankiloom check ./cards
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

Syncing requires Anki desktop with [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
installed. To take over existing Yanki notes, first stop Yanki sync and use
`ankiloom sync ./cards --adopt --dry-run`, then run without `--dry-run`.
See the [migration guide](https://paperbenni.xyz/AnkiLoom/guide/migration.html).

Basic, reversed, cloze and typed-answer notes are supported, along with tags,
math, tables and local image/audio media. Anki-side edits are detected as
conflicts; deletion requires explicit `--prune`. `--json` supports scripts,
and `--skill` exports an agent skill with a live command reference.

## Development

```sh
uv sync --locked
just check
uv run pytest
uv build
```

`just check` runs Ruff lint/format checks and ty. Tests use temporary Anki
collections and never touch your real profile.

For the VitePress docs (Node.js 22 or newer):

```sh
npm ci
just docs
just docs-build
```

The documentation workflow builds pull requests and deploys `main` to GitHub
Pages. CLI reference pages and the downloadable agent skill are generated from
the Python CLI during each build. Edit guides in `docs/guide/`; do not hand-edit
generated reference pages. Python checks do not require Node.js.

Inspired by [Obsidian_to_Anki](https://github.com/ObsidianToAnki/Obsidian_to_Anki),
with card syntax and migration compatibility based on [Yanki](https://github.com/kitschpatrol/yanki).
The implementation is original. See the [design notes](https://paperbenni.xyz/AnkiLoom/guide/development.html#design-and-references).

MIT licensed.
