"""Deterministic routing decisions for the verification graph."""

from __future__ import annotations

from typing import Literal

from graph.state import VerificationState


Route = Literal["continue", "stop"]


def stop_requested(state: VerificationState) -> Route:
    """Stop on cancellation or a failure in the most recently attempted node."""
    return "stop" if state.cancelled or state.recoverable_errors else "continue"


def evidence_ready(state: VerificationState) -> Route:
    """Route to classification so it can report missing claims or passages."""
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue"


def synthesis_ready(state: VerificationState) -> Route:
    """Route to synthesis so it can report missing evidence or scores."""
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue"


def citation_audit_ready(state: VerificationState) -> Route:
    """Route to citation audit so it can report a missing report draft."""
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue"


__all__ = [
    "citation_audit_ready",
    "evidence_ready",
    "stop_requested",
    "synthesis_ready",
]
