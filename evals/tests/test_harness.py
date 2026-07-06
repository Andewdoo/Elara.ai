from pathlib import Path

from evals.harness import evaluate, load_cases


def test_smoke_fixture_covers_required_quality_dimensions():
    result = evaluate(load_cases(Path(__file__).parents[1] / "cases" / "smoke.json"))
    assert result.case_count == 2
    assert set(result.metrics) >= {
        "verdict_accuracy", "attribution_accuracy", "evidence_precision", "evidence_recall",
        "passage_recall", "citation_entailment", "url_relevance_precision",
        "extraction_fidelity", "numerical_accuracy", "primary_source_recall",
        "duplicate_clustering_f1", "source_clustering_accuracy",
        "confidence_calibration_error", "confidence_brier_score",
        "unsupported_statement_rate", "mean_latency_seconds",
        "p95_latency_seconds", "mean_cost_per_verification_usd", "total_cost_usd",
    }
    assert result.metrics["unsupported_statement_rate"] == 0


def test_missing_expected_mapping_fields_fail_fidelity_checks():
    cases = [{
        "id": "missing-fields",
        "expected": {
            "verdict": "supported",
            "citation_entailment": {"sentence-1": "entailed"},
            "extracted_fields": {"amount": "10"},
            "numerical_checks": {"amount": "valid"},
        },
        "predicted": {"verdict": "supported", "confidence": 1.0},
    }]
    metrics = evaluate(cases).metrics
    assert metrics["citation_entailment"] == 0
    assert metrics["extraction_fidelity"] == 0
    assert metrics["numerical_accuracy"] == 0


def test_metrics_score_field_attribution_multiclass_brier_latency_and_cost():
    cases = [
        {
            "id": "metric-a",
            "expected": {
                "verdict": "supported",
                "attribution": {"speaker": "Ada", "organization": "Example"},
                "evidence_ids": ["e1", "e2"],
                "required_passage_ids": ["p1", "p2"],
                "primary_source_ids": ["s1"],
            },
            "predicted": {
                "verdict": "supported",
                "verdict_probabilities": {
                    "supported": 0.7,
                    "refuted": 0.1,
                    "mixed": 0.1,
                    "insufficient": 0.1,
                },
                "attribution": {"speaker": "Ada", "organization": "Wrong"},
                "evidence_ids": ["e1", "extra"],
                "required_passage_ids": ["p1"],
                "primary_source_ids": ["s1"],
                "statement_count": 4,
                "unsupported_statement_count": 1,
                "latency_seconds": 2,
                "cost_usd": 0.25,
            },
        }
    ]
    metrics = evaluate(cases).metrics
    assert metrics["attribution_accuracy"] == 0.5
    assert metrics["evidence_precision"] == 0.5
    assert metrics["evidence_recall"] == 0.5
    assert metrics["passage_recall"] == 0.5
    assert metrics["primary_source_recall"] == 1.0
    assert metrics["confidence_brier_score"] == 0.03
    assert metrics["unsupported_statement_rate"] == 0.25
    assert metrics["p95_latency_seconds"] == 2
    assert metrics["total_cost_usd"] == 0.25
