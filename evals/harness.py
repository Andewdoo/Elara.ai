"""Offline evaluators for evidence-grounded verification outputs."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LABELS = ("supported", "refuted", "mixed", "insufficient")


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    metrics: dict[str, float]
    case_count: int


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _accuracy(cases: list[dict[str, Any]], key: str) -> float:
    relevant = [case for case in cases if key in case["expected"]]
    return _mean(float(case["predicted"].get(key) == case["expected"][key]) for case in relevant)


def _field_accuracy(cases: list[dict[str, Any]], key: str) -> float:
    """Score either a scalar annotation or a field-level annotation mapping."""
    mapping_cases = [case for case in cases if isinstance(case["expected"].get(key), dict)]
    scalar_cases = [case for case in cases if key in case["expected"] and case not in mapping_cases]
    checks: list[float] = []
    for case in mapping_cases:
        expected = case["expected"][key]
        predicted = case["predicted"].get(key, {})
        checks.extend(
            float(predicted.get(field) == expected.get(field))
            for field in set(expected) | set(predicted)
        )
    checks.extend(
        float(case["predicted"].get(key) == case["expected"][key]) for case in scalar_cases
    )
    return _mean(checks) if checks else 1.0


def _mapping_accuracy(cases: list[dict[str, Any]], key: str) -> float:
    checks: list[float] = []
    for case in cases:
        expected = case["expected"].get(key, {})
        predicted = case["predicted"].get(key, {})
        checks.extend(
            float(predicted.get(field) == expected.get(field))
            for field in set(expected) | set(predicted)
        )
    return _mean(checks) if checks else 1.0


def _set_scores(cases: list[dict[str, Any]], key: str) -> tuple[float, float]:
    tp = fp = fn = 0
    for case in cases:
        expected = set(case["expected"].get(key, []))
        predicted = set(case["predicted"].get(key, []))
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    return (
        tp / (tp + fp) if tp + fp else 1.0,
        tp / (tp + fn) if tp + fn else 1.0,
    )


def _macro_f1(cases: list[dict[str, Any]]) -> float:
    scores = []
    present = {case["expected"].get("verdict") for case in cases}
    for label in LABELS:
        if label not in present:
            continue
        tp = sum(c["expected"].get("verdict") == label == c["predicted"].get("verdict") for c in cases)
        fp = sum(c["predicted"].get("verdict") == label != c["expected"].get("verdict") for c in cases)
        fn = sum(c["expected"].get("verdict") == label != c["predicted"].get("verdict") for c in cases)
        scores.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0)
    return _mean(scores)


def _cluster_pairs(clusters: list[list[str]]) -> set[tuple[str, str]]:
    return {
        (min(left, right), max(left, right))
        for cluster in clusters
        for index, left in enumerate(cluster)
        for right in cluster[index + 1 :]
    }


def _cluster_f1(cases: list[dict[str, Any]]) -> float:
    tp = fp = fn = 0
    for case in cases:
        expected = _cluster_pairs(case["expected"].get("duplicate_clusters", []))
        predicted = _cluster_pairs(case["predicted"].get("duplicate_clusters", []))
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    return 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 1.0


def _brier_score(case: dict[str, Any]) -> float:
    """Use multiclass verdict probabilities when available, with legacy fallback."""
    expected_label = case["expected"].get("verdict")
    probabilities = case["predicted"].get("verdict_probabilities")
    if isinstance(probabilities, dict):
        return _mean(
            (float(probabilities.get(label, 0.0)) - float(label == expected_label)) ** 2
            for label in LABELS
        )
    correct = float(case["predicted"].get("verdict") == expected_label)
    confidence = float(case["predicted"].get("confidence", 0.0))
    return (confidence - correct) ** 2


def _percentile_95(values: Iterable[float]) -> float:
    items = sorted(values)
    if not items:
        return 0.0
    index = max(0, (95 * len(items) + 99) // 100 - 1)
    return items[index]


def evaluate(cases: list[dict[str, Any]]) -> EvaluationResult:
    evidence_precision, evidence_recall = _set_scores(cases, "evidence_ids")
    _, passage_recall = _set_scores(cases, "required_passage_ids")
    url_relevance_precision, _ = _set_scores(cases, "relevant_url_ids")
    _, primary_recall = _set_scores(cases, "primary_source_ids")
    correctness_and_confidence = [
        (
            float(case["predicted"].get("verdict") == case["expected"].get("verdict")),
            float(case["predicted"].get("confidence", 0)),
        )
        for case in cases
    ]
    calibration = _mean(abs(confidence - correct) for correct, confidence in correctness_and_confidence)
    brier_score = _mean(_brier_score(case) for case in cases)
    statements = sum(int(case["predicted"].get("statement_count", 0)) for case in cases)
    unsupported = sum(int(case["predicted"].get("unsupported_statement_count", 0)) for case in cases)
    latencies = [float(case["predicted"].get("latency_seconds", 0)) for case in cases]
    costs = [float(case["predicted"].get("cost_usd", 0)) for case in cases]
    metrics = {
        "verdict_accuracy": _accuracy(cases, "verdict"),
        "verdict_macro_f1": _macro_f1(cases),
        "attribution_accuracy": _field_accuracy(cases, "attribution"),
        "evidence_precision": evidence_precision,
        "evidence_recall": evidence_recall,
        "passage_recall": passage_recall,
        "citation_entailment": _mapping_accuracy(cases, "citation_entailment"),
        "url_relevance_precision": url_relevance_precision,
        "extraction_fidelity": _mapping_accuracy(cases, "extracted_fields"),
        "numerical_accuracy": _mapping_accuracy(cases, "numerical_checks"),
        "primary_source_recall": primary_recall,
        "duplicate_clustering_f1": _cluster_f1(cases),
        "source_clustering_accuracy": _cluster_f1(cases),
        "confidence_calibration_error": calibration,
        "confidence_brier_score": brier_score,
        "unsupported_statement_rate": unsupported / statements if statements else 0.0,
        "mean_latency_seconds": _mean(latencies),
        "p95_latency_seconds": _percentile_95(latencies),
        "mean_cost_per_verification_usd": _mean(costs),
        "total_cost_usd": sum(costs),
    }
    return EvaluationResult({key: round(value, 6) for key, value in metrics.items()}, len(cases))


def load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("evaluation file must contain at least one case")
    ids = [case.get("id") for case in payload]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("evaluation cases require unique non-empty ids")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", type=Path)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = evaluate(load_cases(args.cases))
    print(json.dumps({"case_count": result.case_count, "metrics": result.metrics}, sort_keys=True))
    if args.smoke:
        pass_metrics = (
            "verdict_accuracy", "attribution_accuracy", "evidence_precision", "evidence_recall",
            "passage_recall", "citation_entailment", "url_relevance_precision",
            "extraction_fidelity", "numerical_accuracy", "primary_source_recall",
            "duplicate_clustering_f1", "source_clustering_accuracy",
        )
        if any(result.metrics[name] < 1 for name in pass_metrics):
            return 1
        if result.metrics["confidence_calibration_error"] > 0.25 or result.metrics["unsupported_statement_rate"] > 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
