"""Domain exceptions."""


class RunAbortedError(ValueError):
    """Global run failure whose message is safe and useful to show to API clients.

    Any other exception that aborts a run is logged in full on the worker and surfaced
    only as a generic message, so infrastructure details never reach the run status API.
    """


class IdempotencyConflictError(Exception):
    """Idempotency key already used by another user or for a different request payload."""

    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self) -> None:
        super().__init__(self.code)
