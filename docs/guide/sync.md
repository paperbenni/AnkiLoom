# Sync and recovery

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

## Read performance

Preflight batches identity lookups with AnkiConnect's read-only `multi` action,
then reads fields and card decks in bulk. Unchanged notes need no second read
during apply. Notes that will be modified are still rechecked immediately
before writing and verified afterward; conflict detection stays active.

On the 44-note development collection, this reduced an unchanged sync from
223 HTTP requests and about 11.2 seconds to four requests and about 0.42 seconds,
excluding CLI startup. Markdown parsing accounted for about 0.08 seconds.
Reads are chunked for larger collections. Mutations remain individually
journaled and are never retried at the HTTP request level.
