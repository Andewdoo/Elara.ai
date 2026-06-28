class TransientProviderError(RuntimeError):
    """A provider operation may succeed when retried within the task budget."""


class TransientFetchError(RuntimeError):
    """A source fetch may succeed when retried within the task budget."""
