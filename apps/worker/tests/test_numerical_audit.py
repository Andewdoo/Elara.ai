import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest

from auditing.numerical import (
    AuditStatus,
    NumericalAuditor,
    NumericalCandidate,
    NumericalInput,
    NumericalOperation,
    RoundingRule,
)
from graph.state import ResearchDepth, ScoreBundle, VerificationState
from research.extension_errors import WorkflowExtensionError


def candidate(operation, inputs, **kwargs):
    return NumericalCandidate(
        candidate_ref="candidate-1",
        claim_ref="claim-1",
        operation=operation,
        inputs=inputs,
        **kwargs,
    )


def value(role, amount, unit="people", period="2025", source="source-1"):
    return NumericalInput(
        role=role, value=str(amount), unit=unit, period=period, source_ref=source
    )


def test_decimal_percentage_and_ratio_are_reproducible():
    auditor = NumericalAuditor()
    percentage = auditor.audit(
        candidate(
            NumericalOperation.PERCENTAGE,
            [value("numerator", "1"), value("denominator", "3")],
        )
    )
    ratio = auditor.audit(
        candidate(
            NumericalOperation.RATIO,
            [value("numerator", "10"), value("denominator", "4")],
        )
    )

    assert percentage.result["value"] == "33.33333333333333333333333333"
    assert ratio.result["value"] == "2.5"
    assert percentage.decimal_context == {
        "precision": 28,
        "rounding": "ROUND_HALF_UP",
        "applied_rounding": None,
    }
    assert percentage.audit_status == ratio.audit_status == AuditStatus.PASSED


def test_rounding_rule_is_explicit_and_matches_claim_after_rounding():
    record = NumericalAuditor().audit(
        candidate(
            NumericalOperation.PERCENTAGE,
            [value("numerator", "1"), value("denominator", "6")],
            claimed_value="16.7",
            rounding=RoundingRule(quantum="0.1", mode="ROUND_HALF_UP"),
        )
    )

    assert record.result["value"] == "16.7"
    assert record.result["unrounded_value"] == "16.66666666666666666666666667"
    assert record.result["matches_claim"] is True
    assert record.inputs["rounding"] == {"quantum": "0.1", "mode": "ROUND_HALF_UP"}


@pytest.mark.parametrize(
    ("amount", "source_unit", "target_unit", "expected"),
    [("1.25", "km", "m", "1.25E+3"), ("2500", "g", "kg", "2.500")],
)
def test_unit_conversion_uses_decimal_factors(amount, source_unit, target_unit, expected):
    record = NumericalAuditor().audit(
        candidate(
            NumericalOperation.UNIT_CONVERSION,
            [value("value", amount, unit=source_unit)],
            output_unit=target_unit,
        )
    )

    assert record.audit_status == AuditStatus.PASSED
    assert Decimal(record.result["value"]) == Decimal(expected)
    assert record.units == target_unit


def test_total_and_comparison_are_correct_and_expose_denominator():
    auditor = NumericalAuditor()
    total = auditor.audit(
        candidate(
            NumericalOperation.TOTAL,
            [value("component", "0.1"), value("component_2", "0.2")],
        )
    )
    comparison = auditor.audit(
        candidate(
            NumericalOperation.COMPARISON,
            [value("current", "125"), value("baseline", "100")],
        )
    )

    assert total.result["value"] == "0.3"
    assert comparison.result["value"] == "25.00"
    assert comparison.result["absolute_difference"] == "25"
    assert comparison.result["denominator"] == "100"


@pytest.mark.parametrize(
    ("inputs", "expected"),
    [
        ([value("numerator", "1")], AuditStatus.MISSING_DENOMINATOR),
        ([value("numerator", "1"), value("denominator", "0")], AuditStatus.ZERO_DENOMINATOR),
        (
            [value("numerator", "1", period="2025"), value("denominator", "2", period="2024")],
            AuditStatus.PERIOD_MISMATCH,
        ),
        (
            [value("numerator", "1", unit="kg"), value("denominator", "2", unit="people")],
            AuditStatus.MISMATCHED_UNITS,
        ),
    ],
)
def test_denominator_unit_period_and_zero_failures_are_explicit(inputs, expected):
    record = NumericalAuditor().audit(candidate(NumericalOperation.PERCENTAGE, inputs))
    assert record.audit_status == expected
    assert record.result == {"value": None, "issues": [expected.value]}


def test_conflicting_source_values_fail_instead_of_selecting_one():
    record = NumericalAuditor().audit(
        candidate(
            NumericalOperation.RATIO,
            [
                value("numerator", "10", source="source-a"),
                value("numerator", "11", source="source-b"),
                value("denominator", "20", source="source-c"),
            ],
        )
    )
    assert record.audit_status == AuditStatus.SOURCE_VALUE_CONFLICT
    assert record.result["value"] is None
    assert len(record.inputs["values"]) == 3


def test_incompatible_and_unknown_conversions_fail_explicitly():
    mismatch = NumericalAuditor().audit(
        candidate(
            NumericalOperation.UNIT_CONVERSION,
            [value("value", "1", unit="kg")],
            output_unit="km",
        )
    )
    unsupported = NumericalAuditor().audit(
        candidate(
            NumericalOperation.UNIT_CONVERSION,
            [value("value", "1", unit="widgets")],
            output_unit="boxes",
        )
    )
    assert mismatch.audit_status == AuditStatus.MISMATCHED_UNITS
    assert unsupported.audit_status == AuditStatus.UNSUPPORTED_CONVERSION


def test_invalid_decimal_and_rounding_inputs_are_rejected():
    with pytest.raises(ValueError):
        value("numerator", "NaN")
    with pytest.raises(ValueError):
        RoundingRule(quantum="0")
    with pytest.raises(ValueError):
        RoundingRule(mode="ROUND_RANDOM")


def test_workflow_service_appends_auditable_records_without_float_recomputation():
    raw = candidate(
        NumericalOperation.PERCENTAGE,
        [value("numerator", "2"), value("denominator", "5")],
    ).model_dump(mode="json")
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        scores=ScoreBundle(methodology_version="1.0"),
        numerical_candidates=[raw],
    )
    result = asyncio.run(NumericalAuditor().process(state))

    assert len(result.calculations) == 1
    assert result.calculations[0].result["value"] == "40.0"
    assert result.calculations[0].inputs["values"][1]["role"] == "denominator"


def test_numerical_audit_requires_scoring_results():
    state = VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
    )

    with pytest.raises(WorkflowExtensionError) as caught:
        asyncio.run(NumericalAuditor().process(state))

    assert caught.value.code == "NUMERICAL_AUDIT_SCORES_REQUIRED"
