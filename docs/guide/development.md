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
locks, dry runs, pruning and lost responses after create/update/delete.
Real Anki-engine tests create a temporary collection and verify all four note
models generate and render the expected cards. Tests never use your real profile.

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
