"""CLI definitions also generate the agent skill and command reference."""

import functools
import json
import sys
from collections import Counter
from pathlib import Path

import click
from filelock import Timeout

from . import __version__
from .cards import MODELS, YANKI_MODELS, scan
from .configuration import client_for, config
from .errors import LoomError, operation_error
from .service import SyncOptions, sync_once
from .watch import watch_folder

EXIT_CODES = {
    "validation": 2,
    "input": 2,
    "config": 2,
    "parse": 2,
    "conflict": 3,
    "preflight": 3,
    "adoption": 3,
    "duplicate": 3,
    "missing": 3,
    "model": 3,
    "connection": 4,
    "anki": 4,
    "state": 3,
}


def emit(value, as_json):
    if as_json:
        click.echo(json.dumps(value, ensure_ascii=False, sort_keys=True))
    elif isinstance(value, dict) and "changes" in value:
        for change in value["changes"]:
            click.secho(
                f"  {change['action']:10} {change['path']} → {change['deck']}",
                fg={"create": "green", "update": "yellow", "adopt": "cyan", "delete": "red"}.get(
                    change["action"]
                ),
            )
        click.echo(
            ("Preview: " if value.get("dryRun") else "")
            + ", ".join(f"{n} {name}" for name, n in value["summary"].items())
        )
    else:
        click.echo(json.dumps(value, indent=2, ensure_ascii=False))


def guarded(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (LoomError, OSError, Timeout) as exc:
            exc = operation_error(exc)
            code = EXIT_CODES.get(exc.code, 1)
            if kwargs.get("as_json"):
                click.echo(
                    json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}})
                )
            else:
                click.secho(f"Error: {exc}", fg="red", err=True)
            raise click.exceptions.Exit(code) from exc

    return wrapper


def skill_text():
    from importlib.resources import files

    text = files("ankiloom").joinpath("SKILL.md").read_text()
    text += "\n## Installed command reference\n\nGenerated from this version's actual CLI definitions.\n"
    return text + command_reference()


def command_reference() -> str:
    """Render the command definitions for both the agent skill and website."""
    text = ""
    context = click.Context(cli, info_name="ankiloom")
    for name, command in [
        ("ankiloom", cli),
        *[(f"ankiloom {n}", c) for n, c in sorted(cli.commands.items())],
    ]:
        ctx = (
            context
            if command is cli
            else click.Context(command, info_name=name.split()[-1], parent=context)
        )
        text += f"\n### `{name}`\n\n```text\n{command.get_help(ctx)}\n```\n"
    return text


def show_skill(ctx, param, value):
    if value and not ctx.resilient_parsing:
        click.echo(skill_text())
        ctx.exit()


@click.group(context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100})
@click.version_option(__version__)
@click.option(
    "--skill",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    callback=show_skill,
    help="Print an LLM skill with live CLI reference, then exit.",
)
def cli():
    """Weave Markdown flashcards into Anki through AnkiConnect.

    One file per note. Use check for offline validation, then sync --dry-run
    to compare with Anki. Notes are never deleted unless you pass --prune.
    """


def root_options(function):
    function = click.option(
        "--exclude", multiple=True, help="Exclude a root-relative glob; repeat as needed."
    )(function)
    function = click.option(
        "--deck", default=None, help="Deck prefix before the folder hierarchy."
    )(function)
    function = click.argument("root", type=click.Path(path_type=Path), default="cards")(function)
    return function


def connection_options(function):
    function = click.option(
        "--timeout",
        type=click.FloatRange(min=0, min_open=True),
        default=15.0,
        show_default=True,
        help="AnkiConnect request timeout in seconds.",
    )(function)
    function = click.option(
        "--url",
        envvar="ANKICONNECT_URL",
        default=None,
        help="AnkiConnect URL (default http://127.0.0.1:8765). Also ANKICONNECT_URL.",
    )(function)
    return function


def json_option(function):
    return click.option(
        "--json", "as_json", is_flag=True, help="Emit a JSON result or structured runtime error."
    )(function)


@cli.command()
@root_options
@json_option
@guarded
def check(root, deck, exclude, as_json):
    """Validate ROOT offline, including note syntax, duplicate IDs and local media.

    ROOT defaults to ./cards. Every visible .md file is treated as a note.
    Optional ROOT/ankiloom.toml supports deck, exclude and url settings.
    """
    root = root.resolve()
    deck, exclude, _ = config(root, deck, exclude)
    cards = scan(root, deck, exclude)
    emit(
        {
            "ok": True,
            "root": str(root),
            "notes": len(cards),
            "kinds": dict(Counter(c.kind for c in cards)),
            "media": len({name for c in cards for name in c.media}),
        },
        as_json,
    )


@cli.command()
@root_options
@connection_options
@click.option(
    "--dry-run",
    is_flag=True,
    help="Read Anki and show the plan without writing files, media, models or notes.",
)
@click.option(
    "--adopt",
    is_flag=True,
    help="Take over existing noteIds with compatible AnkiLoom/Yanki models; preserve review history.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Explicitly overwrite Anki-side edits with Markdown. Does not bypass identity/model errors.",
)
@click.option(
    "--prune",
    is_flag=True,
    help="Delete unchanged, journal-tracked Anki notes absent from this complete ROOT.",
)
@click.option(
    "--ankiweb",
    is_flag=True,
    help="Request AnkiWeb sync after successful local sync (default: local only).",
)
@json_option
@guarded
def sync(root, deck, exclude, url, timeout, dry_run, adopt, force, prune, ankiweb, as_json):
    """Sync ROOT to running Anki. Markdown supplies content; Anki keeps scheduling.

    Start with sync ROOT --adopt --dry-run when migrating from Yanki. Stop
    running Yanki against the same notes after adopting them. ROOT defaults
    to ./cards. Changing the inferred note type is refused.

    --prune requires the complete original ROOT. Excluded files also count
    as absent. Without --prune, missing files never cause deletions.
    """
    result = sync_once(
        SyncOptions(
            root=root,
            deck=deck,
            exclude=exclude,
            url=url,
            timeout=timeout,
            dry_run=dry_run,
            adopt=adopt,
            force=force,
            prune=prune,
            ankiweb=ankiweb,
        )
    )
    emit(result.report, as_json)


