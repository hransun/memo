class MemoError(Exception):
    """Expected business failure; the controller maps it to an HTTP response."""

    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
