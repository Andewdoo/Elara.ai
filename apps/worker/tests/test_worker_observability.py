from types import SimpleNamespace
from uuid import uuid4

from agents.deepseek_client import CallMetadata, TokenUsage
from graph.state import ResearchDepth
from observability.metrics import build_run_metrics
from observability.sentry import before_send
from observability.tracing import SafeTrace, _metadata


def test_run_metrics_cover_required_operational_signals_without_content():
    state = SimpleNamespace(
        run_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        snapshots=[
            SimpleNamespace(
                access_status="FETCHED",
                metadata={"fetch_latency_ms": 40, "cache_hit": True},
                parser_name="trafilatura",
            ),
            SimpleNamespace(
                access_status="INACCESSIBLE",
                metadata={"fetch_latency_ms": 80},
                parser_name=None,
            ),
        ],
        extracted_sources=[object()],
        candidate_sources=[object(), object()],
        passages=[object(), object()],
        evidence=[
            SimpleNamespace(recommended_rejection_reasons=[]),
            SimpleNamespace(recommended_rejection_reasons=["low_quality"]),
        ],
        information_clusters=[SimpleNamespace(source_refs=["one", "two"])],
        query_result_counts={"query": 4},
        search_query_executions=[
            SimpleNamespace(
                execution_status="executed",
                network_attempt_count=2,
                discovery_phase="phase_one",
            ),
            SimpleNamespace(
                execution_status="cache_hit",
                network_attempt_count=0,
                discovery_phase="phase_two",
            ),
        ],
        discovery_gate_outcomes=[SimpleNamespace(discovery_phase="phase_two")],
        model_calls={
            "intake": CallMetadata(
                model="deepseek-chat",
                prompt_version="v1",
                temperature=0.1,
                latency_ms=10,
                usage=TokenUsage(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
                request_count=3,
                batch_count=2,
                repair_count=1,
                recovery_count=2,
                split_fallback_count=1,
                recovery_success_count=1,
                structured_failure_counts={"content_json": 2},
            )
        },
        recoverable_errors=[
            SimpleNamespace(
                details={
                    "recovery_count": 3,
                    "split_fallback_count": 1,
                    "recovery_success_count": 0,
                    "recovery_exhaustion_count": 1,
                    "structured_failure_subtype": "usage_metadata",
                    "structured_failure_count": 2,
                }
            )
        ],
        embedding_run_metadata=None,
        citation_audit=SimpleNamespace(needs_revision=True),
        cancelled=False,
    )
    points = {
        point.name: point
        for point in build_run_metrics(
            state, duration_seconds=2.5, retry_count=1, queue_depth=3
        )
    }
    assert set(points) >= {
        "search_to_fetch_conversion",
        "extraction_success",
        "median_fetch_latency",
        "playwright_fallback_rate",
        "cache_hit_rate",
        "duplicate_cluster_rate",
        "evidence_yield",
        "cost_per_verification",
        "deepseek_token_usage",
        "deepseek_input_token_usage",
        "deepseek_output_token_usage",
        "deepseek_request_count",
        "deepseek_batch_count",
        "deepseek_repair_count",
        "source_accessibility_failure_rate",
        "citation_audit_failure_rate",
        "queue_length",
        "run_duration",
        "retry_count",
        "cancellation_rate",
    }
    assert points["evidence_yield"].value == 1.0
    assert points["deepseek_input_token_usage"].value == 10
    assert points["deepseek_output_token_usage"].value == 5
    assert points["deepseek_request_count"].value == 3
    assert points["deepseek_batch_count"].value == 2
    assert points["deepseek_repair_count"].value == 1
    assert points["deepseek_recovery_count"].value == 5
    assert points["deepseek_split_fallback_count"].value == 2
    assert points["deepseek_recovery_success_count"].value == 1
    assert points["deepseek_recovery_exhaustion_count"].value == 1
    assert points["deepseek_structured_failure_content_json_count"].value == 2
    assert points["deepseek_structured_failure_usage_metadata_count"].value == 2
    assert points["brave_query_count"].value == 2
    assert points["brave_network_request_count"].value == 2
    assert points["brave_cache_hit_count"].value == 1
    assert points["brave_phase_two_query_count"].value == 1
    assert points["brave_gate_expansion_count"].value == 1


def test_observability_filters_sensitive_fields_and_trace_metadata():
    assert before_send({"extra": {"source_content": "private", "run_id": "safe"}}, {})[
        "extra"
    ] == {"source_content": "[Filtered]", "run_id": "safe"}
    assert _metadata(
        {"provider": "deepseek", "model": "deepseek-chat", "prompt": "secret"}
    ) == {"provider": "deepseek", "model": "deepseek-chat"}
    assert (
        before_send({"exception": {"values": [{"value": "private evidence"}]}}, {})[
            "exception"
        ]
        == "[Filtered]"
    )


def test_trace_outputs_allow_only_aggregate_fields():
    class RunTree:
        outputs = None

        def add_outputs(self, values):
            self.outputs = values

    run_tree = RunTree()
    SafeTrace(run_tree).add_outputs(
        {"completed_stage_count": 3, "source_content": "private"}
    )
    assert run_tree.outputs == {"completed_stage_count": 3}
