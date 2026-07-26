"""Fail-closed governance transitions backed by immutable durable records."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentEvent, GovernanceDecision, ReportCitation, ReportShare, RunStatus, User, UserFeedback, VerificationRun
from app.models.types import utc_now
from app.services.run_lifecycle import COMPLETION_CITATION_AUDIT_STATUSES, _next_sequence
from app.services.verifications import get_owned_run


class GovernanceConflictError(ValueError):
    pass


def _require_reviewer(reviewer: User) -> None:
    if reviewer.role not in {"reviewer", "admin"}:
        raise PermissionError("Reviewer authority is required")


def decide_publication(db: Session, *, reviewer: User, run_id: UUID, decision: str, rationale: str) -> VerificationRun:
    _require_reviewer(reviewer)
    run = db.scalar(select(VerificationRun).where(VerificationRun.id == run_id).with_for_update())
    if run is None:
        raise LookupError("Verification run not found")
    if run.publication_state != "review_required":
        raise GovernanceConflictError("Run is not awaiting publication review")
    if decision not in {"approved", "rejected", "revision_required"}:
        raise GovernanceConflictError("Unsupported publication decision")
    now = utc_now()
    run.publication_state = decision
    run.publication_reviewed_by = reviewer.id
    run.publication_reviewed_at = now
    run.publication_review_reason = rationale.strip()
    if decision == "approved":
        citations = db.scalars(select(ReportCitation).where(ReportCitation.run_id == run.id)).all()
        if not citations or any(
            row.audit_status not in COMPLETION_CITATION_AUDIT_STATUSES for row in citations
        ):
            raise GovernanceConflictError("Publication approval requires a passing durable citation audit")
        run.status = RunStatus.COMPLETED
        run.completed_at = now
        event_type, message = "run.completed", "Verification completed after stronger review approval."
    else:
        event_type, message = f"publication.{decision}", "Publication remains held pending governance resolution."
    run.updated_at = now
    db.add(AgentEvent(run_id=run.id, sequence=_next_sequence(db, run.id), stage=run.status,
                      event_type=event_type, public_message=message, payload={}, created_at=now))
    db.commit()
    db.refresh(run)
    return run


def share_report(db: Session, *, owner_id: UUID, run_id: UUID, recipient_id: UUID, scope: str, expires_in_hours: int) -> ReportShare:
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    if run.status != RunStatus.COMPLETED or run.publication_state not in {"published", "approved", "unreviewed"}:
        raise GovernanceConflictError("Only publishable completed reports can be shared")
    if recipient_id == owner_id:
        raise GovernanceConflictError("Owners do not need a share grant")
    if scope not in {"report", "report_sources", "report_sources_exports"}:
        raise GovernanceConflictError("Unsupported share scope")
    if not 1 <= expires_in_hours <= 168:
        raise GovernanceConflictError("Share expiry must be between 1 and 168 hours")
    if db.get(User, recipient_id) is None:
        raise LookupError("Recipient not found")
    row = db.scalar(select(ReportShare).where(ReportShare.run_id == run.id, ReportShare.recipient_user_id == recipient_id))
    now = utc_now()
    if row is None:
        row = ReportShare(run_id=run.id, recipient_user_id=recipient_id, scope=scope,
                          expires_at=now + timedelta(hours=expires_in_hours), created_at=now)
        db.add(row)
    else:
        row.scope, row.expires_at, row.revoked_at = scope, now + timedelta(hours=expires_in_hours), None
    db.commit()
    db.refresh(row)
    return row


def revoke_share(db: Session, *, owner_id: UUID, run_id: UUID, share_id: UUID) -> None:
    run = get_owned_run(db, owner_id=owner_id, run_id=run_id)
    row = db.scalar(select(ReportShare).where(ReportShare.id == share_id, ReportShare.run_id == run.id))
    if row is None:
        raise LookupError("Share not found")
    row.revoked_at = row.revoked_at or utc_now()
    db.commit()


def adjudicate_feedback(db: Session, *, reviewer: User, feedback_id: UUID, decision: str, rationale: str, revised_run_id: UUID | None = None) -> GovernanceDecision:
    _require_reviewer(reviewer)
    feedback = db.scalar(select(UserFeedback).where(UserFeedback.id == feedback_id).with_for_update())
    if feedback is None:
        raise LookupError("Feedback not found")
    allowed = {"accepted", "rejected", "needs_information", "escalated"}
    if feedback.category not in {"CORRECTION", "APPEAL"} or decision not in allowed:
        raise GovernanceConflictError("Unsupported adjudication transition")
    if feedback.status not in {"open", "needs_information", "escalated"}:
        raise GovernanceConflictError("Feedback is already finally adjudicated")
    prior = feedback.status
    feedback.status = decision
    row = GovernanceDecision(feedback_id=feedback.id, reviewer_id=reviewer.id, prior_status=prior,
                             decision=decision, rationale=rationale.strip(), revised_run_id=revised_run_id,
                             public_notice_required=decision == "accepted", created_at=utc_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


__all__ = ["GovernanceConflictError", "adjudicate_feedback", "decide_publication", "revoke_share", "share_report"]
