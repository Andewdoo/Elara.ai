from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models.enums import AccessStatus, InputType, RunStatus
from app.models.sources import RunSource, Source, SourceSnapshot
from app.models.user import User
from app.models.verification_run import VerificationRun
from graph.runtime import SqlWorkflowStateWriter
from graph.state import (
    CandidateSource,
    ExtractedSourceRecord,
    ResearchDepth,
    SnapshotRecord,
    VerificationState,
    WorkflowStage,
)


def test_extraction_stage_persists_source_snapshot_and_explicit_access_status():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 6, 29, tzinfo=UTC)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="retrieval-owner",
            email="retrieval@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.EXTRACTING,
            submitted_text="A claim",
            normalized_target={},
            workflow_version="step-9-test",
        )
        db.add(run)
        db.commit()
        run_id, owner_id = run.id, owner.id
    fetched_id, inaccessible_id = uuid4(), uuid4()
    state = VerificationState(
        run_id=run_id,
        user_id=owner_id,
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        candidate_sources=[
            CandidateSource(
                source_ref="source-1",
                url="https://example.test/a",
                canonical_url="https://example.test/a",
                domain="example.test",
                selection_reason="primary objective",
                priority=Decimal("0.8"),
            ),
            CandidateSource(
                source_ref="source-2",
                url="https://example.test/b",
                canonical_url="https://example.test/b",
                domain="example.test",
                selection_reason="counterevidence objective",
                priority=Decimal("0.7"),
            ),
        ],
        snapshots=[
            SnapshotRecord(
                snapshot_id=str(fetched_id),
                source_ref="source-1",
                access_status="FETCHED",
                retrieved_at=now,
                content_hash="abc",
                content_type="text/html",
                snapshot_path="C:/tmp/elara/a.html",
                parser_name="trafilatura",
                parser_version="2.1.0",
                extraction_quality=Decimal("0.9"),
                metadata={
                    "untrusted_evidence": True,
                    "fallback_reason": "static_extraction_failed_for_important_source",
                    "extraction_certainty": 0.9,
                    "extraction": {
                        "fallback_attempted": True,
                        "fallback_reason": "static_extraction_failed_for_important_source",
                        "extraction_certainty": 0.9,
                        "inaccessible_status": None,
                    },
                },
            ),
            SnapshotRecord(
                snapshot_id=str(inaccessible_id),
                source_ref="source-2",
                access_status="BOT_BLOCKED",
                retrieved_at=now,
                failure_reason="source denied automated access",
                parser_name="playwright",
                parser_version="1.52.0",
                metadata={
                    "extraction": {
                        "fallback_attempted": True,
                        "fallback_reason": "static_extraction_failed_for_important_source",
                        "extraction_certainty": None,
                        "inaccessible_status": "BOT_BLOCKED",
                    }
                },
            ),
        ],
        extracted_sources=[
            ExtractedSourceRecord(
                source_ref="source-1",
                snapshot_id=str(fetched_id),
                body="Extracted evidence body",
                title="Evidence title",
            )
        ],
        parser_versions={"trafilatura": "2.1.0", "playwright": "1.52.0"},
    )
    asyncio.run(SqlWorkflowStateWriter(factory).save(stage=WorkflowStage.EXTRACTION, state=state))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Source)) == 0
    state = state.complete(WorkflowStage.EXTRACTION)
    asyncio.run(SqlWorkflowStateWriter(factory).save(stage=WorkflowStage.EXTRACTION, state=state))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Source)) == 2
        snapshots = db.scalars(select(SourceSnapshot).order_by(SourceSnapshot.access_status)).all()
        assert {item.access_status for item in snapshots} == {AccessStatus.FETCHED, AccessStatus.BOT_BLOCKED}
        fetched = next(item for item in snapshots if item.access_status == AccessStatus.FETCHED)
        inaccessible = next(
            item for item in snapshots if item.access_status == AccessStatus.BOT_BLOCKED
        )
        assert fetched.snapshot_metadata["extraction"]["fallback_attempted"] is True
        assert fetched.snapshot_metadata["extraction_certainty"] == 0.9
        assert inaccessible.snapshot_metadata["extraction"]["inaccessible_status"] == "BOT_BLOCKED"
        assert inaccessible.parser_name == "playwright"
        assert inaccessible.parser_version == "1.52.0"
        links = db.scalars(select(RunSource).order_by(RunSource.selected_rank)).all()
        assert links[0].snapshot_id == fetched_id
        assert links[1].inaccessible_reason == "source denied automated access"


def test_changed_snapshot_creates_next_version_and_persists_correction_notice():
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    first_seen = datetime(2026, 7, 1, tzinfo=UTC)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="snapshot-version-owner",
            email="snapshot-version@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        runs = [
            VerificationRun(
                user_id=owner.id,
                input_type=InputType.CLAIM,
                research_depth="STANDARD",
                status=RunStatus.EXTRACTING,
                submitted_text=f"Version {index}",
                normalized_target={},
                workflow_version="step-21b-test",
            )
            for index in (1, 2)
        ]
        db.add_all(runs)
        db.commit()
        owner_id = owner.id
        run_ids = [run.id for run in runs]

    for index, run_id in enumerate(run_ids, start=1):
        snapshot_id = uuid4()
        retrieved_at = first_seen + timedelta(hours=index - 1)
        correction_notices = ["Correction: the reported total is 42."] if index == 2 else []
        state = VerificationState(
            run_id=run_id,
            user_id=owner_id,
            research_depth=ResearchDepth.STANDARD,
            methodology_version="1.0",
            candidate_sources=[
                CandidateSource(
                    source_ref="source-1",
                    url="https://example.test/changing",
                    canonical_url="https://example.test/changing",
                    domain="example.test",
                    selection_reason="changed snapshot test",
                    priority=Decimal("0.8"),
                )
            ],
            snapshots=[
                SnapshotRecord(
                    snapshot_id=str(snapshot_id),
                    source_ref="source-1",
                    access_status="FETCHED",
                    retrieved_at=retrieved_at,
                    content_hash=f"hash-{index}",
                    content_type="text/html",
                    snapshot_path=f"C:/tmp/elara/changing-{index}.html",
                    parser_name="beautifulsoup4",
                    parser_version="4.13.0",
                    extraction_quality=Decimal("0.9"),
                    metadata={"correction_notices": correction_notices},
                )
            ],
            extracted_sources=[
                ExtractedSourceRecord(
                    source_ref="source-1",
                    snapshot_id=str(snapshot_id),
                    body=f"Snapshot body version {index}",
                    correction_notices=correction_notices,
                )
            ],
        ).complete(WorkflowStage.EXTRACTION)
        asyncio.run(SqlWorkflowStateWriter(factory).save(stage=WorkflowStage.EXTRACTION, state=state))

    with factory() as db:
        snapshots = db.scalars(
            select(SourceSnapshot).order_by(SourceSnapshot.version_number)
        ).all()

    assert [snapshot.version_number for snapshot in snapshots] == [1, 2]
    assert [snapshot.content_hash for snapshot in snapshots] == ["hash-1", "hash-2"]
    assert snapshots[0].correction_status is None
    assert snapshots[1].correction_status == "NOTICE_DETECTED"
