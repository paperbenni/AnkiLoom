"""CLI definitions also generate the agent skill and command reference."""

import functools
import json
import os
import sys
import tomllib
from collections import Counter
from pathlib import Path

import click
from filelock import FileLock, Timeout

from . import __version__
from .anki import AnkiConnect
from .cards import MODELS, YANKI_MODELS, scan
from .errors import LoomError
from .storage import State
from .sync import apply, plan

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
            if isinstance(exc, Timeout):
                exc = LoomError(
                    "Another sync holds this root's lock. Wait for it to finish and retry.",
                    "conflict",
                )
            elif isinstance(exc, OSError):
                exc = LoomError(f"Filesystem error: {exc}", "input")
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


def config(root, deck, exclude, url=None):
    path = root / "ankiloom.toml"
    values = {}
    if path.exists():
        try:
            values = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise LoomError(f"Invalid {path}: {exc}", "config") from exc
        unknown = set(values) - {"deck", "exclude", "url"}
        if unknown:
            raise LoomError(f"Unknown settings in {path}: {', '.join(sorted(unknown))}", "config")
        if any(not isinstance(values[k], str) for k in ("deck", "url") if k in values):
            raise LoomError(f"deck and url in {path} must be strings.", "config")
        if "exclude" in values and (
            not isinstance(values["exclude"], list)
            or any(not isinstance(p, str) for p in values["exclude"])
        ):
            raise LoomError(f"exclude in {path} must be an array of glob strings.", "config")
    return (
        deck if deck is not None else values.get("deck", ""),
        tuple(values.get("exclude", [])) + exclude,
        url or values.get("url", "http://127.0.0.1:8765"),
    )


def client_for(url, timeout):
    return AnkiConnect(url or "http://127.0.0.1:8765", os.environ.get("ANKICONNECT_KEY"), timeout)


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
    root = root.resolve()
    deck, exclude, url = config(root, deck, exclude, url)
    client = client_for(url, timeout)

    def run():
        cards = scan(root, deck, exclude)
        state = State(root, url)
        entries, removed = plan(cards, client, state, adopt, force, prune)
        changes = [entry.report(root) for entry in entries]
        changes += [
            {
                "path": f"noteId:{r['id']}",
                "action": "delete",
                "noteId": r["id"],
                "deck": ", ".join(r["decks"]),
            }
            for r in removed
        ]
        if not dry_run:
            apply(entries, removed, client, state)
            for change, entry in zip(changes, entries):
                change["noteId"] = entry.card.note_id
            if ankiweb:
                client.call("sync")
        emit(
            {
                "ok": True,
                "dryRun": dry_run,
                "changes": changes,
                "summary": dict(sorted(Counter(c["action"] for c in changes).items())),
            },
            as_json,
        )

    if dry_run:
        run()
    else:
        if not root.is_dir():
            raise LoomError(f"Card root is not a directory: {root}", "input")
        directory = root / ".ankiloom"
        directory.mkdir(exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.exists():
            ignore.write_text("*\n", encoding="utf-8")
        with FileLock(directory / "sync.lock", timeout=0):
            run()


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
