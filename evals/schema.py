"""Validation for versioned, human-review-gated evaluation datasets."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PENDING_REVIEW = "pending_human_approval"
DATASET_SPLITS = {
    "development_calibration",
    "locked_validation",
    "adversarial_security",
    "regression",
}
REQUIRED_DOMAINS = {
    "finance",
    "science",
    "technology",
    "current_events",
    "quotations",
    "paraphrases",
    "allegations",
    "numerical_claims",
    "misleading_context",
    "insufficient_evidence",
}
CASE_FIELDS = {
    "atomic_claims",
    "primary_sources",
    "acceptable_passages",
    "evidence_expectations",
    "attribution_expectations",
    "expected_labels",
    "expected_calculations",
    "citation_entailment",
    "dependency_clusters",
    "ambiguities",
    "inaccessible_sources",
}


def _require_pending(value: Any, location: str) -> None:
    if not isinstance(value, dict) or value.get("review_status") != PENDING_REVIEW:
        raise ValueError(f"{location} must be marked {PENDING_REVIEW}")


def validate_dataset(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("dataset must be a JSON object")
    split = payload.get("dataset_split")
    if split not in DATASET_SPLITS:
        raise ValueError(f"unknown dataset split: {split}")
    if not payload.get("schema_version") or not payload.get("dataset_version"):
        raise ValueError("dataset requires schema_version and dataset_version")
    if payload.get("human_approval") is not False:
        raise ValueError("Step 22A candidate datasets must set human_approval to false")
    if payload.get("review_status") != PENDING_REVIEW:
        raise ValueError(f"dataset review_status must be {PENDING_REVIEW}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("dataset requires at least one candidate case")
    seen: set[str] = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or case_id in seen:
            raise ValueError("candidate cases require unique non-empty ids")
        seen.add(case_id)
        if case.get("dataset_split") != split:
            raise ValueError(f"{case_id} has the wrong dataset_split")
        if case.get("domain") not in REQUIRED_DOMAINS:
            raise ValueError(f"{case_id} has an unknown domain")
        missing = CASE_FIELDS - set(case)
        if missing:
            raise ValueError(f"{case_id} is missing fields: {sorted(missing)}")
        _require_pending(case.get("review"), f"{case_id}.review")
        for field in CASE_FIELDS:
            _require_pending(case[field], f"{case_id}.{field}")
        claims = case["atomic_claims"].get("candidates")
        if not isinstance(claims, list) or not claims:
            raise ValueError(f"{case_id} requires at least one atomic claim")
        for claim in claims:
            if not claim.get("id") or not claim.get("text") or not claim.get("importance"):
                raise ValueError(f"{case_id} has an incomplete atomic claim")
    return payload


def load_dataset(path: Path) -> dict[str, Any]:
    return validate_dataset(json.loads(path.read_text(encoding="utf-8")))


def load_thresholds(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("human_approval") is not False:
        raise ValueError("Step 22A thresholds must set human_approval to false")
    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        raise ValueError("threshold registry is empty")
    for metric, annotation in thresholds.items():
        _require_pending(annotation, f"thresholds.{metric}")
        if annotation.get("value") is not None:
            raise ValueError(f"thresholds.{metric}.value must remain null before approval")
    return payload
