# Sync and recovery

## Preview and sync

```sh
ankiloom check ./cards
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

`check` validates cards offline. A dry run compares them with Anki and reports
planned changes. Neither command writes to Markdown or Anki.

Ordinary sync updates a matching AnkiLoom note by its `noteId`, preserving its
note and card IDs and review history. Cards without IDs create new notes. Keep
Anki desktop running and avoid editing the same notes in Anki while a sync is
in progress. Use one sync tool for each set of notes.

Sync is local by default. Add `--ankiweb` to sync AnkiWeb after a successful
local sync.

## Markdown is the source of truth

Sync applies the Markdown card's fields and folder-derived deck, overwriting
direct edits to those values in Anki. Copy any Anki edits you want to keep into
Markdown before syncing. Sync also adds the tags listed in Markdown and keeps
unrelated Anki tags. A checkout can remove tags it previously synced from
Markdown because its local journal records those tags. On a fresh checkout,
an existing Anki tag absent from Markdown is treated as an unrelated tag.

Scheduling and review history stay in Anki. Sync reports IDs that point to
missing notes or incompatible note types. If a note was deleted in Anki,
restore it from a backup or remove its ID from Markdown to deliberately create
a new note.

## Remove notes from Anki

Deleting a file or a section leaves its Anki note alone. To delete notes whose
Markdown cards have been removed, preview first:

```sh
ankiloom sync ./cards --prune --dry-run
ankiloom sync ./cards --prune
```

Use the **complete original card folder**: excluded files also count as missing.
Only notes previously synced from that folder are eligible. Notes changed in
Anki are protected, and an empty card folder is refused.

Copied media is left in Anki even when you remove a card. Use Anki's media
tools to clean up unused files.

## Recover an interrupted sync

A failed sync may have completed some changes. Fix the reported problem, then
rerun the same command. Keep `.ankiloom/` in place so AnkiLoom can recover
unfinished work without creating duplicate notes.

After an interrupted creation, rerun before editing the new card's content.
For multi-card files, unchanged content can be recovered after a move or
reorder; ambiguous matches require you to restore the original content or
location before retrying.

### If the local sync data was lost

If a sync was interrupted, restore `.ankiloom/` from a backup if possible.
Otherwise, check Anki before rerunning: a new note may exist even though its
ID has not reached Markdown yet. Temporary tags beginning with
`ankiloom::create::` can help you find these notes.

For a note you want to keep, restore its numeric `noteId` in the Markdown
frontmatter or its per-card ID comment. Then preview and sync:

```sh
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

See [Tags and IDs](./card-format.md#tags-and-ids)
and [multi-card IDs](./card-format.md#multiple-notes-per-file) for the formats.

## Use another machine

Keep card IDs in version control with your Markdown. Keep `.ankiloom/` local
to each machine for recovery and pruning. AnkiLoom creates a Git ignore file
for it automatically.

Pull the latest Markdown and sync the same Anki collection to the other machine
before running ordinary sync there. The IDs in the pulled files identify the
existing notes.

```sh
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

Wait for any unfinished sync to recover on the original machine before moving
to another one.
