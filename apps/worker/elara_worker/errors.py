from collections.abc import Mapping


class TransientProviderError(RuntimeError):
    """A provider operation may succeed when retried within the task budget."""


class TransientFetchError(RuntimeError):
    """A source fetch may succeed when retried within the task budget."""


# These failures are deterministic after the bounded model repair policy has run.
# Keep the codes here rather than relying solely on a workflow caller to set
# ``retryable=False``: a contract failure must never re-enter the Celery provider
# retry budget.
DETERMINISTIC_CONTRACT_ERROR_CODES = frozenset(
    {
        "AGENT_CONTRACT_REPAIR_EXHAUSTED",
        "STRUCTURED_RESPONSE_INVALID",
        # Historical runs used the coarse code below for both body parsing and
        # schema-contract failures. Keep it deterministic for durable replay.
        "STRUCTURED_RESPONSE_REPAIR_EXHAUSTED",
        "STRUCTURED_SCHEMA_REPAIR_EXHAUSTED",
    }
)


def is_retryable_workflow_error(
    *, code: str, retryable: bool, details: Mapping[str, object]
) -> bool:
    """Return whether a workflow result may enter Celery's transient retry path.

    Structured-response codes can be the top-level workflow code or retained as
    redacted provider metadata under ``error_code``.  Neither form is retryable.
    """
    if code in DETERMINISTIC_CONTRACT_ERROR_CODES:
        return False
    error_code = details.get("error_code")
    if isinstance(error_code, str) and error_code in DETERMINISTIC_CONTRACT_ERROR_CODES:
        return False
    if (
        error_code == "PROVIDER_BODY_PARSE_EXHAUSTED"
        and details.get("local_recovery_exhausted") is True
    ):
        return False
    return retryable
