"""Deterministic source-dependency detection over untrusted extracted evidence."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from itertools import combinations
from urllib.parse import urlsplit, urlunsplit

from graph.state import DependencyRecord, ExtractedSourceRecord, VerificationState
from provenance.clustering import cluster_sources
from research.extension_errors import WorkflowExtensionError


_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s%$.,:-]", re.UNICODE)
_NUMBER = re.compile(
    r"(?<!\w)(?:[$€£]\s*)?-?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|percent|million|billion|trillion|thousand|kg|km|miles?|hours?|days?|years?))?",
    re.IGNORECASE,
)
_QUOTED = re.compile(r"[\"“](.{35,600}?)[\"”]", re.DOTALL)
_SYNDICATION = re.compile(
    r"\b(?:associated press|reuters|afp|wire service|republished (?:from|with permission)|originally published (?:by|in|at)|syndicated)\b",
    re.IGNORECASE,
)
_CORRECTION_OR_ERROR = re.compile(
    r"\b(?:correction|corrected|erroneously|incorrectly|error|typo)\b", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class _SourceFeatures:
    source_ref: str
    body: str
    normalized_body: str
    paragraphs: tuple[str, ...]
    quotes: frozenset[str]
    statistics: frozenset[str]
    tables: frozenset[str]
    outbound_links: frozenset[str]
    timestamp: datetime
    content_hash: str | None
    syndication_label: bool
    error_fragments: frozenset[str]


class SourceDependencyAnalyzer:
    """Infer auditable edges using only deterministic, inspectable signals."""

    def analyze(self, state: VerificationState) -> VerificationState:
        candidates = {item.source_ref: item for item in state.candidate_sources}
        snapshots = {item.source_ref: item for item in state.snapshots}
        extracted = {item.source_ref: item for item in state.extracted_sources}
        features = {
            source_ref: _features(document, snapshots[source_ref])
            for source_ref, document in extracted.items()
            if source_ref in snapshots
        }
        edges: list[DependencyRecord] = []
        seen: set[tuple[str, str, str]] = set()

        known_urls = {
            _canonical_url(candidate.canonical_url or candidate.url): source_ref
            for source_ref, candidate in candidates.items()
        }
        for child_ref, feature in features.items():
            for link in feature.outbound_links:
                parent_ref = known_urls.get(_canonical_url(link))
                if parent_ref and parent_ref != child_ref:
                    _add_edge(
                        edges,
                        seen,
                        parent_ref,
                        child_ref,
                        "CITES",
                        Decimal("0.9900"),
                        "explicit_outbound_link",
                    )
            child_text = feature.normalized_body
            for parent_ref, parent_document in extracted.items():
                if parent_ref == child_ref:
                    continue
                parent_candidate = candidates.get(parent_ref)
                names = {
                    _normalize(value)
                    for value in (
                        parent_document.title,
                        parent_document.publisher,
                        parent_candidate.title if parent_candidate else None,
                    )
                    if value and len(_normalize(value)) >= 5
                }
                if any(name in child_text for name in names):
                    _add_edge(
                        edges,
                        seen,
                        parent_ref,
                        child_ref,
                        "CITES",
                        Decimal("0.8500"),
                        "explicit_named_source",
                    )

        for left, right in combinations(features.values(), 2):
            parent, child = _ordered(left, right)
            text_similarity = _text_similarity(parent.normalized_body, child.normalized_body)
            paragraph_order_similarity = _ordered_paragraph_similarity(
                parent.paragraphs, child.paragraphs
            )
            similarity = max(
                text_similarity,
                paragraph_order_similarity * Decimal("0.9000"),
            )
            exact_copy = bool(
                parent.content_hash
                and child.content_hash
                and parent.content_hash == child.content_hash
            ) or parent.normalized_body == child.normalized_body
            if exact_copy:
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "REPUBLISHES", Decimal("1.0000"), "identical_content")
            elif similarity >= Decimal("0.9000") or (
                similarity >= Decimal("0.7000")
                and (parent.syndication_label or child.syndication_label)
            ):
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "REPUBLISHES", max(similarity, Decimal("0.9000")), "syndication_text_and_paragraph_order")
            elif similarity >= Decimal("0.6500"):
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "POSSIBLE_DUPLICATE", similarity, "near_identical_text_or_paragraph_order")

            quote_similarity = _shared_feature_similarity(
                parent.quotes, child.quotes, threshold=Decimal("0.9000")
            )
            if quote_similarity is not None:
                confidence = min(
                    Decimal("0.9800"),
                    Decimal("0.7000") + quote_similarity * Decimal("0.2800"),
                )
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "QUOTES", confidence, "shared_quotation_first_known")

            table_similarity = _shared_feature_similarity(
                parent.tables, child.tables, threshold=Decimal("0.7200")
            )
            shared_stats = parent.statistics & child.statistics
            if table_similarity is not None or len(shared_stats) >= 2:
                confidence = (
                    min(Decimal("0.9500"), Decimal("0.7000") + table_similarity * Decimal("0.2500"))
                    if table_similarity is not None
                    else min(Decimal("0.8800"), Decimal("0.6200") + Decimal(len(shared_stats)) * Decimal("0.0400"))
                )
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "USES_SAME_DATA", confidence, "shared_table_or_statistics")

            error_similarity = _shared_feature_similarity(
                parent.error_fragments,
                child.error_fragments,
                threshold=Decimal("0.7500"),
            )
            cites_parent = (parent.source_ref, child.source_ref, "CITES") in seen
            shared_evidence = (
                quote_similarity is not None
                or table_similarity is not None
                or len(shared_stats) >= 2
            )
            if error_similarity is not None or (cites_parent and shared_evidence):
                _add_edge(edges, seen, parent.source_ref, child.source_ref, "DERIVES_FROM", Decimal("0.9200") if error_similarity is not None else Decimal("0.8600"), "shared_error_or_cited_evidence_chain")

        clusters = cluster_sources(state, edges)
        cluster_by_source = {
            source_ref: cluster.cluster_ref
            for cluster in clusters
            for source_ref in cluster.source_refs
        }
        multipliers = dependency_multipliers(
            list(candidates), edges, source_types={key: value.source_type for key, value in candidates.items()}
        )
        clustered_edges = [
            edge.model_copy(
                update={
                    "information_cluster_ref": (
                        cluster_by_source.get(edge.child_source_ref)
                        if cluster_by_source.get(edge.parent_source_ref)
                        == cluster_by_source.get(edge.child_source_ref)
                        else None
                    ),
                    "dependency_multiplier": multipliers[edge.child_source_ref],
                }
            )
            for edge in edges
        ]
        validate_provenance(
            source_refs=set(candidates),
            dependencies=clustered_edges,
            multipliers=multipliers,
        )
        return state.model_copy(
            update={
                "information_clusters": clusters,
                "dependencies": clustered_edges,
                "source_dependency_multipliers": multipliers,
            }
        )


class ProvenancePipeline:
    def __init__(self, analyzer: SourceDependencyAnalyzer | None = None) -> None:
        self.analyzer = analyzer or SourceDependencyAnalyzer()

    async def process(self, state: VerificationState) -> VerificationState:
        return self.analyzer.analyze(state)


_ALLOWED_DEPENDENCY_MULTIPLIERS = {
    Decimal("1.00"),
    Decimal("0.35"),
    Decimal("0.10"),
    Decimal("0.00"),
}


def validate_provenance(
    *,
    source_refs: set[str],
    dependencies: list[DependencyRecord],
    multipliers: dict[str, Decimal],
) -> None:
    """Reject invalid deterministic provenance outputs before stage completion."""
    unknown_endpoints = sum(
        1
        for edge in dependencies
        if edge.parent_source_ref not in source_refs or edge.child_source_ref not in source_refs
    )
    if unknown_endpoints:
        raise WorkflowExtensionError(
            code="INVALID_PROVENANCE_ENDPOINT",
            public_message="Provenance referenced a source that was not selected for this run.",
            details={"invalid_endpoint_count": unknown_endpoints},
        )
    edge_keys = [
        (edge.parent_source_ref, edge.child_source_ref, edge.relationship)
        for edge in dependencies
    ]
    duplicate_count = len(edge_keys) - len(set(edge_keys))
    if duplicate_count:
        raise WorkflowExtensionError(
            code="DUPLICATE_PROVENANCE_EDGE",
            public_message="Provenance produced duplicate source-dependency edges.",
            details={"duplicate_edge_count": duplicate_count},
        )
    missing_multiplier_count = len(source_refs - set(multipliers))
    invalid_multiplier_count = sum(
        1
        for source_ref, value in multipliers.items()
        if source_ref not in source_refs or value not in _ALLOWED_DEPENDENCY_MULTIPLIERS
    )
    if missing_multiplier_count or invalid_multiplier_count:
        raise WorkflowExtensionError(
            code="INVALID_DEPENDENCY_MULTIPLIER",
            public_message="Provenance produced an unsupported source-dependency multiplier.",
            details={
                "missing_multiplier_count": missing_multiplier_count,
                "invalid_multiplier_count": invalid_multiplier_count,
            },
        )


def dependency_multipliers(
    source_refs: list[str],
    dependencies: list[DependencyRecord],
    *,
    source_types: dict[str, str] | None = None,
) -> dict[str, Decimal]:
    """Apply the methodology's four deterministic contribution levels."""
    by_child: dict[str, list[DependencyRecord]] = defaultdict(list)
    for edge in dependencies:
        by_child[edge.child_source_ref].append(edge)
    result: dict[str, Decimal] = {}
    for source_ref in source_refs:
        relationships = by_child[source_ref]
        if any(edge.relationship == "REPUBLISHES" for edge in relationships):
            result[source_ref] = Decimal("0.00")
        elif (
            (source_types or {}).get(source_ref) == "INDEPENDENT_ANALYSIS"
            and not any(edge.relationship == "POSSIBLE_DUPLICATE" for edge in relationships)
        ):
            result[source_ref] = Decimal("0.35")
        elif any(edge.relationship in {"DERIVES_FROM", "QUOTES", "USES_SAME_DATA", "POSSIBLE_DUPLICATE"} for edge in relationships):
            only_shared_data = all(edge.relationship == "USES_SAME_DATA" for edge in relationships)
            result[source_ref] = (
                Decimal("0.35")
                if only_shared_data
                and (source_types or {}).get(source_ref)
                not in {"SECONDARY_REPORT", "DERIVATIVE_REPORT", "OFFICIAL_SELF_REPORT"}
                else Decimal("0.10")
            )
        else:
            result[source_ref] = Decimal("1.00")
    return result


