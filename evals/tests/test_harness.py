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
        "mean_cost_per_verification_usd",
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
