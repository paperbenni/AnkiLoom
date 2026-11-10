"""Presentation-neutral progress updates from sync operations."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class ProgressUpdate:
    phase: str
    completed: int = 0
    total: int | None = None
    detail: str = ""


def no_progress(update: ProgressUpdate) -> None:
    pass


ProgressCallback = Callable[[ProgressUpdate], None]
