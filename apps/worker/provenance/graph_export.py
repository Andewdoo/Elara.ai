"""React Flow-compatible export for an in-memory provenance state."""

from __future__ import annotations

from graph.state import VerificationState


def export_source_graph(state: VerificationState) -> dict[str, list[dict[str, object]]]:
    clusters = {cluster.cluster_ref: cluster for cluster in state.information_clusters}
    cluster_by_source = {
        source_ref: cluster.cluster_ref
        for cluster in clusters.values()
        for source_ref in cluster.source_refs
    }
    snapshots = {snapshot.source_ref: snapshot for snapshot in state.snapshots}
    documents = {document.source_ref: document for document in state.extracted_sources}
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []

    for index, cluster in enumerate(state.information_clusters):
        nodes.append(
            {
                "id": f"cluster:{cluster.cluster_ref}",
                "type": "cluster",
                "label": cluster.label,
                "data": {"clusterId": cluster.cluster_ref, "originType": cluster.origin_type},
                "position": {"x": 0, "y": index * 180},
            }
        )
    for index, source in enumerate(state.candidate_sources):
        document = documents.get(source.source_ref)
        snapshot = snapshots.get(source.source_ref)
        source_id = f"source:{source.source_ref}"
        first_known = (
            (document.published_at if document else None)
            or (snapshot.published_at if snapshot else None)
            or (snapshot.retrieved_at if snapshot else None)
        )
        nodes.append(
            {
                "id": source_id,
                "type": "source",
                "label": (document.title if document else None) or source.title or source.domain or source.source_ref,
                "data": {
                    "sourceId": source.source_ref,
                    "accessStatus": snapshot.access_status if snapshot else "PENDING",
                    "role": source.source_type,
                    "clusterId": cluster_by_source.get(source.source_ref),
                    "dependencyMultiplier": float(
                        state.source_dependency_multipliers.get(source.source_ref, 1)
                    ),
                    "firstKnownAppearance": (
                        first_known.isoformat() if first_known is not None else None
                    ),
                    "contentType": snapshot.content_type if snapshot else None,
                },
                "position": {"x": 320, "y": index * 140},
            }
        )
        cluster_ref = cluster_by_source.get(source.source_ref)
        if cluster_ref:
            edges.append(
                _edge(
                    f"cluster-member:{cluster_ref}:{source.source_ref}",
                    f"cluster:{cluster_ref}",
                    source_id,
                    "INFORMATION_CLUSTER",
                    1.0,
                    "deterministic_cluster_membership",
                )
            )
        if snapshot:
            snapshot_node = f"snapshot:{snapshot.snapshot_id}"
            nodes.append(
                {
                    "id": snapshot_node,
                    "type": "snapshot",
                    "label": f"Snapshot {snapshot.retrieved_at.date().isoformat()}",
                    "data": {"sourceId": source.source_ref, "accessStatus": snapshot.access_status},
                    "position": {"x": 640, "y": index * 140},
                }
            )
            edges.append(_edge(f"snapshot-of:{snapshot.snapshot_id}", source_id, snapshot_node, "SNAPSHOT_OF", 1.0, "stored_snapshot_reference"))

    for edge in state.dependencies:
        edges.append(
            _edge(
                f"dependency:{edge.parent_source_ref}:{edge.child_source_ref}:{edge.relationship}",
                f"source:{edge.parent_source_ref}",
                f"source:{edge.child_source_ref}",
                edge.relationship,
                float(edge.confidence),
                edge.detection_method,
            )
        )
    return {"nodes": nodes, "edges": edges}


def _edge(edge_id, source, target, relationship, confidence, method):
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "label": relationship.replace("_", " ").lower(),
        "relationship": relationship,
        "confidence": confidence,
        "data": {
            "relationship": relationship,
            "confidence": confidence,
            "detectionMethod": method,
        },
    }


__all__ = ["export_source_graph"]
