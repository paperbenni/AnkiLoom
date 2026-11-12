# Development

```sh
uv sync --locked
uv run pytest
just check
uv build
```

`just check` runs Ruff lint and formatting checks, followed by Astral's ty
type checker across source and tests. All check tools and the Anki test engine
are locked development dependencies; Anki is not a runtime dependency.

HTTP integration tests exercise AnkiConnect requests, migration, conflicts,
locks, dry runs, pruning and lost responses after create/update/delete, including
Yanki replacement creation and deletion. Yanki compatibility is isolated in
the explicit recreation command; normal sync only supports native models.
Real Anki-engine tests create a temporary collection and verify all four note
models generate and render the expected cards. Tests never use your real profile.

## Sync internals

Markdown tokens determine card boundaries and protect code, math and other
formatting from being interpreted as card syntax. Multi-card notes share a
document source snapshot so one ID write does not invalidate sibling notes.
Generated ID edits are parsed again during preflight to check that card
boundaries, content and neighboring IDs remain intact.

Creation recovery journals a temporary token before calling `addNote` and
includes that token in an `ankiloom::create::…` tag. If the response is lost,
the next sync can recover the note by its tag. The returned numeric ID is
saved in the journal before the tag is removed. Successful sync keeps the
numeric ID as the permanent sync identity in Markdown. Preserve response-loss
tests when changing the order of these writes.

AnkiConnect has no atomic compare-and-swap operation. Changed notes are
rechecked before writes and verified afterward. Mutating requests are never
retried at the HTTP request level; a subsequent sync uses the journal to
recover interrupted operations. A per-root lock prevents concurrent local
AnkiLoom syncs, but cannot exclude edits made in Anki itself.

### Read performance

Preflight batches legacy identity and interrupted-creation lookups using
AnkiConnect's read-only `multi` action, then reads fields and card decks in
bulk. Unchanged notes skip a second read during apply. Reads are chunked for
larger collections.

Recorded on the 44-note development collection, an unchanged sync fell from
223 HTTP requests and about 11.2 seconds to three requests and about 0.4
seconds, excluding CLI startup. Markdown parsing accounted for about 0.08
seconds. These are development measurements, not performance guarantees.

## Watch and update internals

The watcher polls content hashes, so it can detect edits even when file size
and modification time stay the same. After a sync, it ignores only the exact
source text produced by that sync. Taking a fresh folder snapshot at that
point would risk swallowing edits made during the operation.

The updater checks the running environment against `uv tool dir` and the uv
tool receipt before replacing an installation. It resolves a release or HEAD
to an immutable commit, delegates installation to uv, then verifies both the
installed version and commit. HEAD checks compare commits even when versions
match; unknown commit provenance is treated as an available HEAD update.

## Design and references

Python was chosen for [uvx's isolated, Git-installable tools](https://docs.astral.sh/uv/guides/tools/),
[Click's definition-generated help](https://click.palletsprojects.com/en/stable/documentation/),
and [markdown-it-py's CommonMark token parser](https://markdown-it-py.readthedocs.io/en/latest/).
TypeScript would fit the Obsidian ecosystem, but this tool needs no Obsidian
runtime. Go's standalone binaries are attractive, but Python's existing
Markdown and CLI components keep this small and directly runnable through uvx.

Inspired by [Obsidian_to_Anki](https://github.com/ObsidianToAnki/Obsidian_to_Anki)
(reference reviewed at `feb3db2708559bf386412ef6f8be00753faf7775`): persistent
note IDs, AnkiConnect field updates, deck movement and media uploads.
The parser, journal and CLI are original implementations; no plugin code is
copied or vendored. Card syntax and existing-model compatibility follow
[Yanki](https://github.com/kitschpatrol/yanki)
(reference reviewed at `9bde82f7b0e1a9888fb07a303e23050d29641280`).

MIT licensed.

## Documentation

Documentation uses VitePress with local search and is deployed to GitHub Pages.
Install Node.js 22 or newer, then:

```sh
npm ci
just docs
```

`just docs-build` creates the static site in `docs/.vitepress/dist` and fails
on broken internal Markdown links. `npm run docs:preview` serves the built site.

The build first runs `scripts/generate_docs.py`. It shares the CLI reference
renderer with `ankiloom --skill`, so command names, options and help text come
from the same definitions. Generated reference pages and the downloadable skill
are ignored by Git. Edit the guides in `docs/guide/` and the bundled skill in
`src/ankiloom/SKILL.md`.

The Documentation workflow builds pull requests and deploys pushes to `main`.
Only deployment has Pages write permissions. The site uses `/AnkiLoom/` as
its base path, matching the repository's GitHub Pages URL.
