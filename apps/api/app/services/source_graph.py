"""Authorized, run-scoped source graph projection for React Flow."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import DependencyRelationship, SourceType
from app.models.claims import AtomicClaim
from app.models.evidence import EvidenceItem, ReportCitation
from app.models.provenance import InformationCluster, SourceDependency
from app.models.sources import RunSource, Source, SourcePassage, SourceSnapshot
from app.schemas.verifications import SourceGraphEdge, SourceGraphNode, SourceGraphResponse


def build_source_graph(db: Session, *, run_id: UUID) -> SourceGraphResponse:
    source_rows = db.execute(
        select(RunSource, Source, SourceSnapshot)
        .join(Source, Source.id == RunSource.source_id)
        .outerjoin(SourceSnapshot, SourceSnapshot.id == RunSource.snapshot_id)
        .where(RunSource.run_id == run_id)
        .order_by(RunSource.selected_rank.asc().nullslast(), Source.first_seen_at, Source.id)
    ).all()
    source_ids = {source.id for _, source, _ in source_rows}
    evidence_rows = db.execute(
        select(SourcePassage.source_id, EvidenceItem.atomic_claim_id)
        .join(EvidenceItem, EvidenceItem.passage_id == SourcePassage.id)
        .join(AtomicClaim, AtomicClaim.id == EvidenceItem.atomic_claim_id)
        .where(AtomicClaim.run_id == run_id, SourcePassage.source_id.in_(source_ids))
    ).all()
    claim_ids_by_source: dict[UUID, set[str]] = defaultdict(set)
    for source_id, claim_id in evidence_rows:
        claim_ids_by_source[source_id].add(str(claim_id))
    cited_source_ids = set(
        db.scalars(
            select(SourcePassage.source_id)
            .join(ReportCitation, ReportCitation.passage_id == SourcePassage.id)
            .where(
                ReportCitation.run_id == run_id,
                ReportCitation.audit_status == "passed",
                SourcePassage.source_id.in_(source_ids),
            )
        ).all()
    )
    clusters = db.scalars(
        select(InformationCluster)
        .where(InformationCluster.run_id == run_id)
        .order_by(InformationCluster.created_at, InformationCluster.id)
    ).all()
    dependencies = [
        edge
        for edge in db.scalars(
            select(SourceDependency)
            .where(SourceDependency.run_id == run_id)
            .order_by(SourceDependency.created_at, SourceDependency.id)
        ).all()
        if edge.parent_source_id in source_ids and edge.child_source_id in source_ids
    ]
    memberships: dict[UUID, UUID] = {}
    for edge in dependencies:
        if edge.information_cluster_id is not None:
            memberships[edge.parent_source_id] = edge.information_cluster_id
            memberships[edge.child_source_id] = edge.information_cluster_id
    for cluster in clusters:
        if cluster.representative_source_id in source_ids:
            memberships.setdefault(cluster.representative_source_id, cluster.id)

    nodes: list[SourceGraphNode] = []
    edges: list[SourceGraphEdge] = []
    cluster_y = {cluster.id: index * 180.0 for index, cluster in enumerate(clusters)}
    for cluster in clusters:
        nodes.append(
            SourceGraphNode(
                id=f"cluster:{cluster.id}",
                type="cluster",
                label=cluster.label,
                data={"clusterId": str(cluster.id), "originType": cluster.origin_type},
                position={"x": 0.0, "y": cluster_y[cluster.id]},
                metadata={
                    "representativeSourceId": (
                        str(cluster.representative_source_id)
                        if cluster.representative_source_id in source_ids
                        else None
                    )
                },
            )
        )

    source_y_by_cluster: dict[UUID | None, int] = defaultdict(int)
    multipliers = _dependency_multipliers(source_ids, dependencies, {source.id: source.source_type for _, source, _ in source_rows})
    for fallback_index, (run_source, source, snapshot) in enumerate(source_rows):
        cluster_id = memberships.get(source.id)
        local_index = source_y_by_cluster[cluster_id]
        source_y_by_cluster[cluster_id] += 1
        y = cluster_y.get(cluster_id, fallback_index * 180.0) + local_index * 90.0
        nodes.append(
            SourceGraphNode(
                id=f"source:{source.id}",
                type="source",
                label=source.title or source.publisher or source.domain,
                data={
                    "sourceId": str(source.id),
                    "accessStatus": (
                        snapshot.access_status.value
                        if snapshot
                        else "INACCESSIBLE" if run_source.inaccessible_reason else "PENDING"
                    ),
                    "role": run_source.role,
                    "clusterId": str(cluster_id) if cluster_id else None,
                    "dependencyMultiplier": float(multipliers[source.id]),
                    "firstKnownAppearance": _first_known(source, snapshot),
                    "contentType": source.content_type,
                    "atomicClaimIds": sorted(claim_ids_by_source[source.id]),
                    "evidenceUsed": source.id in cited_source_ids,
                },
                position={"x": 320.0, "y": y},
                metadata={
                    "canonicalUrl": source.canonical_url,
                    "domain": source.domain,
                    "publisher": source.publisher,
                    "sourceType": source.source_type.value,
                    "firstKnownAppearance": _first_known(source, snapshot),
                },
            )
        )
        if cluster_id is not None:
            edges.append(
                _edge(
                    edge_id=f"cluster-member:{cluster_id}:{source.id}",
                    source=f"cluster:{cluster_id}",
                    target=f"source:{source.id}",
                    relationship="INFORMATION_CLUSTER",
                    confidence=1.0,
                    detection_method="deterministic_cluster_membership",
                )
            )
        if snapshot is not None:
            nodes.append(
                SourceGraphNode(
                    id=f"snapshot:{snapshot.id}",
                    type="snapshot",
                    label=f"Snapshot {snapshot.retrieved_at.date().isoformat()}",
                    data={
                        "sourceId": str(source.id),
                        "accessStatus": snapshot.access_status.value,
                        "role": run_source.role,
                        "clusterId": str(cluster_id) if cluster_id else None,
                        "atomicClaimIds": sorted(claim_ids_by_source[source.id]),
                        "evidenceUsed": source.id in cited_source_ids,
                    },
                    position={"x": 640.0, "y": y},
                    metadata={
                        "snapshotId": str(snapshot.id),
                        "retrievedAt": snapshot.retrieved_at.isoformat(),
                        "publishedAt": snapshot.published_at.isoformat() if snapshot.published_at else None,
                        "contentHash": snapshot.content_hash,
                        "parserName": snapshot.parser_name,
                        "parserVersion": snapshot.parser_version,
                    },
                )
            )
            edges.append(
                _edge(
                    edge_id=f"snapshot-of:{snapshot.id}",
                    source=f"source:{source.id}",
                    target=f"snapshot:{snapshot.id}",
                    relationship="SNAPSHOT_OF",
                    confidence=1.0,
                    detection_method="stored_snapshot_reference",
                )
            )

    for dependency in dependencies:
        edges.append(
            _edge(
                edge_id=f"dependency:{dependency.id}",
                source=f"source:{dependency.parent_source_id}",
                target=f"source:{dependency.child_source_id}",
                relationship=dependency.relationship.value,
                confidence=float(dependency.confidence),
                detection_method=dependency.detection_method,
            )
        )
    return SourceGraphResponse(nodes=nodes, edges=edges)


def _dependency_multipliers(source_ids, dependencies, source_types):
    by_child = defaultdict(list)
    for edge in dependencies:
        by_child[edge.child_source_id].append(edge.relationship)
    result = {}
    for source_id in source_ids:
        relationships = set(by_child[source_id])
        if DependencyRelationship.REPUBLISHES in relationships:
            result[source_id] = Decimal("0.00")
        elif (
            source_types[source_id] == SourceType.INDEPENDENT_ANALYSIS
            and DependencyRelationship.POSSIBLE_DUPLICATE not in relationships
        ):
            result[source_id] = Decimal("0.35")
        elif relationships.intersection(
            {
                DependencyRelationship.DERIVES_FROM,
                DependencyRelationship.QUOTES,
                DependencyRelationship.USES_SAME_DATA,
                DependencyRelationship.POSSIBLE_DUPLICATE,
            }
        ):
            only_shared_data = relationships == {DependencyRelationship.USES_SAME_DATA}
            repeated_roles = {
                SourceType.SECONDARY_REPORT,
                SourceType.DERIVATIVE_REPORT,
                SourceType.OFFICIAL_SELF_REPORT,
            }
            result[source_id] = (
                Decimal("0.35")
                if only_shared_data and source_types[source_id] not in repeated_roles
                else Decimal("0.10")
            )
        else:
            result[source_id] = Decimal("1.00")
    return result


def _first_known(source: Source, snapshot: SourceSnapshot | None) -> str:
    value = (snapshot.published_at if snapshot else None) or source.first_seen_at
    return value.isoformat()


def _edge(*, edge_id, source, target, relationship, confidence, detection_method):
    return SourceGraphEdge(
        id=edge_id,
        source=source,
        target=target,
        label=relationship.replace("_", " ").lower(),
        relationship=relationship,
        confidence=confidence,
        data={
            "relationship": relationship,
            "confidence": confidence,
            "detectionMethod": detection_method,
        },
    )


__all__ = ["build_source_graph"]
