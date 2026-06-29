from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
from graph.state import CandidateSource, ExtractedSourceRecord, ResearchDepth, SnapshotRecord, VerificationState, WorkflowStage


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
                metadata={"untrusted_evidence": True},
            ),
            SnapshotRecord(
                snapshot_id=str(inaccessible_id),
                source_ref="source-2",
                access_status="BOT_BLOCKED",
                retrieved_at=now,
                failure_reason="source denied automated access",
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
        parser_versions={"trafilatura": "2.1.0"},
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
        links = db.scalars(select(RunSource).order_by(RunSource.selected_rank)).all()
        assert links[0].snapshot_id == fetched_id
        assert links[1].inaccessible_reason == "source denied automated access"
