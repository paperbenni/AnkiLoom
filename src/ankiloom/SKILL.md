---
name: ankiloom
description: Author Markdown flashcards in single-note or multi-card files and sync them to Anki with AnkiLoom, including migration from Yanki and conflict recovery.
---

# AnkiLoom

One Markdown file is one Anki note by default. Set `ankiloom: multi` in YAML
frontmatter to put multiple notes in a file. Folders under the card root become
Anki deck levels. Optional YAML frontmatter contains `tags` (a list of strings).
`/` in tags becomes `::`. Preserve `noteId`; the tool writes it. Older cards may
also contain a legacy `loomId`, which sync removes automatically. When copying a
note to make a new one, remove `noteId` from the copy.

## Card syntax

In multi-card files, a top-level `##` heading starts a note and is part of its
prompt. Its section ends at the next `##` or `#` heading; lower headings remain
inside the note. Use the syntax below inside each section. Only ATX headings
count; code, math, quotes and lists do not define section boundaries.

Outside heading sections, `question :: answer` on a paragraph line creates a
basic note. Adjacent quick lines work. Exactly one spaced delimiter must be
outside code, math, emphasis and links. Escape extra delimiters as `\::`.
Quick cards are one physical line; multiline inline formatting in their
paragraph is rejected. Lists, tables and code/HTML blocks do not create cards.
Quick-card strike-through and emphasis are ordinary formatting, not cloze or
typed-answer syntax. A `#` heading returns from a section to prose/quick cards.
Ordinary prose outside sections is ignored. File tags apply to all notes.

Multi-card IDs are hidden comments: `<!-- ankiloom noteId: 123 -->`, on the
quick line or on a separate line inside its heading section. Do not use file-level
noteId/loomId in multi mode. Preserve each comment when moving/reordering notes;
remove it when copying a new note. Never remove multi mode while IDs remain.
After an interrupted creation, rerun before editing content: unchanged content
can recover after a move, while ambiguous matches block sync.

- Basic: prompt, blank line, `---`, blank line, answer.
- Reversed: prompt, two consecutive `---` rules separated by blank lines,
  answer. An optional third rule introduces extra answer-side information.
- Cloze: `~~answer~~` in the prompt; `~~1 answer~~` groups explicit numbers.
  A final emphasis inside a cloze gives a hint: `~~Paris _city_~~`.
  An optional horizontal rule separates back-side information.
- Type answer: prompt followed by a final `_plain answer_`, without a rule.

Code fences do not supply card separators or cloze syntax. Tables, code,
HTML and `$inline$` / `$$display$$` math work. Local Markdown images and
`![[relative/image.png|900]]` wiki embeds are copied to Anki with content-hashed
names. Local audio embeds become Anki sounds. Paths resolve relative to the
note and must remain inside the card root. Remote images stay remote.

## Sync and migration

Use `check ROOT` for offline validation. Use `sync ROOT --dry-run --json` to
inspect the actual Anki plan. Anki desktop with AnkiConnect must be running.
Use `--adopt` for existing compatible Yanki notes: updates preserve note IDs,
models, card IDs and review history. Stop Yanki sync for those notes afterward.
AnkiLoom refuses note type changes rather than silently recreating cards.

Markdown supplies content; Anki supplies scheduling. Anki-side content, tag,
or deck edits detected against the local journal block sync. Copy wanted edits
to Markdown first; `--force` explicitly permits replacing the Anki version.
Do not use force as a generic retry. Ordinary retries recover interrupted writes.

Missing files or removed sections do not delete notes. `--prune` is explicit and uses the complete
original card root; excluded notes also count as missing. An empty root is
refused for pruning. Sync is local unless `--ankiweb` is passed.

Keep `.ankiloom/` local and ignored by Git; it contains the lock and sync
journal. Keep note IDs in version control with the Markdown. On a new machine,
run a preview with `--adopt` to establish a fresh baseline against the same
Anki collection. A successful create with a lost response recovers from the
temporary token in the journal and its Anki tag, so rerun the same command.
Once `noteId` is written, that recovery record and tag are cleared. If the
journal is lost during an unfinished creation, find the
`ankiloom::create::…` tag in Anki and resolve that note manually.

`watch ROOT` syncs immediately, then after file changes settle. It shares the
sync journal and lock, ignores its own metadata writes, and catches changes
made during a sync. Connection failures and busy locks retry; conflicts and
validation errors wait for a file change. Use one-shot sync for adoption,
forced overwrites and pruning; watch does not expose those options.
`watch --dry-run` only previews. Ctrl+C stops watch cleanly with exit code 0.

One-shot JSON is one object on stdout. Watch JSON is newline-delimited events
with `event` equal to `watching`, `sync`, `error` or `stopped`; errors are
nonfatal and can include `retryIn` in seconds (null means waiting for an edit). Exit codes: 0 success, 1 unexpected/general error,
2 input/config/usage/unsupported installation, 3 preflight/conflict/state,
4 AnkiConnect/API error, 5 update failure,
130 interrupted. A failed apply may have completed earlier notes; fix the
reported issue and rerun. Dry runs and checks never write source files or Anki.
Use the generated reference below for the installed version's exact options.


Human output uses Rich help, progress and concise summaries. Global flags go
before the subcommand: `--color auto|always|never`, `--progress` / `--no-progress`,
and `--verbose`. Auto respects NO_COLOR; always overrides it. JSON disables
presentation and progress regardless of global flags. Grouped preflight errors
include all individual problems in `error.details`; verbose human output lists
all affected paths. Generated command references are always plain text.


`update` explicitly installs the latest stable GitHub release; `update --head`
selects the latest default-branch commit. `update --check` is read-only and
works in any installation. Updates delegate to uv only for permanent tool
installs. Editable checkouts, pipx, project/disposable environments, forks and
custom tool requirements get manual instructions rather than being replaced.
No version checks run during other commands. JSON reports old/new versions and
commits. An interrupted update exits 130; check the installed version before
retrying. No update command reads or changes cards or Anki.
