from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import asyncio
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import InformationCluster, InputType, RunStatus, SourceDependency, User, VerificationRun
from graph.runtime import SqlWorkflowStateWriter
from graph.state import (
    CandidateSource,
    ExtractedSourceRecord,
    ResearchDepth,
    SnapshotRecord,
    VerificationState,
    WorkflowStage,
)
from provenance.dependencies import SourceDependencyAnalyzer
from provenance.graph_export import export_source_graph


def _state() -> VerificationState:
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    original_body = (
        'The filing states "Quarterly ridership reached a record after service resumed across the city." '
        "The table reports 1,250 trips and a 42% increase.\n\n"
        "Correction: the source table incorrectly labeled fiscal 2024 as fiscal 2023."
    )
    copy_body = original_body
    analysis_body = (
        "Our independent seasonal analysis uses the Original filing dataset. Ridership was 1,250 trips, "
        "a 42% increase, but weather explains part of the movement."
    )
    documents = [
        ExtractedSourceRecord(
            source_ref="original",
            snapshot_id=str(uuid4()),
            body=original_body,
            title="Original filing",
            published_at=now,
            quotes=["Quarterly ridership reached a record after service resumed across the city."],
            tables=["Ridership | 1,250 | 42%"],
        ),
        ExtractedSourceRecord(
            source_ref="copy",
            snapshot_id=str(uuid4()),
            body=copy_body,
            title="Wire copy",
            published_at=now + timedelta(hours=1),
            quotes=["Quarterly ridership reached a record after service resumed across the city."],
            tables=["Ridership | 1,250 | 42%"],
            outbound_links=["https://records.example/filing"],
        ),
        ExtractedSourceRecord(
            source_ref="analysis",
            snapshot_id=str(uuid4()),
            body=analysis_body,
            title="Independent analysis",
            published_at=now + timedelta(hours=2),
        ),
        ExtractedSourceRecord(
            source_ref="independent",
            snapshot_id=str(uuid4()),
            body="A separately collected survey found a different pattern with no shared records.",
            title="Independent survey",
            published_at=now + timedelta(hours=3),
            outbound_links=["https://records.example/filing"],
        ),
    ]
    candidates = [
        CandidateSource(
            source_ref=document.source_ref,
            url=("https://records.example/filing" if document.source_ref == "original" else f"https://{document.source_ref}.example/story"),
            canonical_url=("https://records.example/filing" if document.source_ref == "original" else f"https://{document.source_ref}.example/story"),
            domain=f"{document.source_ref}.example",
            title=document.title,
            source_type="INDEPENDENT_ANALYSIS" if document.source_ref == "analysis" else "UNKNOWN",
            selection_reason="test",
        )
        for document in documents
    ]
    snapshots = [
        SnapshotRecord(
            snapshot_id=document.snapshot_id,
            source_ref=document.source_ref,
            access_status="FETCHED",
            retrieved_at=now + timedelta(hours=4),
            published_at=document.published_at,
            content_hash="same-hash" if document.source_ref in {"original", "copy"} else f"hash-{document.source_ref}",
        )
        for document in documents
    ]
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        candidate_sources=candidates,
        snapshots=snapshots,
        extracted_sources=documents,
    )


def test_detects_dependency_signals_clusters_and_methodology_multipliers():
    result = SourceDependencyAnalyzer().analyze(_state())
    relationships = {
        (edge.parent_source_ref, edge.child_source_ref, edge.relationship)
        for edge in result.dependencies
    }

    assert ("original", "copy", "CITES") in relationships
    assert ("original", "copy", "REPUBLISHES") in relationships
    assert ("original", "copy", "QUOTES") in relationships
    assert ("original", "copy", "USES_SAME_DATA") in relationships
    assert ("original", "copy", "DERIVES_FROM") in relationships
    assert ("original", "analysis", "USES_SAME_DATA") in relationships
    assert any(
        edge.parent_source_ref == "original"
        and edge.child_source_ref == "analysis"
        and edge.relationship == "CITES"
        and edge.detection_method == "explicit_named_source"
        for edge in result.dependencies
    )
    assert result.source_dependency_multipliers == {
        "original": Decimal("1.00"),
        "copy": Decimal("0.00"),
        "analysis": Decimal("0.35"),
        "independent": Decimal("1.00"),
    }
    main_cluster = next(cluster for cluster in result.information_clusters if "copy" in cluster.source_refs)
    assert main_cluster.representative_source_ref == "original"
    assert main_cluster.source_refs == ["analysis", "copy", "original"]
    assert any(cluster.source_refs == ["independent"] for cluster in result.information_clusters)
    citation_only = next(
        edge
        for edge in result.dependencies
        if edge.parent_source_ref == "original"
        and edge.child_source_ref == "independent"
        and edge.relationship == "CITES"
    )
    assert citation_only.information_cluster_ref is None


