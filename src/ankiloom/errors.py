from filelock import Timeout


class LoomError(Exception):
    """An actionable error that can be shown without a traceback."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def operation_error(exc: LoomError | OSError | Timeout) -> LoomError:
    """Give one-shot sync and watch the same actionable failure messages."""
    if isinstance(exc, Timeout):
        return LoomError(
            "Another sync holds this root's lock. Wait for it to finish and retry.", "conflict"
        )
    if isinstance(exc, OSError):
        return LoomError(f"Filesystem error: {exc}", "input")
    return exc
