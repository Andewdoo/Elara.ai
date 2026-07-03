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
    model_request_count = len(calls) + (embedding.request_count if embedding else 0)
    search_requests = len(state.query_result_counts)
    cost = (
        Decimal(prompt_tokens) * Decimal(str(input_cost_per_million))
        + Decimal(completion_tokens) * Decimal(str(output_cost_per_million))
    ) / Decimal(1_000_000)
    cost += Decimal(search_requests) * Decimal(str(search_cost_per_request))
    approved_evidence = sum(
        not item.recommended_rejection_reasons for item in state.evidence
    )
    duplicate_members = sum(max(0, len(item.source_refs) - 1) for item in state.information_clusters)
    citation_failed = bool(state.citation_audit and state.citation_audit.needs_revision)
    values = {
        "search_to_fetch_conversion": (_ratio(len(fetched), sum(state.query_result_counts.values())), "ratio"),
        "extraction_success": (_ratio(len(state.extracted_sources), len(fetched)), "ratio"),
        "median_fetch_latency": (float(median(fetch_latencies)) if fetch_latencies else 0.0, "millisecond"),
        "playwright_fallback_rate": (_ratio(sum(item.parser_name == "playwright" for item in snapshots), len(fetched)), "ratio"),
        "cache_hit_rate": (_ratio(sum(bool(item.metadata.get("cache_hit")) for item in fetched), len(fetched)), "ratio"),
        "duplicate_cluster_rate": (_ratio(duplicate_members, len(state.candidate_sources)), "ratio"),
        # The methodology defines yield as accepted evidence per fetched source,
        # not as the fraction of candidate passages accepted.
        "evidence_yield": (_ratio(approved_evidence, len(fetched)), "evidence_per_source"),
        "cost_per_verification": (float(cost), "currency_usd"),
        "deepseek_token_usage": (float(total_tokens), "token"),
        "deepseek_input_token_usage": (float(prompt_tokens), "token"),
        "deepseek_output_token_usage": (float(completion_tokens), "token"),
        "deepseek_request_count": (float(model_request_count), "request"),
        "source_accessibility_failure_rate": (_ratio(len(snapshots) - len(fetched), len(snapshots)), "ratio"),
        "citation_audit_failure_rate": (float(citation_failed), "ratio"),
        "queue_length": (float(queue_depth), "job"),
        "run_duration": (round(duration_seconds, 6), "second"),
        "retry_count": (float(retry_count), "retry"),
        "cancellation_rate": (float(bool(state.cancelled)), "ratio"),
    }
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


__all__ = ["METRICS_STREAM", "MetricPoint", "build_run_metrics", "emit_metrics", "queue_length"]
