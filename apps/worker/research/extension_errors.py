"""Typed, public-safe failures raised by deterministic workflow extensions."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import TypeAlias


SafeExtensionDetail: TypeAlias = str | int | float | bool | None


class WorkflowExtensionError(RuntimeError):
    """A deterministic extension failure safe to retain in workflow state.

    Details intentionally accept only scalar primitives.  Callers must retain
    source bytes, provider payloads, paths, and other potentially sensitive
    diagnostics in their own protected observability systems.
    """

    def __init__(
        self,
        *,
        code: str,
        public_message: str,
        retryable: bool = False,
        details: Mapping[str, SafeExtensionDetail] | None = None,
    ) -> None:
        _validate_code(code)
        _validate_public_message(public_message)
        safe_details = _validate_details(details or {})
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable
        self.details = safe_details


def _validate_code(code: str) -> None:
    if not code or not code.isascii() or code != code.upper() or not code.replace("_", "").isalnum():
        raise ValueError("extension error code must be uppercase ASCII words separated by underscores")


def _validate_public_message(public_message: str) -> None:
    if not public_message or len(public_message) > 1_000:
        raise ValueError("extension error public_message must be between 1 and 1000 characters")


def _validate_details(
    details: Mapping[str, SafeExtensionDetail],
) -> dict[str, SafeExtensionDetail]:
    safe: dict[str, SafeExtensionDetail] = {}
    for key, value in details.items():
        if not isinstance(key, str) or not key:
            raise TypeError("extension error detail keys must be non-empty strings")
        if isinstance(value, (str, int, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, float) and isfinite(value):
            safe[key] = value
        else:
            raise TypeError("extension error details must contain only safe primitive values")
    return safe


__all__ = ["SafeExtensionDetail", "WorkflowExtensionError"]
