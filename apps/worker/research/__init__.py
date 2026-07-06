"""Server-only targeted discovery and secure retrieval services."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from research.pipeline import RetrievalPipeline


def __getattr__(name: str) -> Any:
    if name == "RetrievalPipeline":
        from research.pipeline import RetrievalPipeline

        return RetrievalPipeline
    raise AttributeError(name)

__all__ = ["RetrievalPipeline"]
