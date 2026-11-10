class LoomError(Exception):
    """An actionable error that can be shown without a traceback."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code
