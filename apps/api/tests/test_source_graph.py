from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.models import (
    AccessStatus,
    DependencyRelationship,
    InformationCluster,
    RunSource,
    Source,
    SourceDependency,
    SourceSnapshot,
)


def test_source_graph_returns_authorized_react_flow_projection(
    client, session_factory: sessionmaker[Session]
):
    created = client.post(
        "/v1/verifications",
        json={"input_type": "CLAIM", "text": "A provenance test"},
    )
    run_id = UUID(created.json()["run_id"])
    now = datetime.now(UTC)
    with session_factory() as db:
        original = Source(
            canonical_url="https://records.example/original",
            domain="records.example",
            title="Original record",
            source_type="PRIMARY",
            first_seen_at=now,
            last_seen_at=now,
        )
        copy = Source(
            canonical_url="https://news.example/copy",
            domain="news.example",
            title="Republished report",
            source_type="DERIVATIVE_REPORT",
            first_seen_at=now + timedelta(hours=1),
            last_seen_at=now + timedelta(hours=1),
        )
        db.add_all([original, copy])
        db.flush()
        original_snapshot = SourceSnapshot(
            source_id=original.id,
            version_number=1,
            retrieved_at=now,
            published_at=now,
            access_status=AccessStatus.FETCHED,
            content_hash="original-hash",
        )
        copy_snapshot = SourceSnapshot(
            source_id=copy.id,
            version_number=1,
            retrieved_at=now + timedelta(hours=1),
            published_at=now + timedelta(hours=1),
            access_status=AccessStatus.FETCHED,
            content_hash="copy-hash",
        )
        db.add_all([original_snapshot, copy_snapshot])
        db.flush()
        db.add_all(
            [
                RunSource(run_id=run_id, source_id=original.id, snapshot_id=original_snapshot.id, role="PRIMARY", selected_rank=1),
                RunSource(run_id=run_id, source_id=copy.id, snapshot_id=copy_snapshot.id, role="DERIVATIVE_REPORT", selected_rank=2),
            ]
        )
        cluster = InformationCluster(
            run_id=run_id,
            label="Original record information origin",
            origin_type="syndication_chain",
            representative_source_id=original.id,
        )
        db.add(cluster)
        db.flush()
        dependency = SourceDependency(
            run_id=run_id,
            parent_source_id=original.id,
            child_source_id=copy.id,
            relationship=DependencyRelationship.REPUBLISHES,
            confidence=Decimal("1.0000"),
            detection_method="identical_content",
            information_cluster_id=cluster.id,
        )
        db.add(dependency)
        db.commit()

    response = client.get(f"/v1/verifications/{run_id}/source-graph")

    assert response.status_code == 200
    graph = response.json()
    assert all({"id", "type", "data", "position"} <= node.keys() for node in graph["nodes"])
    republish = next(edge for edge in graph["edges"] if edge["relationship"] == "REPUBLISHES")
    assert republish["data"] == {
        "relationship": "REPUBLISHES",
        "confidence": 1.0,
        "detectionMethod": "identical_content",
    }
    copy_node = next(node for node in graph["nodes"] if node["label"] == "Republished report")
    assert copy_node["data"]["dependencyMultiplier"] == 0.0


def test_source_graph_does_not_reveal_another_users_run(client, session_factory, owner):
    from app.models import InputType, ResearchDepth, RunStatus, User, VerificationRun

    now = datetime.now(UTC)
    with session_factory() as db:
        other = User(
            auth_provider="firebase",
            auth_subject="other-user",
            email="other@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(other)
        db.flush()
        run = VerificationRun(
            user_id=other.id,
            input_type=InputType.CLAIM,
            research_depth=ResearchDepth.STANDARD,
            status=RunStatus.QUEUED,
            submitted_text="private",
            workflow_version="step-11",
            queued_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        db.commit()
        run_id = run.id

    response = client.get(f"/v1/verifications/{run_id}/source-graph")
    assert response.status_code == 404
