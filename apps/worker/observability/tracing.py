"""Content-free LangSmith-compatible traces for worker and DeepSeek operations."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator


logger = logging.getLogger(__name__)
_ALLOWED_METADATA = {
    "environment",
    "model",
    "operation",
    "prompt_version",
    "provider",
    "research_depth",
    "retry_count",
    "run_id",
    "stage",
    "workflow_version",
}
_ALLOWED_OUTPUTS = {
    "cancelled",
    "completed_stage_count",
    "recoverable_error_count",
}


@dataclass(slots=True)
class SafeTrace:
    run_tree: Any = None

    def add_outputs(self, values: dict[str, int | float | str | bool | None]) -> None:
        if self.run_tree is not None:
            self.run_tree.add_outputs(
                {key: value for key, value in values.items() if key in _ALLOWED_OUTPUTS}
            )


def _metadata(values: dict[str, object]) -> dict[str, int | float | str | bool | None]:
    return {
        key: value
        for key, value in values.items()
        if key in _ALLOWED_METADATA and isinstance(value, (str, int, float, bool, type(None)))
    }


@contextmanager
def safe_trace(
    name: str,
    *,
    run_type: str = "chain",
    metadata: dict[str, object] | None = None,
) -> Iterator[SafeTrace]:
    """Trace aggregate metadata only; never serialize function inputs or outputs."""
    try:
        from langsmith import trace
    except ImportError:
        yield SafeTrace()
        return
    manager = trace(
        name,
        run_type=run_type,
        inputs={"content_recorded": False},
        metadata=_metadata(metadata or {}),
        tags=["elara", "privacy-safe"],
    )
    try:
        run_tree = manager.__enter__()
    except Exception:
        logger.warning("LangSmith-compatible trace setup failed", exc_info=False)
        yield SafeTrace()
        return
    try:
        yield SafeTrace(run_tree)
    except BaseException:
        # Do not let exception messages derived from retrieved content or user
        # input cross the tracing boundary. The original exception still
        # propagates locally with its full traceback.
        safe_error = RuntimeError("traced operation failed")
        try:
            manager.__exit__(RuntimeError, safe_error, None)
        except Exception:
            logger.warning("LangSmith-compatible trace delivery failed", exc_info=False)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            logger.warning("LangSmith-compatible trace delivery failed", exc_info=False)


__all__ = ["SafeTrace", "safe_trace"]