def _features(document: ExtractedSourceRecord, snapshot) -> _SourceFeatures:
    body = document.body
    normalized = _normalize(body)
    quotes = {_normalize(value) for value in document.quotes if len(_normalize(value)) >= 35}
    quotes.update(_normalize(match) for match in _QUOTED.findall(body) if len(_normalize(match)) >= 35)
    tables = {_normalize(value) for value in document.tables if len(_normalize(value)) >= 20}
    errors = {
        _normalize(paragraph)
        for paragraph in re.split(r"\n\s*\n", body)
        if _CORRECTION_OR_ERROR.search(paragraph) and 20 <= len(_normalize(paragraph)) <= 500
    }
    timestamp = document.published_at or document.updated_at or snapshot.published_at or snapshot.retrieved_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return _SourceFeatures(
        source_ref=document.source_ref,
        body=body,
        normalized_body=normalized,
        paragraphs=tuple(_normalize(value) for value in re.split(r"\n\s*\n", body) if value.strip()),
        quotes=frozenset(quotes),
        statistics=frozenset(_statistics(body)),
        tables=frozenset(tables),
        outbound_links=frozenset(document.outbound_links),
        timestamp=timestamp,
        content_hash=snapshot.content_hash,
        syndication_label=bool(_SYNDICATION.search(body)),
        error_fragments=frozenset(errors),
    )


