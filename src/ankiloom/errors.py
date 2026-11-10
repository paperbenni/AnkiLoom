from os.path import commonpath
from pathlib import Path

from filelock import Timeout


class LoomError(Exception):
    """An actionable error that can be shown without a traceback."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict:
        payload = {"code": self.code, "message": str(self)}
        if isinstance(self, PreflightError):
            payload["details"] = self.details
        return payload


def operation_error(exc: LoomError | OSError | Timeout) -> LoomError:
    """Give one-shot sync and watch the same actionable failure messages."""
    if isinstance(exc, Timeout):
        return LoomError(
            "Another sync holds this root's lock. Wait for it to finish and retry.", "conflict"
        )
    if isinstance(exc, OSError):
        return LoomError(f"Filesystem error: {exc}", "input")
    return exc


def format_problems(problems: list[dict], *, verbose: bool = False) -> str:
    """Explain each distinct failure once, keeping every affected file in JSON."""
    groups: dict[tuple[str, str], list[str]] = {}
    for problem in problems:
        key = (problem["code"], problem["message"])
        groups.setdefault(key, []).append(problem["path"])
    lines = [
        f"Sync blocked: {len(problems)} affected {'note' if len(problems) == 1 else 'notes'}.\n"
    ]
    for (_, message), paths in groups.items():
        lines.append(f"{len(paths)} {'note' if len(paths) == 1 else 'notes'}: {message}")
        shown = paths if verbose else paths[:3]
        if all(Path(path).is_absolute() for path in paths):
            root = Path(commonpath([str(Path(path).parent) for path in paths]))
            lines.append(f"  In {root}:")
            lines.extend(f"    {Path(path).relative_to(root)}" for path in shown)
        else:
            lines.extend(f"  {path}" for path in shown)
        if len(shown) < len(paths):
            lines.append(f"  … and {len(paths) - len(shown)} more (use --verbose to list all).")
    return "\n".join(lines)


class PreflightError(LoomError):
    def __init__(self, problems: list[dict]):
        super().__init__(format_problems(problems), "preflight")
        self.details = problems
