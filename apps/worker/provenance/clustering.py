"""Deterministic information-origin clustering."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from graph.state import DependencyRecord, InformationClusterRecord, VerificationState


_CLUSTERING_RELATIONSHIPS = {
    "REPUBLISHES",
    "QUOTES",
    "DERIVES_FROM",
    "USES_SAME_DATA",
    "POSSIBLE_DUPLICATE",
}


def cluster_sources(
    state: VerificationState, dependencies: list[DependencyRecord]
) -> list[InformationClusterRecord]:
    source_refs = [source.source_ref for source in state.candidate_sources]
    parent = {source_ref: source_ref for source_ref in source_refs}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    for edge in dependencies:
        if (
            edge.relationship in _CLUSTERING_RELATIONSHIPS
            and edge.confidence >= Decimal("0.65")
            and edge.parent_source_ref in parent
            and edge.child_source_ref in parent
        ):
            union(edge.parent_source_ref, edge.child_source_ref)

    groups: dict[str, list[str]] = defaultdict(list)
    for source_ref in source_refs:
        groups[find(source_ref)].append(source_ref)

    documents = {item.source_ref: item for item in state.extracted_sources}
    snapshots = {item.source_ref: item for item in state.snapshots}
    candidates = {item.source_ref: item for item in state.candidate_sources}
    clusters: list[InformationClusterRecord] = []
    for members in sorted((sorted(values) for values in groups.values()), key=lambda values: values[0]):
        representative = min(
            members,
            key=lambda ref: (
                (documents.get(ref).published_at if documents.get(ref) else None)
                or (snapshots.get(ref).published_at if snapshots.get(ref) else None)
                or snapshots[ref].retrieved_at,
                ref,
            ),
        )
        relationships = {
            edge.relationship
            for edge in dependencies
            if edge.parent_source_ref in members and edge.child_source_ref in members
        }
        origin_type = _origin_type(relationships, len(members))
        representative_candidate = candidates[representative]
        label_base = (
            (documents.get(representative).title if documents.get(representative) else None)
            or representative_candidate.title
            or representative_candidate.domain
            or representative
        )
        cluster_ref = str(uuid5(NAMESPACE_URL, f"elara:{state.run_id}:cluster:{'|'.join(members)}"))
        clusters.append(
            InformationClusterRecord(
                cluster_ref=cluster_ref,
                label=f"{label_base} information origin",
                origin_type=origin_type,
                representative_source_ref=representative,
                source_refs=members,
            )
        )
    return clusters


def _origin_type(relationships: set[str], member_count: int) -> str:
    if member_count == 1:
        return "independent_origin"
    if "REPUBLISHES" in relationships:
        return "syndication_chain"
    if "DERIVES_FROM" in relationships:
        return "derived_reporting_chain"
    if "USES_SAME_DATA" in relationships:
        return "shared_data_chain"
    if "QUOTES" in relationships:
        return "shared_quotation_chain"
    return "possible_duplicate_chain"


__all__ = ["cluster_sources"]