def _add_edge(edges, seen, parent, child, relationship, confidence, method) -> None:
    key = (parent, child, relationship)
    if parent == child or key in seen:
        return
    seen.add(key)
    edges.append(
        DependencyRecord(
            parent_source_ref=parent,
            child_source_ref=child,
            relationship=relationship,
            confidence=confidence.quantize(Decimal("0.0001")),
            detection_method=method,
        )
    )


def _ordered(left: _SourceFeatures, right: _SourceFeatures) -> tuple[_SourceFeatures, _SourceFeatures]:
    return (left, right) if (left.timestamp, left.source_ref) <= (right.timestamp, right.source_ref) else (right, left)


def _normalize(value: str) -> str:
    return _SPACE.sub(" ", _PUNCT.sub(" ", value.casefold())).strip()


def _normalize_number(value: str) -> str:
    return _SPACE.sub("", value.casefold().replace(",", ""))


def _statistics(text: str) -> set[str]:
    """Keep distinctive quantitative values; discard years and trivial counters."""
    values: set[str] = set()
    for match in _NUMBER.finditer(text):
        raw = match.group(0).strip()
        normalized = _normalize_number(raw)
        numeric = re.sub(r"[^0-9.-]", "", normalized)
        try:
            number = Decimal(numeric)
        except (InvalidOperation, ValueError):
            continue
        has_unit = bool(re.search(r"[%$€£]|[a-z]", raw, re.IGNORECASE))
        if not has_unit and number == number.to_integral_value():
            integer = int(number)
            if 1900 <= integer <= 2100 or -9 <= integer <= 9:
                continue
        values.add(normalized)
    return values


