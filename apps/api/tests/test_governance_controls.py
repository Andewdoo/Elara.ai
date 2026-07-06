from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import (
    AccessStatus, AtomicClaim, InputType, ReportCitation, ResearchDepth, RunSource,
    RunStatus, Source, SourcePassage, SourceSnapshot, SourceType, User, UserFeedback, VerificationRun,
)
from app.services.governance import GovernanceConflictError, adjudicate_feedback, decide_publication
from app.services.retention import cleanup_orphan_snapshots
from app.services.run_lifecycle import TerminalRunTransitionError, persist_completed_run


class RecordingStorage:
    def __init__(self):
        self.deleted: list[str] = []

    def delete_object(self, *, key: str) -> None:
        self.deleted.append(key)


def _citation_ready_allegation(db, owner):
    now = datetime.now(UTC)
    run = VerificationRun(
        user_id=owner.id, input_type=InputType.CLAIM, research_depth=ResearchDepth.STANDARD,
        status=RunStatus.AUDITING, submitted_text="An allegation", normalized_target={},
        workflow_version="step-24b-test", title="Held report", verdict="Not verified",
        evidence_reviewed_at=now,
    )
    source = Source(canonical_url="https://example.test/evidence", domain="example.test",
                    source_type=SourceType.PRIMARY, first_seen_at=now, last_seen_at=now)
    db.add_all([run, source])
    db.flush()
    snapshot = SourceSnapshot(source_id=source.id, version_number=1, retrieved_at=now,
                              access_status=AccessStatus.FETCHED, content_hash="sha256:held",
                              snapshot_path="source-snapshots/held.html")
    db.add(snapshot)
    db.flush()
    passage = SourcePassage(snapshot_id=snapshot.id, source_id=source.id, text="Evidence",
                            text_hash="sha256:passage", extraction_certainty=Decimal("1.0"))
    claim = AtomicClaim(run_id=run.id, claim_text="An allegation", claim_type="allegation",
                        importance_weight=3, entities=[], locations=[], metrics=[], ambiguities=[])
    db.add_all([passage, claim])
    db.flush()
    db.add_all([
        RunSource(run_id=run.id, source_id=source.id, snapshot_id=snapshot.id, role="primary"),
        ReportCitation(run_id=run.id, atomic_claim_id=claim.id, report_section="summary",
                       sentence_text="Held sentence", passage_id=passage.id, audit_status="passed"),
    ])
    db.commit()
    return run.id, snapshot.id


def test_allegation_is_held_approved_durably_and_cannot_be_retried(session_factory, owner):
    with session_factory() as db:
        run_id, _ = _citation_ready_allegation(db, owner)
        event = persist_completed_run(db, run_id=run_id, expected_citation_count=1)
        assert event.event_type == "publication.review_required"
        held = db.get(VerificationRun, run_id)
        assert held.status == RunStatus.AUDITING and held.publication_state == "review_required"
        with pytest.raises(TerminalRunTransitionError):
            persist_completed_run(db, run_id=run_id, expected_citation_count=1)
        reviewer = User(auth_provider="firebase", auth_subject="reviewer", email="reviewer@example.test",
                        plan_tier="internal", role="reviewer", usage_limits={})
        db.add(reviewer)
        db.commit()
        db.refresh(reviewer)
        approved = decide_publication(db, reviewer=reviewer, run_id=run_id,
                                      decision="approved", rationale="Independent review passed")
        assert approved.status == RunStatus.COMPLETED and approved.publication_state == "approved"


def test_retention_never_deletes_completed_report_snapshot(session_factory, owner):
    storage = RecordingStorage()
    with session_factory() as db:
        run_id, protected_id = _citation_ready_allegation(db, owner)
        run = db.get(VerificationRun, run_id)
        run.status = RunStatus.COMPLETED
        source = Source(canonical_url="https://orphan.test/evidence", domain="orphan.test",
                        source_type=SourceType.PRIMARY, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC))
        db.add(source)
        db.flush()
        orphan = SourceSnapshot(source_id=source.id, version_number=1, retrieved_at=datetime.now(UTC),
                                access_status=AccessStatus.FETCHED, content_hash="sha256:orphan",
                                snapshot_path="source-snapshots/orphan.html",
                                created_at=datetime.now(UTC) - timedelta(days=60))
        db.add(orphan)
        db.commit()
        assert cleanup_orphan_snapshots(db, storage=storage, older_than_days=30) == 1
        assert db.get(SourceSnapshot, protected_id) is not None
        assert storage.deleted == ["source-snapshots/orphan.html"]


def test_correction_decision_history_is_reviewer_only_and_final(session_factory, owner):
    with session_factory() as db:
        run_id, _ = _citation_ready_allegation(db, owner)
        feedback = UserFeedback(run_id=run_id, user_id=owner.id, category="CORRECTION",
                                message="The cited date is wrong", status="open")
        reviewer = User(auth_provider="firebase", auth_subject="appeal-reviewer",
                        email="appeal-reviewer@example.test", plan_tier="internal",
                        role="reviewer", usage_limits={})
        db.add_all([feedback, reviewer])
        db.commit()
        db.refresh(feedback)
        db.refresh(reviewer)
        decision = adjudicate_feedback(db, reviewer=reviewer, feedback_id=feedback.id,
                                       decision="accepted", rationale="Source confirms correction")
        assert decision.public_notice_required is True
        with pytest.raises(GovernanceConflictError):
            adjudicate_feedback(db, reviewer=reviewer, feedback_id=feedback.id,
                                decision="rejected", rationale="Cannot overwrite history")
