"""Deterministic routing decisions for the verification graph."""

from __future__ import annotations

from typing import Literal

from graph.state import VerificationState


Route = Literal["continue", "stop"]


def stop_requested(state: VerificationState) -> Route:
    """Stop on cancellation or a failure in the most recently attempted node."""
    return "stop" if state.cancelled or state.recoverable_errors else "continue"


def evidence_ready(state: VerificationState) -> Route:
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue" if state.claims and state.passages else "stop"


def synthesis_ready(state: VerificationState) -> Route:
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue" if state.evidence and state.scores is not None else "stop"


def citation_audit_ready(state: VerificationState) -> Route:
    if state.cancelled or state.recoverable_errors:
        return "stop"
    return "continue" if state.report_draft is not None else "stop"


__all__ = [
    "citation_audit_ready",
    "evidence_ready",
    "stop_requested",
    "synthesis_ready",
]