def _shared_feature_similarity(
    left: frozenset[str],
    right: frozenset[str],
    *,
    threshold: Decimal,
) -> Decimal | None:
    best: Decimal | None = None
    for left_value in left:
        for right_value in right:
            similarity = _text_similarity(left_value, right_value)
            if similarity >= threshold and (best is None or similarity > best):
                best = similarity
    return best


def _ordered_paragraph_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> Decimal:
    if len(left) < 2 or len(right) < 2:
        return Decimal("0")
    left_signatures = [_paragraph_signature(value) for value in left]
    right_signatures = [_paragraph_signature(value) for value in right]
    return Decimal(str(SequenceMatcher(None, left_signatures, right_signatures, autojunk=False).ratio()))


def _paragraph_signature(value: str) -> str:
    return " ".join(value.split()[:12])


def _text_similarity(left: str, right: str) -> Decimal:
    if not left or not right:
        return Decimal("0")
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) < 500:
        return Decimal(str(SequenceMatcher(None, shorter, longer, autojunk=False).ratio()))
    left_shingles = _shingles(left)
    right_shingles = _shingles(right)
    union = left_shingles | right_shingles
    return Decimal(len(left_shingles & right_shingles)) / Decimal(len(union) or 1)


def _shingles(text: str, size: int = 5) -> set[tuple[str, ...]]:
    tokens = text.split()
    if len(tokens) < size:
        return {tuple(tokens)}
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def _canonical_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        port = f":{parsed.port}" if parsed.port and parsed.port not in {80, 443} else ""
        path = parsed.path.rstrip("/") or "/"
        return urlunsplit((parsed.scheme.casefold(), f"{host}{port}", path, parsed.query, ""))
    except ValueError:
        return url


__all__ = [
    "ProvenancePipeline",
    "SourceDependencyAnalyzer",
    "dependency_multipliers",
    "validate_provenance",
]