def watch_event(event, as_json):
    if as_json:
        click.echo(json.dumps(event, ensure_ascii=False, sort_keys=True))
    elif event["event"] == "sync":
        emit(event, False)
    elif event["event"] == "error":
        click.secho(f"Error: {event['error']['message']}", fg="red", err=True)
        if event["retryIn"] is not None:
            click.echo(
                f"Retrying in {event['retryIn']:g}s; journaled writes will be recovered.", err=True
            )
        else:
            click.echo(
                "Waiting for a file change. Fix the issue, or stop watch to run an explicit sync.",
                err=True,
            )
    elif event["event"] == "watching":
        click.echo(f"Watching {event['root']} (Ctrl+C to stop).")
    else:
        click.echo("Watch stopped.")


@cli.command()
@root_options
@connection_options
@click.option(
    "--interval",
    type=click.FloatRange(min=0, min_open=True),
    default=1.0,
    show_default=True,
    help="Poll file contents every this many seconds.",
)
@click.option(
    "--debounce",
    type=click.FloatRange(min=0),
    default=0.5,
    show_default=True,
    help="Wait this many seconds after changes settle before syncing.",
)
@click.option(
    "--retry-delay",
    type=click.FloatRange(min=0, min_open=True),
    default=10.0,
    show_default=True,
    help="Retry a connection failure or busy lock after this many seconds.",
)
@click.option(
    "--dry-run", is_flag=True, help="Continuously preview changes without writing files or Anki."
)
@click.option(
    "--ankiweb", is_flag=True, help="Request AnkiWeb sync after each successful local sync."
)
@json_option
@guarded
def watch(
    root, deck, exclude, url, timeout, interval, debounce, retry_delay, dry_run, ankiweb, as_json
):
    """Sync ROOT on startup and after files change. ROOT defaults to ./cards.

    Watches cards, local assets and ankiloom.toml, respecting --exclude.
    Saves are debounced; syncs run sequentially under the usual root lock.
    Own noteId/loomId writes and hidden files do not trigger another sync.

    Conflicts and invalid cards are reported, then watch waits for an edit.
    Connection failures and busy locks retry through the journaled sync path.
    Use one-shot sync for --adopt, --force and --prune. Ctrl+C stops cleanly.
    With --json, each event is a separate JSON line (watching/sync/error/stopped).
    """
    options = SyncOptions(
        root=root,
        deck=deck,
        exclude=exclude,
        url=url,
        timeout=timeout,
        dry_run=dry_run,
        ankiweb=ankiweb,
    )
    watch_folder(
        options,
        lambda event: watch_event(event, as_json),
        interval=interval,
        debounce=debounce,
        retry_delay=retry_delay,
    )


@cli.command()
@connection_options
@json_option
@guarded
def doctor(url, timeout, as_json):
    """Check the AnkiConnect connection without modifying Anki."""
    client = client_for(url, timeout)
    client.connect()
    emit(
        {
            "ok": True,
            "url": client.endpoint,
            "decks": client.call("deckNames"),
            "models": client.call("modelNames"),
        },
        as_json,
    )


@cli.command("list")
@connection_options
@json_option
@guarded
def list_notes(url, timeout, as_json):
    """List notes adopted or created by AnkiLoom (read-only)."""
    client = client_for(url, timeout)
    client.connect()
    ids = client.call("findNotes", query="tag:ankiloom::managed")
    notes = client.call("notesInfo", notes=ids) if ids else []
    emit({"ok": True, "notes": notes}, as_json)


@cli.command()
@click.argument("css", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@connection_options
@click.option(
    "--include-yanki",
    is_flag=True,
    help="Also style Yanki note models retained during migration; affects all notes using them.",
)
@click.option("--dry-run", is_flag=True, help="List affected models without writing CSS.")
@json_option
@guarded
def style(css, url, timeout, include_yanki, dry_run, as_json):
    """Replace CSS on all existing AnkiLoom models with CSS file contents.

    Models are global in Anki: every note using an affected model is styled.
    Include .yanki selectors in CSS when styling adopted Yanki models.
    """
    content = css.read_text(encoding="utf-8")
    client = client_for(url, timeout)
    client.connect()
    wanted = set(MODELS.values()) | (set(YANKI_MODELS.values()) if include_yanki else set())
    models = sorted(wanted & set(client.call("modelNames")))
    if not dry_run:
        for name in models:
            client.call("updateModelStyling", model={"name": name, "css": content})
    emit({"ok": True, "dryRun": dry_run, "models": models}, as_json)


def main():
    # Keep invalid-option/usage errors machine readable too.
    try:
        cli(standalone_mode=False)
    except click.ClickException as exc:
        if "--json" in sys.argv[1:]:
            click.echo(
                json.dumps(
                    {"ok": False, "error": {"code": "usage", "message": exc.format_message()}}
                )
            )
        else:
            exc.show()
        sys.exit(exc.exit_code)
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)
    except (KeyboardInterrupt, click.Abort):
        click.echo("Interrupted. Rerun the same sync to recover journaled changes.", err=True)
        sys.exit(130)