def test_graph_export_is_react_flow_compatible_and_contains_detection_metadata():
    graph = export_source_graph(SourceDependencyAnalyzer().analyze(_state()))

    assert all({"id", "type", "data", "position"} <= node.keys() for node in graph["nodes"])
    assert all(
        isinstance(node["data"]["dependencyMultiplier"], float)
        for node in graph["nodes"]
        if node["type"] == "source"
    )
    dependency_edges = [edge for edge in graph["edges"] if edge["id"].startswith("dependency:")]
    assert dependency_edges
    assert all("detectionMethod" in edge["data"] for edge in dependency_edges)
    assert any(edge["data"]["relationship"] == "REPUBLISHES" for edge in dependency_edges)


def test_fuzzy_shared_features_are_detected_without_treating_dates_as_shared_data():
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    documents = [
        ExtractedSourceRecord(
            source_ref="first",
            snapshot_id=str(uuid4()),
            body="In 2026 section 1 was reviewed. Correction: the north row was incorrectly labeled south.",
            published_at=now,
            quotes=["Quarterly ridership reached a record after service resumed across the city."],
            tables=["Metric | Value\nRidership | 1,250"],
        ),
        ExtractedSourceRecord(
            source_ref="second",
            snapshot_id=str(uuid4()),
            body="In 2026 section 1 was updated. Corrected: the north row had been incorrectly labelled south.",
            published_at=now + timedelta(hours=1),
            quotes=["Quarterly ridership reached a record after service resumed across the city!"],
            tables=["Metric, Value; Ridership, 1,250"],
        ),
    ]
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        candidate_sources=[
            CandidateSource(
                source_ref=document.source_ref,
                url=f"https://{document.source_ref}.example/story",
                domain=f"{document.source_ref}.example",
                selection_reason="test",
            )
            for document in documents
        ],
        snapshots=[
            SnapshotRecord(
                snapshot_id=document.snapshot_id,
                source_ref=document.source_ref,
                access_status="FETCHED",
                retrieved_at=now + timedelta(hours=2),
                published_at=document.published_at,
                content_hash=f"hash-{document.source_ref}",
            )
            for document in documents
        ],
        extracted_sources=documents,
    )

    result = SourceDependencyAnalyzer().analyze(state)
    relationships = {edge.relationship for edge in result.dependencies}

    assert {"POSSIBLE_DUPLICATE", "QUOTES", "USES_SAME_DATA", "DERIVES_FROM"} <= relationships


def test_common_years_and_small_section_numbers_do_not_create_data_dependency():
    now = datetime(2026, 6, 30, 12, tzinfo=UTC)
    documents = [
        ExtractedSourceRecord(
            source_ref="alpha",
            snapshot_id=str(uuid4()),
            body="In 2026, section 1 describes the alpha policy and its legal history.",
            published_at=now,
        ),
        ExtractedSourceRecord(
            source_ref="beta",
            snapshot_id=str(uuid4()),
            body="In 2026, section 1 describes an unrelated beta engineering process.",
            published_at=now + timedelta(hours=1),
        ),
    ]
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        candidate_sources=[
            CandidateSource(
                source_ref=document.source_ref,
                url=f"https://{document.source_ref}.example/story",
                domain=f"{document.source_ref}.example",
                selection_reason="test",
            )
            for document in documents
        ],
        snapshots=[
            SnapshotRecord(
                snapshot_id=document.snapshot_id,
                source_ref=document.source_ref,
                access_status="FETCHED",
                retrieved_at=now + timedelta(hours=2),
                published_at=document.published_at,
                content_hash=f"hash-{document.source_ref}",
            )
            for document in documents
        ],
        extracted_sources=documents,
    )

    result = SourceDependencyAnalyzer().analyze(state)

    assert all(edge.relationship != "USES_SAME_DATA" for edge in result.dependencies)


def test_provenance_clusters_and_edges_are_persisted_idempotently():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="provenance-owner",
            email="provenance@example.test",
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
            status=RunStatus.ANALYZING_PROVENANCE,
            submitted_text="A provenance claim",
            normalized_target={},
            workflow_version="step-11-test",
        )
        db.add(run)
        db.commit()
        run_id, owner_id = run.id, owner.id

    value = _state().model_copy(update={"run_id": run_id, "user_id": owner_id})
    writer = SqlWorkflowStateWriter(factory)
    asyncio.run(writer.save(stage=WorkflowStage.EXTRACTION, state=value.complete(WorkflowStage.EXTRACTION)))
    analyzed = SourceDependencyAnalyzer().analyze(value).complete(WorkflowStage.PROVENANCE)
    asyncio.run(writer.save(stage=WorkflowStage.PROVENANCE, state=analyzed))
    asyncio.run(writer.save(stage=WorkflowStage.PROVENANCE, state=analyzed))

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(InformationCluster)) == 2
        assert db.scalar(select(func.count()).select_from(SourceDependency)) == len(analyzed.dependencies)
