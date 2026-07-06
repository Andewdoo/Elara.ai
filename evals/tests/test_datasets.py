import json
from pathlib import Path

import pytest

from evals.schema import (
    DATASET_SPLITS,
    PENDING_REVIEW,
    REQUIRED_DOMAINS,
    load_dataset,
    load_thresholds,
    validate_dataset,
)


DATASET_ROOT = Path(__file__).parents[1] / "datasets"


def test_versioned_candidate_datasets_cover_splits_and_required_domains():
    datasets = [load_dataset(path) for path in sorted((DATASET_ROOT / "v0.1.0").glob("*.json"))]
    assert {dataset["dataset_split"] for dataset in datasets} == DATASET_SPLITS
    cases = [case for dataset in datasets for case in dataset["cases"]]
    assert {case["domain"] for case in cases} == REQUIRED_DOMAINS
    assert all(case["review"]["review_status"] == PENDING_REVIEW for case in cases)
    assert all(
        label["value"] is None
        for case in cases
        for label in case["expected_labels"]["candidates"]
    )


def test_release_thresholds_are_unapproved_and_unset():
    payload = load_thresholds(DATASET_ROOT / "thresholds.step22a.json")
    assert payload["human_approval"] is False
    assert all(item["value"] is None for item in payload["thresholds"].values())


def test_candidate_dataset_rejects_a_human_approval_claim():
    path = DATASET_ROOT / "v0.1.0" / "regression.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["human_approval"] = True
    with pytest.raises(ValueError, match="human_approval"):
        validate_dataset(payload)
