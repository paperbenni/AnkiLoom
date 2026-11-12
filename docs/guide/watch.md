# Watch a folder

Keep Anki desktop running with AnkiConnect installed, then:

```sh
ankiloom watch ./cards
```

Watch syncs once at startup and again after your saves settle. It watches
Markdown, local assets and `ankiloom.toml`, using the same exclusions and sync
rules as `sync`. Stop it with **Ctrl+C**. It runs in the foreground; no service
or background process is installed.

To run the released version without installing it:

```sh
uvx --from git+https://github.com/paperbenni/AnkiLoom@v0.7.0 ankiloom watch ./cards
```

If your cards were synced with Yanki, complete the [migration](./migration.md)
once before starting watch. Automatic adoption, forced overwrites and deletion
are deliberately reserved for one-shot `sync` commands.

## What triggers a sync

By default, watch checks for changes once a second and waits half a second
after your last save before syncing. A burst of saves becomes one sync.

Only one sync runs at a time for a card folder. Saving IDs during sync does
not trigger another sync. Hidden files and folders, such as `.ankiloom/` and
`.git/`, are ignored. Edits made while a sync is running are picked up afterward.

Moving a card to another folder updates its deck. Deleting a file or removing
a section **never deletes its Anki note**. Stop watch and use an explicit
`sync --prune` against the complete root if you want to remove missing notes
from Anki.

## Errors and retries

Connection failures and busy sync locks retry after ten seconds, without
requiring another file edit. Keep `.ankiloom/` in place so interrupted
creations can be recovered without duplicate notes.

Invalid Markdown, configuration errors, model mismatches and Anki-side edits
are reported while watch keeps running. They wait for a file change, rather
than retrying on a timer. Fix the input file, or stop watch and use the relevant
one-shot `sync` command. Watch never automatically forces a conflicting update.

Normal sync remains local. Pass `--ankiweb` to request an AnkiWeb sync after
each successful local sync. An AnkiWeb-only edit does not trigger watch;
changes are checked against Anki the next time local files trigger a sync.

## Preview and timing

```sh
ankiloom watch ./cards --dry-run
ankiloom watch ./cards --interval 0.5 --debounce 1 --retry-delay 15
```

A preview continuously compares with Anki but writes no notes, models, media,
journal or source IDs. Timing options are measured in seconds.

See the [generated reference](../reference/cli.md#ankiloom-watch) for all options,
including `--deck`, `--exclude`, `--url` and `--timeout`.

## JSON events

```sh
ankiloom watch ./cards --json
```

Each event is one JSON object on its own line:

```json
{"ok": true, "event": "watching", "root": "/path/to/cards"}
{"ok": true, "event": "sync", "trigger": "initial", "dryRun": false, "changes": [], "summary": {}}
{"ok": false, "event": "error", "trigger": "change", "retryIn": 10, "error": {"code": "connection", "message": "..."}}
{"ok": true, "event": "stopped", "root": "/path/to/cards"}
```

A sync event contains the same report as one-shot sync, plus its `event` and
`trigger` (`initial`, `change` or `retry`). Error events are nonfatal; `retryIn`
is a delay in seconds, or `null` when waiting for a file edit. Ctrl+C emits
`stopped` and exits with code 0. Fatal startup errors use the usual structured
error response and nonzero exit code.
