"""Deterministic, content-free operational and provider usage metrics."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from decimal import Decimal
from statistics import median
from typing import Any, Iterable


logger = logging.getLogger(__name__)
METRICS_STREAM = "elara:metrics:worker"
_STRUCTURED_FAILURE_SUBTYPES = (
    "response_json",
    "choices_envelope",
    "message_content_type",
    "content_json",
    "usage_metadata",
    "output_schema",
)


@dataclass(frozen=True, slots=True)
class MetricPoint:
    name: str
    value: float
    unit: str
    run_id: str
    research_depth: str


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def build_run_metrics(
    state: Any,
    *,
    duration_seconds: float,
    retry_count: int,
    queue_depth: int,
    input_cost_per_million: float = 0,
    output_cost_per_million: float = 0,
    search_cost_per_request: float = 0,
) -> list[MetricPoint]:
    snapshots = list(state.snapshots)
    fetched = [item for item in snapshots if item.access_status == "FETCHED"]
    fetch_latencies = [
        float(item.metadata["fetch_latency_ms"])
        for item in fetched
        if isinstance(item.metadata.get("fetch_latency_ms"), (int, float))
    ]
    calls = list(state.model_calls.values())
    embedding = state.embedding_run_metadata
    prompt_tokens = sum(item.usage.prompt_tokens for item in calls) + (
        embedding.prompt_tokens if embedding else 0
    )
    total_tokens = sum(item.usage.total_tokens for item in calls) + (
        embedding.total_tokens if embedding else 0
    )
    completion_tokens = max(0, total_tokens - prompt_tokens)
    model_request_count = sum(item.request_count for item in calls) + (
        embedding.request_count if embedding else 0
    )
    model_batch_count = sum(item.batch_count for item in calls)
    model_repair_count = sum(item.repair_count for item in calls)
    model_recovery_count = sum(item.recovery_count for item in calls)
    model_split_fallback_count = sum(item.split_fallback_count for item in calls)
    model_recovery_success_count = sum(item.recovery_success_count for item in calls)
    structured_failure_counts = {
        subtype: sum(item.structured_failure_counts.get(subtype, 0) for item in calls)
        for subtype in _STRUCTURED_FAILURE_SUBTYPES
    }
    recovery_exhaustion_count = 0
    for error in getattr(state, "recoverable_errors", []):
        details = error.details
        model_recovery_count += int(details.get("recovery_count", 0) or 0)
        model_split_fallback_count += int(details.get("split_fallback_count", 0) or 0)
        model_recovery_success_count += int(
            details.get("recovery_success_count", 0) or 0
        )
        recovery_exhaustion_count += int(
            details.get("recovery_exhaustion_count", 0) or 0
        )
        subtype = details.get("structured_failure_subtype")
        if subtype in structured_failure_counts:
            structured_failure_counts[subtype] += int(
                details.get("structured_failure_count", 0) or 0
            )
    search_executions = list(getattr(state, "search_query_executions", []))
    brave_query_count = sum(
        item.execution_status in {"executed", "cache_hit"} for item in search_executions
    ) or len(state.query_result_counts)
    brave_network_request_count = sum(
        item.network_attempt_count for item in search_executions
    ) or len(state.query_result_counts)
    brave_cache_hit_count = sum(
        item.execution_status == "cache_hit" for item in search_executions
    )
    brave_phase_two_query_count = sum(
        item.discovery_phase == "phase_two"
        and item.execution_status in {"executed", "cache_hit"}
        for item in search_executions
    )
    brave_gate_expansion_count = sum(
        item.discovery_phase == "phase_two"
        for item in getattr(state, "discovery_gate_outcomes", [])
    )
    cost = (
        Decimal(prompt_tokens) * Decimal(str(input_cost_per_million))
        + Decimal(completion_tokens) * Decimal(str(output_cost_per_million))
    ) / Decimal(1_000_000)
    cost += Decimal(brave_network_request_count) * Decimal(str(search_cost_per_request))
    approved_evidence = sum(
        not item.recommended_rejection_reasons for item in state.evidence
    )
    duplicate_members = sum(
        max(0, len(item.source_refs) - 1) for item in state.information_clusters
    )
    citation_failed = bool(state.citation_audit and state.citation_audit.needs_revision)
    values = {
        "brave_query_count": (float(brave_query_count), "query"),
        "brave_network_request_count": (float(brave_network_request_count), "request"),
        "brave_cache_hit_count": (float(brave_cache_hit_count), "query"),
        "brave_phase_two_query_count": (float(brave_phase_two_query_count), "query"),
        "brave_gate_expansion_count": (float(brave_gate_expansion_count), "expansion"),
        "search_to_fetch_conversion": (
            _ratio(len(fetched), sum(state.query_result_counts.values())),
            "ratio",
        ),
        "extraction_success": (
            _ratio(len(state.extracted_sources), len(fetched)),
            "ratio",
        ),
        "median_fetch_latency": (
            float(median(fetch_latencies)) if fetch_latencies else 0.0,
            "millisecond",
        ),
        "playwright_fallback_rate": (
            _ratio(
                sum(item.parser_name == "playwright" for item in snapshots),
                len(fetched),
            ),
            "ratio",
        ),
        "cache_hit_rate": (
            _ratio(
                sum(bool(item.metadata.get("cache_hit")) for item in fetched),
                len(fetched),
            ),
            "ratio",
        ),
        "duplicate_cluster_rate": (
            _ratio(duplicate_members, len(state.candidate_sources)),
            "ratio",
        ),
        # The methodology defines yield as accepted evidence per fetched source,
        # not as the fraction of candidate passages accepted.
        "evidence_yield": (
            _ratio(approved_evidence, len(fetched)),
            "evidence_per_source",
        ),
        "cost_per_verification": (float(cost), "currency_usd"),
        "deepseek_token_usage": (float(total_tokens), "token"),
        "deepseek_input_token_usage": (float(prompt_tokens), "token"),
        "deepseek_output_token_usage": (float(completion_tokens), "token"),
        "deepseek_request_count": (float(model_request_count), "request"),
        "deepseek_batch_count": (float(model_batch_count), "batch"),
        "deepseek_repair_count": (float(model_repair_count), "repair"),
        "deepseek_recovery_count": (float(model_recovery_count), "recovery_call"),
        "deepseek_split_fallback_count": (
            float(model_split_fallback_count),
            "split_fallback",
        ),
        "deepseek_recovery_success_count": (
            float(model_recovery_success_count),
            "recovered_batch",
        ),
        "deepseek_recovery_exhaustion_count": (
            float(recovery_exhaustion_count),
            "exhausted_stage",
        ),
        "source_accessibility_failure_rate": (
            _ratio(len(snapshots) - len(fetched), len(snapshots)),
            "ratio",
        ),
        "citation_audit_failure_rate": (float(citation_failed), "ratio"),
        "queue_length": (float(queue_depth), "job"),
        "run_duration": (round(duration_seconds, 6), "second"),
        "retry_count": (float(retry_count), "retry"),
        "cancellation_rate": (float(bool(state.cancelled)), "ratio"),
    }
    values.update(
        {
            f"deepseek_structured_failure_{subtype}_count": (float(count), "failure")
            for subtype, count in structured_failure_counts.items()
        }
    )
    return [
        MetricPoint(name, value, unit, str(state.run_id), state.research_depth.value)
        for name, (value, unit) in values.items()
    ]


def queue_length(redis_client: Any, queue_names: Iterable[str]) -> int:
    try:
        return sum(int(redis_client.llen(name)) for name in queue_names)
    except Exception:
        return 0


def emit_metrics(redis_client: Any, points: Iterable[MetricPoint]) -> None:
    for point in points:
        payload = asdict(point)
        logger.info("worker metric", extra={"metric": payload})
        try:
            redis_client.xadd(
                METRICS_STREAM,
                {"metric": json.dumps(payload, separators=(",", ":"))},
                maxlen=10_000,
                approximate=True,
            )
        except Exception:
            logger.warning("Unable to publish worker metric %s", point.name)


__all__ = [
    "METRICS_STREAM",
    "MetricPoint",
    "build_run_metrics",
    "emit_metrics",
    "queue_length",
]
