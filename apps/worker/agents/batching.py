"""Deterministic helpers for bounded language-model batches."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar


ItemT = TypeVar("ItemT")


def chunked(items: Sequence[ItemT], batch_size: int) -> list[tuple[ItemT, ...]]:
    """Return ordered, non-empty chunks without mutating the input sequence."""

    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise ValueError("batch_size must be a positive integer")
    return [tuple(items[index : index + batch_size]) for index in range(0, len(items), batch_size)]


__all__ = ["chunked"]
