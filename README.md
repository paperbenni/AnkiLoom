# AnkiLoom

**Markdown flashcards → Anki. No Obsidian, custom regexes, or background service.**

Write one Markdown file per note. Use a horizontal rule between the question
and answer. Folders become decks. Sync from the terminal through AnkiConnect.

```markdown
Frobenius norm

---

Square every entry, sum them, then take the square root.

$$
\|A\|_F = \sqrt{\sum_{i,j} a_{ij}^2}
$$
```

## Run it

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).
For syncing, run Anki desktop with [AnkiConnect](https://ankiweb.net/shared/info/2055492159)
installed. Obsidian is never needed. AnkiLoom does not open or edit Anki's database directly.

Run without a permanent installation:

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.1.0 ankiloom check ./cards
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.1.0 ankiloom sync ./cards --dry-run
```

Or install the command:

```sh
uv tool install git+https://github.com/paperbenni/AnkiLoom@v0.1.0
ankiloom check ./cards
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

Python 3.11 or newer; uv can provision Python. Releases include a wheel and
source archive. This package is distributed from GitHub, **not PyPI**.

## Migrate from Yanki

Keep your Markdown and its existing `noteId` values. First stop syncing those
notes with Yanki, then preview and adopt them:

```sh
ankiloom check ./cards
ankiloom sync ./cards --adopt --dry-run
ankiloom sync ./cards --adopt
```

AnkiLoom updates those exact notes in place, keeping their models, card IDs,
review history and unrelated tags/fields. It supports Yanki Basic, Reversed
with Extra, Cloze and Type Answer models. It refuses a note type change instead
of deleting and recreating cards. New notes use AnkiLoom models.

After adoption, use ordinary `ankiloom sync ./cards`. To keep existing card
styling, no additional step is needed: adopted note templates and CSS stay in
Anki. To apply a CSS file explicitly:

```sh
ankiloom style ./style.css --include-yanki --dry-run
ankiloom style ./style.css --include-yanki
```

Style changes affect **all** notes using the listed models. Rendered content
has both `.ankiloom` and `.yanki` classes so existing Yanki CSS selectors work.

## Card format

Each visible `.md` file below the root is one note. Keep supporting documents
outside that directory or exclude them. Hidden files/directories are ignored.

### Basic

```markdown
Question

---

Answer, with **formatting**, code, math, tables, or images.
```

### Reversed

Two rules between prompt and answer create cards in both directions. A third
rule introduces optional extra information on the answer side of both cards.

```markdown
Oxygen

---

---

O

---

A chemical symbol.
```

### Cloze

Strike-through hides an answer. Each unnumbered cloze creates a separate card;
explicit numbers group clozes and help keep their identities stable as you edit.
An optional final emphasis supplies a hint. Code and math are left alone.

```markdown
~~1 Paris _city_~~ is the capital of ~~2 France~~.

---

Extra information on the answer side.
```

Once studied, preserve cloze numbers. Anki can retain empty cards after clozes
are removed; use Anki's **Tools → Empty Cards** to review those.

### Type answer

Without a horizontal rule, a final emphasis span supplies a plain-text answer.

```markdown
Capital of France?

_Paris_
```

### Tags and IDs

```markdown
---
tags:
  - maths/linear-algebra
  - exam
---

Question

---

Answer
```

Tags use a YAML list; `/` becomes Anki's `::`. Use block-style frontmatter keys
as above, rather than a flow-style `{...}` mapping. Other metadata is preserved.

AnkiLoom writes `loomId` (a retry-safe identity) and `noteId` (Anki's numeric ID).
**Commit these with your cards.** Filenames can change without creating new notes.
When copying a file to make a different note, remove **both** IDs from the copy.
Duplicate IDs fail validation rather than silently targeting the same note.

Folders below the supplied root become deck levels: `cards/maths/algebra/x.md`
becomes `maths::algebra`. A file directly under the root uses the root's name.
`--deck University` adds a prefix: `University::maths::algebra`.

### Rendering and media

Supported: CommonMark, HTML, pipe tables, fenced code, inline `$x$`, display
`$$...$$` math, and local image/audio embeds. Math uses Anki's MathJax renderer.
AnkiLoom preserves normal Markdown paragraph and line-break behavior.

```markdown
![Diagram](assets/diagram.png)
![[assets/diagram.png|900]]
![[assets/diagram.png|900x600]]
![Pronunciation](assets/audio.mp3)
```

Media paths resolve relative to the card file and must stay inside the card
root. Local files are copied to Anki using content-hashed names: identical
assets deduplicate and changed content gets a new name. Missing media fails
validation. Remote image URLs remain remote and are never downloaded.

This is a focused format, not an Obsidian renderer. Wiki note links/transclusions,
PDF embeds, Mermaid rendering, syntax highlighting, task-list checkboxes,
highlights, video embeds and local media inside raw HTML are not processed.
Use Markdown images or wiki image embeds for managed media. There is no
user-supplied regex format or plugin system.

## Predictable sync

- `check` works offline and never writes files.
- `sync --dry-run` compares with Anki but writes nothing: no IDs, journal,
  notes, models, decks or media. It reports planned creates, updates, adoptions
  and deletions. JSON also identifies changed fields and tag differences.
- Ordinary sync creates and updates notes. Missing files **never** delete notes.
- `--prune` explicitly deletes unchanged journal-tracked notes absent from the
  **complete original root**. Excluded files count as absent too. Pruning an
  empty root is refused; unrelated Anki notes are never candidates.
- Anki-side content, deck, tag or card-identity changes block a later sync.
  Copy wanted changes into Markdown, then explicitly use `--force` to allow
  overwriting the Anki version. Scheduling/review changes do not cause conflicts.
- All input is validated and preflighted before applying note changes. Runtime
  failures can still leave a partially applied sync. Fix the error and rerun
  the same command: each note is journaled, and interrupted writes are recovered.
- A per-root lock prevents concurrent AnkiLoom syncs. AnkiConnect has no atomic
  compare-and-swap operation: avoid editing notes in Anki during sync.
- AnkiWeb sync is off by default. Pass `--ankiweb` to request it after local sync.

The local journal lives at `ROOT/.ankiloom/state.json`. It includes its own
`.gitignore`; keep it local to each machine. Do not use multiple
sync tools on the same notes. On a new machine, preview with `--adopt` to
establish a fresh baseline for the same Anki collection. A missing Anki note
is reported rather than silently recreated.

For fewer writes, unchanged notes skip note/media mutations. AnkiLoom copies
media but never garbage-collects it; Anki's media tools handle that separately.
There is no two-way merge or automatic conflict resolution.

## CLI and agents

```sh
ankiloom --help
ankiloom sync --help
ankiloom doctor --json
ankiloom list --json
ankiloom --skill
```

Help is generated by Click directly from command definitions. `--skill` prints
a bundled LLM skill **plus a freshly generated reference for every installed
command**, so the option documentation comes from the running version.
Use `ankiloom --skill > SKILL.md` to export it for an agent.

Commands with `--json` emit one JSON object to stdout, including runtime errors.
Successful responses include `ok: true`; failures include `ok: false` and
`error: {code, message}`. Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Success, including a dry run with planned changes |
| 1 | General/unexpected error |
| 2 | Input, validation, configuration or CLI usage error |
| 3 | Preflight, conflict, identity, model or journal error |
| 4 | AnkiConnect connection or API error |
| 130 | Interrupted |

Set the endpoint with `--url` or `ANKICONNECT_URL`. Authentication uses
`ANKICONNECT_KEY`; keys are not CLI arguments or journal contents.
`--timeout` controls request timeout in seconds. Mutating requests are never
retried automatically; identity and journal checks govern a subsequent invocation.

Optional `ROOT/ankiloom.toml` configures just three settings:

```toml
deck = "University"
exclude = ["README.md", "drafts/**"]
url = "http://127.0.0.1:8765"
```

CLI values override deck/url; `--exclude` adds patterns. Unknown settings fail
with an error. Connection-only commands (`doctor`, `list`, `style`) have no
root and use `--url` / `ANKICONNECT_URL` directly.

## Development

```sh
uv sync --locked
uv run pytest
uv run --with anki pytest tests/test_real_anki.py
uv run ruff check src tests
uv run ruff format --check src tests
uv build
```

HTTP integration tests exercise AnkiConnect requests, migration, conflicts,
locks, dry runs, pruning and lost responses after create/update/delete. Optional
real Anki-engine tests create a temporary collection and verify all four note
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
