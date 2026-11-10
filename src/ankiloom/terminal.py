"""Rich presentation stays outside the sync engine and machine-readable output."""

import sys
from types import TracebackType

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text
from rich_click import RichContext

from .errors import format_problems
from .progress import ProgressUpdate


def preferences() -> dict:
    ctx = click.get_current_context(silent=True)
    return (ctx.find_root().obj or {}) if ctx else {}


def console(*, stderr: bool = False) -> Console:
    color = preferences().get("color", "auto")
    return Console(
        file=sys.stderr if stderr else sys.stdout,
        color_system="standard" if color == "always" else (None if color == "never" else "auto"),
        force_terminal=True if color == "always" else None,
        no_color=False if color == "always" else (True if color == "never" else None),
        highlight=False,
        markup=False,
    )


def configure_color(ctx: click.Context, param: click.Parameter, value: str) -> None:
    ctx.ensure_object(dict)["color"] = value
    if value != "auto":
        ctx.color = value == "always"
    if isinstance(ctx, RichContext):
        ctx.console = console()


def render_error(error: dict) -> None:
    message = error["message"]
    if error.get("details"):
        message = format_problems(error["details"], verbose=preferences().get("verbose", False))
    console(stderr=True).print(
        Panel(Text(message), title="Error", border_style="red", expand=False)
    )


def render_result(value: dict) -> None:
    out = console()
    if "changes" in value:
        for change in value["changes"]:
            if change["action"] == "unchanged" and not preferences().get("verbose"):
                continue
            row = Text(f"  {change['action']:10} ")
            row.stylize(
                {"create": "green", "update": "yellow", "adopt": "cyan", "delete": "red"}.get(
                    change["action"], "dim"
                )
            )
            row.append(change["path"])
            row.append(f" → {change['deck']}", style="dim")
            out.print(row)
        summary = value["summary"]
        if set(summary) == {"unchanged"}:
            count = summary["unchanged"]
            message = (
                "1 note is up to date." if count == 1 else f"All {count} notes are up to date."
            )
        elif not summary:
            message = "No notes found."
        else:
            message = ", ".join(f"{n} {name}" for name, n in summary.items())
        out.print(
            Text(("Preview: " if value.get("dryRun") else "✓ ") + message, style="bold green")
        )
    elif value.get("event") == "update":
        current, target = value["currentVersion"], value["targetVersion"]
        channel = "GitHub HEAD" if value["channel"] == "head" else "latest release"
        status = value["status"]
        if status == "updated":
            message = f"✓ Updated AnkiLoom {current} → {value['installedVersion']} ({channel})."
        elif status == "update_available":
            message = f"Update available: {current} → {target} ({channel})."
        elif status == "ahead":
            message = f"AnkiLoom {current} is newer than {channel} ({target}); keeping it."
        else:
            message = f"✓ AnkiLoom {current} is up to date ({channel})."
        out.print(
            Text(message, style="bold green" if status in {"updated", "up_to_date"} else "cyan")
        )
        if value["channel"] == "head":
            old = (value["currentCommit"] or "unknown")[:12]
            new = value["targetCommit"][:12]
            out.print(Text(f"Commit: {old} → {new}", style="dim"))
    elif "kinds" in value:
        kinds = ", ".join(f"{count} {kind}" for kind, count in value["kinds"].items())
        out.print(
            Text(
                f"✓ {value['notes']} notes valid ({kinds}), {value['media']} media files.",
                style="bold green",
            )
        )
    else:
        out.print_json(data=value)


class SyncDisplay:
    def __init__(self, *, as_json: bool = False):
        self.out = console(stderr=True)
        requested = preferences().get("progress")
        self.enabled = not as_json and (requested if requested is not None else sys.stderr.isatty())
        self.live: Progress | None = None
        self.task: TaskID | None = None
        self.phase = ""

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def update(self, update: ProgressUpdate) -> None:
        if not self.enabled:
            return
        # Dumb terminals and explicitly enabled pipe output get readable phases,
        # rather than cursor-control sequences they cannot display.
        if not self.out.is_terminal or self.out.is_dumb_terminal:
            if self.phase != update.phase:
                self.out.print(Text(update.phase + "…", style="cyan"))
            self.phase = update.phase
            return
        if self.live is None:
            self.live = Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("{task.description}", markup=False),
                BarColumn(bar_width=20),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=self.out,
                transient=True,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self.task = self.live.add_task(update.phase, total=update.total)
            self.live.start()
        if self.task is not None:
            changed = self.phase != update.phase
            self.phase = update.phase
            detail = f" · {update.detail}" if update.detail else ""
            if changed:
                self.live.remove_task(self.task)
                self.task = self.live.add_task(
                    update.phase + detail, total=update.total, completed=update.completed
                )
                self.live.refresh()
            else:
                self.live.update(
                    self.task, description=update.phase + detail, completed=update.completed
                )

    def stop(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None
            self.task = None
        self.phase = ""
