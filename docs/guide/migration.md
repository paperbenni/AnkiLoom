# Migrate from Yanki

AnkiLoom uses its own note models and bundled styling. Yanki migration **recreates
the referenced notes**, giving them new note/card IDs and resetting their scheduling
and review history. There is one migration path; retaining Yanki models, templates
or CSS is not supported.

Stop syncing these notes with Yanki. Keep Anki desktop open with AnkiConnect,
and keep the existing `noteId` values in your Markdown. Preview the replacements:

```sh
ankiloom check ./cards
ankiloom migrate-yanki ./cards --dry-run
```

If you accept the history reset, apply it explicitly:

```sh
ankiloom migrate-yanki ./cards --reset-history
ankiloom sync ./cards
```

The migration supports Yanki Basic, Reversed with Extra, Cloze and Type Answer.
It checks all inputs before replacing notes. Each native replacement is created
and verified, then its new ID is saved in Markdown **before** the original is
deleted. Markdown supplies the new content and deck; unrelated tags are retained.
The legacy `YankiNamespace` field is discarded. Modified Yanki field schemas are
rejected. Unreferenced notes and notes already using matching AnkiLoom models are
left alone; unused Yanki models are not deleted.

## Recover an interrupted migration

Rerun `migrate-yanki ./cards --reset-history` before editing cards or using ordinary
sync. Keep `.ankiloom/`: its temporary migration journal and recovery tags prevent
duplicate replacements if AnkiConnect loses a response. A failed migration may
already have completed earlier notes. A preview remains read-only during recovery.
Changes to unfinished migration inputs or either Anki note block recovery until
you restore the expected values.

If that journal is lost during migration, inspect Anki for tags beginning with
`ankiloom::migrate::` before retrying. Restore the journal from a backup rather than
discarding an unfinished replacement.

## Already adopted by an older AnkiLoom version?

Run the same migration command. It replaces the retained Yanki notes and updates
the local sync journal. Afterward, ordinary sync uses exactly the same models
and behavior as notes originally created by AnkiLoom.

`sync --adopt` now only establishes a baseline for existing **AnkiLoom** notes,
for example on a new machine. It preserves those notes' IDs and review history;
it does not convert or recreate notes.

Older AnkiLoom versions also wrote a `loomId` field and `ankiloom::id::…` tag.
For native notes, ordinary sync removes these after confirming `noteId`.

See [Card styling](./styling.md) for the bundled theme and custom CSS.
