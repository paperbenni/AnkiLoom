# Sync and recovery

## Preview and sync

```sh
ankiloom check ./cards
ankiloom sync ./cards --dry-run
ankiloom sync ./cards
```

`check` validates cards offline. A dry run compares them with Anki and reports
planned changes. Neither command writes to Markdown or Anki.

Ordinary sync creates and updates notes while preserving their IDs and review
history. Keep Anki desktop running and avoid editing the same notes in Anki
while a sync is in progress. Use one sync tool for each set of notes.

Sync is local by default. Add `--ankiweb` to sync AnkiWeb after a successful
local sync.

## Handle edits made in Anki

Changes to note content, tags or decks in Anki can conflict with your Markdown.
Review both versions and copy any wanted changes into Markdown. Then preview
and explicitly allow Markdown to overwrite Anki:

```sh
ankiloom sync ./cards --force --dry-run
ankiloom sync ./cards --force
```

Normal study and scheduling changes do not cause conflicts. If a note was
deleted in Anki, sync reports it as missing. Restore it from an Anki backup,
or remove its ID from Markdown if you deliberately want a new note.

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
location before retrying. Use `--force` only to overwrite edits made in Anki;
it is not needed for an ordinary retry.

### If the local sync data was lost

If a sync was interrupted, restore `.ankiloom/` from a backup if possible.
Otherwise, check Anki before rerunning: a new note may exist even though its
ID has not reached Markdown yet. Temporary tags beginning with
`ankiloom::create::` can help you find these notes.

For a note you want to keep, restore its numeric `noteId` in the Markdown
frontmatter or its per-card ID comment. Then preview and adopt:

```sh
ankiloom sync ./cards --adopt --dry-run
ankiloom sync ./cards --adopt
```

See [Tags and IDs](./card-format.md#tags-and-ids)
and [multi-card IDs](./card-format.md#multiple-notes-per-file) for the formats.

## Use another machine

Keep card IDs in version control with your Markdown. Keep `.ankiloom/` local
to each machine; AnkiLoom creates a Git ignore file for it automatically.

On another machine with the same Anki collection, preview and adopt the notes
to establish that machine's sync history:

```sh
ankiloom sync ./cards --adopt --dry-run
ankiloom sync ./cards --adopt
```

Wait for any unfinished sync to recover on the original machine before moving
to another one.
