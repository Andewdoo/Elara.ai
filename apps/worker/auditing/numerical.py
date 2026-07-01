"""Reproducible numerical audits over model-identified candidate values.

Candidate extraction is intentionally separate from this module. Every value is
treated as untrusted input and must pass deterministic unit, period, denominator,
conflict, and Decimal validation before a result can pass.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import (
    Context,
    Decimal,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    localcontext,
)
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from graph.state import CalculationRecord, VerificationState


DECIMAL_CONTEXT = Context(prec=28, rounding=ROUND_HALF_UP)
ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_UP": ROUND_UP,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_FLOOR": ROUND_FLOOR,
}


class NumericalOperation(StrEnum):
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    TOTAL = "total"
    COMPARISON = "comparison"
    UNIT_CONVERSION = "unit_conversion"


class AuditStatus(StrEnum):
    PASSED = "passed"
    INVALID_INPUT = "invalid_input"
    MISSING_DENOMINATOR = "missing_denominator"
    ZERO_DENOMINATOR = "zero_denominator"
    MISMATCHED_UNITS = "mismatched_units"
    PERIOD_MISMATCH = "period_mismatch"
    SOURCE_VALUE_CONFLICT = "source_value_conflict"
    UNSUPPORTED_CONVERSION = "unsupported_conversion"


class NumericalInput(BaseModel):
    """One source-backed operand. Decimal is parsed from a string, never float math."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: str = Field(min_length=1, max_length=50)
    value: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=100)
    period: str | None = Field(default=None, max_length=200)
    source_ref: str | None = Field(default=None, max_length=128)

    @field_validator("value")
    @classmethod
    def finite_decimal_string(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("value must be a Decimal-compatible string") from exc
        if not parsed.is_finite():
            raise ValueError("value must be finite")
        return value


class RoundingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantum: str = Field(default="0.01", min_length=1, max_length=50)
    mode: str = "ROUND_HALF_UP"

    @field_validator("quantum")
    @classmethod
    def positive_quantum(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("rounding quantum must be a Decimal-compatible string") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError("rounding quantum must be positive and finite")
        return value

    @field_validator("mode")
    @classmethod
    def supported_mode(cls, value: str) -> str:
        if value not in ROUNDING_MODES:
            raise ValueError("unsupported Decimal rounding mode")
        return value


class NumericalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_ref: str = Field(min_length=1, max_length=128)
    claim_ref: str | None = Field(default=None, max_length=64)
    operation: NumericalOperation
    inputs: list[NumericalInput] = Field(min_length=1)
    output_unit: str | None = Field(default=None, max_length=100)
    claimed_value: str | None = Field(default=None, max_length=200)
    rounding: RoundingRule | None = None

    @field_validator("claimed_value")
    @classmethod
    def valid_claimed_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("claimed_value must be a Decimal-compatible string") from exc
        if not parsed.is_finite():
            raise ValueError("claimed_value must be finite")
        return value

    @model_validator(mode="after")
    def operation_shape(self) -> "NumericalCandidate":
        roles = [item.role for item in self.inputs]
        if self.operation in {NumericalOperation.PERCENTAGE, NumericalOperation.RATIO}:
            if "numerator" not in roles:
                raise ValueError("percentage and ratio require a numerator")
        elif self.operation == NumericalOperation.COMPARISON:
            if "current" not in roles:
                raise ValueError("comparison requires a current value")
        elif self.operation == NumericalOperation.UNIT_CONVERSION:
            if len(self.inputs) != 1 or not self.inputs[0].unit or not self.output_unit:
                raise ValueError("unit conversion requires one unit-bearing input and output_unit")
        return self


# canonical unit -> (dimension, multiplier to the dimension base unit)
_UNITS: dict[str, tuple[str, Decimal]] = {
    "mm": ("length", Decimal("0.001")),
    "cm": ("length", Decimal("0.01")),
    "m": ("length", Decimal("1")),
    "km": ("length", Decimal("1000")),
    "mg": ("mass", Decimal("0.001")),
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "ml": ("volume", Decimal("0.001")),
    "l": ("volume", Decimal("1")),
    "s": ("time", Decimal("1")),
    "min": ("time", Decimal("60")),
    "h": ("time", Decimal("3600")),
    "day": ("time", Decimal("86400")),
}
_ALIASES = {
    "millimeter": "mm", "millimeters": "mm", "centimeter": "cm", "centimeters": "cm",
    "meter": "m", "meters": "m", "metre": "m", "metres": "m",
    "kilometer": "km", "kilometers": "km", "kilometre": "km", "kilometres": "km",
    "milligram": "mg", "milligrams": "mg", "gram": "g", "grams": "g",
    "kilogram": "kg", "kilograms": "kg", "milliliter": "ml", "milliliters": "ml",
    "litre": "l", "litres": "l", "liter": "l", "liters": "l",
    "second": "s", "seconds": "s", "minute": "min", "minutes": "min",
    "hour": "h", "hours": "h", "days": "day",
}


def _unit(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return _ALIASES.get(normalized, normalized)


def _convert(value: Decimal, source: str, target: str) -> Decimal:
    source_definition = _UNITS.get(_unit(source) or "")
    target_definition = _UNITS.get(_unit(target) or "")
    if source_definition is None or target_definition is None:
        raise LookupError("unsupported unit conversion")
    if source_definition[0] != target_definition[0]:
        raise TypeError("units measure different dimensions")
    return value * source_definition[1] / target_definition[1]


class NumericalAuditor:
    def audit(self, candidate: NumericalCandidate | dict[str, Any]) -> CalculationRecord:
        candidate = NumericalCandidate.model_validate(candidate)
        formula = _formula(candidate.operation)
        serialized_inputs = {
            "candidate_ref": candidate.candidate_ref,
            "operation": candidate.operation.value,
            "values": [item.model_dump(mode="json") for item in candidate.inputs],
            "output_unit": candidate.output_unit,
            "claimed_value": candidate.claimed_value,
            "rounding": candidate.rounding.model_dump() if candidate.rounding else None,
        }
        status, issues = self._preflight(candidate)
        result: dict[str, Any] = {"value": None, "issues": issues}
        units = candidate.output_unit
        if status == AuditStatus.PASSED:
            try:
                value, units, extra = self._compute(candidate)
                unrounded = value
                if candidate.rounding is not None:
                    value = value.quantize(
                        Decimal(candidate.rounding.quantum),
                        rounding=ROUNDING_MODES[candidate.rounding.mode],
                    )
                result = {
                    "value": str(value),
                    "unrounded_value": str(unrounded),
                    "claimed_value": candidate.claimed_value,
                    "matches_claim": (
                        value == Decimal(candidate.claimed_value)
                        if candidate.claimed_value is not None
                        else None
                    ),
                    "issues": [],
                    **extra,
                }
            except ZeroDivisionError:
                status, result = AuditStatus.ZERO_DENOMINATOR, {
                    "value": None, "issues": [AuditStatus.ZERO_DENOMINATOR.value]
                }
            except TypeError:
                status, result = AuditStatus.MISMATCHED_UNITS, {
                    "value": None, "issues": [AuditStatus.MISMATCHED_UNITS.value]
                }
            except LookupError:
                status, result = AuditStatus.UNSUPPORTED_CONVERSION, {
                    "value": None, "issues": [AuditStatus.UNSUPPORTED_CONVERSION.value]
                }
            except (InvalidOperation, ArithmeticError):
                status, result = AuditStatus.INVALID_INPUT, {
                    "value": None, "issues": [AuditStatus.INVALID_INPUT.value]
                }
        return CalculationRecord(
            calculation_ref=str(uuid4()),
            formula_name=f"numerical_{candidate.operation.value}",
            formula_text=formula,
            inputs=serialized_inputs,
            result=result,
            units=units,
            decimal_context={
                "precision": DECIMAL_CONTEXT.prec,
                "rounding": DECIMAL_CONTEXT.rounding,
                "applied_rounding": (
                    candidate.rounding.model_dump() if candidate.rounding else None
                ),
            },
            audit_status=status.value,
            claim_ref=candidate.claim_ref,
        )

    async def process(self, state: VerificationState) -> VerificationState:
        calculations = list(state.calculations)
        candidates = list(state.numerical_candidates)
        # Extraction/model adapters may attach candidates to exact passages. They
        # remain untrusted and receive the same strict validation as state inputs.
        for passage in state.passages:
            attached = passage.metadata.get("numerical_candidates", [])
            if isinstance(attached, list):
                candidates.extend(item for item in attached if isinstance(item, dict))
        for candidate in candidates:
            try:
                calculations.append(self.audit(candidate))
            except ValueError as exc:
                raw = candidate if isinstance(candidate, dict) else {}
                calculations.append(
                    CalculationRecord(
                        calculation_ref=str(uuid4()),
                        formula_name="numerical_invalid_candidate",
                        formula_text="candidate validation",
                        inputs={"candidate": raw},
                        result={"value": None, "issues": [str(exc)]},
                        units=None,
                        decimal_context={
                            "precision": DECIMAL_CONTEXT.prec,
                            "rounding": DECIMAL_CONTEXT.rounding,
                            "applied_rounding": None,
                        },
                        audit_status=AuditStatus.INVALID_INPUT.value,
                        claim_ref=raw.get("claim_ref") if isinstance(raw, dict) else None,
                    )
                )
        return state.model_copy(update={"calculations": calculations})

    def _preflight(self, candidate: NumericalCandidate) -> tuple[AuditStatus, list[str]]:
        by_role: dict[str, list[NumericalInput]] = defaultdict(list)
        for item in candidate.inputs:
            by_role[item.role].append(item)
        if candidate.operation in {
            NumericalOperation.PERCENTAGE,
            NumericalOperation.RATIO,
            NumericalOperation.COMPARISON,
        } and not ({"denominator", "baseline"} & by_role.keys()):
            return AuditStatus.MISSING_DENOMINATOR, [AuditStatus.MISSING_DENOMINATOR.value]

        for values in by_role.values():
            if len(values) > 1 and len({(item.value, _unit(item.unit), item.period) for item in values}) > 1:
                return AuditStatus.SOURCE_VALUE_CONFLICT, [AuditStatus.SOURCE_VALUE_CONFLICT.value]

        periods = {item.period for item in candidate.inputs if item.period is not None}
        if len(periods) > 1 or (periods and any(item.period is None for item in candidate.inputs)):
            return AuditStatus.PERIOD_MISMATCH, [AuditStatus.PERIOD_MISMATCH.value]

        if candidate.operation in {
            NumericalOperation.PERCENTAGE,
            NumericalOperation.RATIO,
            NumericalOperation.TOTAL,
            NumericalOperation.COMPARISON,
        }:
            units = {_unit(item.unit) for item in candidate.inputs}
            if len(units) > 1:
                return AuditStatus.MISMATCHED_UNITS, [AuditStatus.MISMATCHED_UNITS.value]
        return AuditStatus.PASSED, []

    def _compute(
        self, candidate: NumericalCandidate
    ) -> tuple[Decimal, str | None, dict[str, Any]]:
        by_role = {item.role: item for item in candidate.inputs}
        values = [Decimal(item.value) for item in candidate.inputs]
        with localcontext(DECIMAL_CONTEXT):
            if candidate.operation == NumericalOperation.PERCENTAGE:
                denominator = Decimal(by_role["denominator"].value)
                if denominator == 0:
                    raise ZeroDivisionError
                return Decimal(by_role["numerator"].value) / denominator * 100, "%", {
                    "denominator": str(denominator)
                }
            if candidate.operation == NumericalOperation.RATIO:
                denominator = Decimal(by_role["denominator"].value)
                if denominator == 0:
                    raise ZeroDivisionError
                return Decimal(by_role["numerator"].value) / denominator, "ratio", {
                    "denominator": str(denominator)
                }
            if candidate.operation == NumericalOperation.TOTAL:
                return sum(values, Decimal("0")), _unit(candidate.inputs[0].unit), {}
            if candidate.operation == NumericalOperation.COMPARISON:
                baseline_input = by_role.get("baseline") or by_role.get("denominator")
                assert baseline_input is not None
                baseline = Decimal(baseline_input.value)
                current = Decimal(by_role["current"].value)
                if baseline == 0:
                    raise ZeroDivisionError
                difference = current - baseline
                return difference / baseline * 100, "%", {
                    "absolute_difference": str(difference), "denominator": str(baseline)
                }
            source = candidate.inputs[0]
            assert source.unit is not None and candidate.output_unit is not None
            converted = _convert(Decimal(source.value), source.unit, candidate.output_unit)
            return converted, _unit(candidate.output_unit), {
                "conversion": f"{_unit(source.unit)}->{_unit(candidate.output_unit)}"
            }
        raise AssertionError("unhandled numerical operation")


def _formula(operation: NumericalOperation) -> str:
    return {
        NumericalOperation.PERCENTAGE: "(numerator / denominator) * 100",
        NumericalOperation.RATIO: "numerator / denominator",
        NumericalOperation.TOTAL: "sum(values)",
        NumericalOperation.COMPARISON: "((current - baseline) / baseline) * 100",
        NumericalOperation.UNIT_CONVERSION: "value * source_factor / target_factor",
    }[operation]


__all__ = [
    "AuditStatus",
    "DECIMAL_CONTEXT",
    "NumericalAuditor",
    "NumericalCandidate",
    "NumericalInput",
    "NumericalOperation",
    "RoundingRule",
]
