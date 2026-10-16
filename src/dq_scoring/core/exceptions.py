"""Domain exceptions."""


class RunAbortedError(ValueError):
    """Global run failure whose message is safe and useful to show to API clients.

    Any other exception that aborts a run is logged in full on the worker and surfaced
    only as a generic message, so infrastructure details never reach the run status API.
    """
