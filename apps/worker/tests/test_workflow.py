import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.deepseek_client import (
    CallMetadata,
    DeepSeekUnavailableError,
    ProviderErrorMetadata,
    StructuredResponse,
)
from agents.decomposition import normalize_decomposition
from agents.evidence_classification import build_classification_tasks, classification_task_ref
from agents.schemas import (
    AtomicClaimOutput,
    CitedReportSentenceOutput,
    CitationAuditOutput,
    ClaimAmbiguityOutput,
    ClaimKind,
    DecompositionDraftOutput,
    DecompositionOutput,
    EvidenceClassificationItemOutput,
    FactCheckability,
    Importance,
    InputKind,
    IntakeClassificationOutput,
    PlanningOutput,
    SynthesisOutput,
    SynthesisDraftOutput,
)
from agents.validation import validate_research_plan
from app.database.base import Base
from app.config import Settings
from app.models import (
    AccessStatus,
    AtomicClaim,
    InputType,
    ReportCitation,
    RunStatus,
    SearchQuery,
    Source,
    SourcePassage,
    SourceSnapshot,
    SourceType,
    User,
    VerificationRun,
)
from app.services.reports import build_report
from app.services.run_lifecycle import persist_completed_run
from graph.state import (
    CalculationRecord,
    CandidateSource,
    ClaimScoreRecord,
    PassageRecord,
    ResearchDepth,
    ScoreBundle,
    SnapshotRecord,
    VerificationState,
    WorkflowStage,
)
from graph.transitions import citation_audit_ready, evidence_ready, synthesis_ready
from graph.workflow import (
    WorkflowExtensions,
    WorkflowNodes,
    WorkflowServices,
    _guard_citation_audit,
    _build_deterministic_report,
    build_workflow,
)
from research.extension_errors import WorkflowExtensionError
from graph.runtime import (
    SqlWorkflowStateWriter,
    execute_planning_workflow,
    execute_verification_workflow,
)


class FakeModel:
    def __init__(
        self,
        outputs: list[dict[str, object]],
        *,
        attempt_counts: list[int] | None = None,
    ) -> None:
        self.outputs = outputs
        self.attempt_counts = attempt_counts or []
        self.calls: list[dict[str, object]] = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        output = kwargs["output_schema"].model_validate(self.outputs.pop(0))
        return StructuredResponse(
            output=output,
            metadata=CallMetadata(
                model="deepseek-chat",
                prompt_version=kwargs["prompt_version"],
                temperature=kwargs["temperature"],
                latency_ms=5,
                attempt_count=self.attempt_counts.pop(0) if self.attempt_counts else 1,
            ),
        )


class FailingModel:
    async def generate_structured(self, **_kwargs):
        raise DeepSeekUnavailableError(
            "provider unavailable",
            metadata=ProviderErrorMetadata(
                model="deepseek-chat",
                prompt_version="intake-v1",
                temperature=0,
                latency_ms=5,
                status_code=503,
                error_code="provider_unavailable",
                retryable=True,
            ),
        )


class RecordingProgress:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def publish(self, **event: object) -> None:
        self.events.append(event)


class RecordingStateWriter:
    def __init__(self) -> None:
        self.saved: list[tuple[WorkflowStage, VerificationState]] = []

    async def save(self, *, stage: WorkflowStage, state: VerificationState) -> None:
        self.saved.append((stage, state))


class Cancellation:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled

    async def is_cancelled(self, _run_id) -> bool:
        return self.cancelled


def state() -> VerificationState:
    return VerificationState(
        run_id=uuid4(),
        user_id=uuid4(),
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
    )


def test_report_states_supported_with_an_unresolved_interpretation_without_model_text():
    value = state().model_copy(
        update={
            "claims": [
                AtomicClaimOutput(
                    claim_ref="meta",
                    text="Meta stock price surpasses $600",
                    claim_kind=ClaimKind.NUMERICAL,
                    importance=Importance.ESSENTIAL,
                    importance_weight=3,
                    fact_checkability=FactCheckability.FACT_CHECKABLE,
                    verification_scope="Verify the price milestone.",
                )
            ],
            "claim_ambiguities": [
                ClaimAmbiguityOutput(
                    claim_ref="meta",
                    text="raw model ambiguity that must not enter the report wording",
                )
            ],
            "claim_scores": [
                ClaimScoreRecord(
                    claim_ref="meta",
                    supporting_weight=Decimal("1"),
                    contradicting_weight=Decimal("0"),
                    total_adjusted_evidence=Decimal("1"),
                    evidence_support=100,
                    evidence_consistency=100,
                    verdict_confidence=75,
                    context_completeness=100,
                    average_quality=100,
                    adequate_evidence=True,
                    final_label="Supported",
                )
            ],
            "calculations": [
                CalculationRecord(
                    calculation_ref="ambiguity-gate-meta",
                    formula_name="ambiguity_gate",
                    formula_text="test gate",
                    inputs={},
                    result={"non_blocking": True},
                    units="gate_decision",
                    decimal_context={"precision": 28, "rounding": "ROUND_HALF_UP"},
                    audit_status="non_blocking",
                    claim_ref="meta",
                )
            ],
        }
    )
    report = _build_deterministic_report(
        value,
        SynthesisDraftOutput.model_validate(
            {
                "summary_sentences": [
                    {
                        "sentence_ref": "summary-1",
                        "text": "Approved evidence supports the price milestone.",
                        "passage_ids": ["passage-1"],
                    }
                ]
            }
        ),
        approved_passage_ids={"passage-1"},
        evidence_reviewed_at=datetime(2026, 7, 19, tzinfo=UTC),
        evidence_timestamp="Evidence reviewed as of 2026-07-19T00:00:00+00:00.",
        model_versions={},
        prompt_versions={},
    )

    assert report.limitations[1] == (
        "Claim meta is supported with an unresolved interpretation "
        "(1 claim-local limitation(s)); accepted evidence was adequate and unopposed."
    )
    assert "raw model ambiguity" not in " ".join(report.limitations)


INTAKE = {
    "input_kind": "claim",
    "normalized_text": "Company X doubled net income in Q1 2026.",
    "detected_language": "English",
    "fact_checkability": "fact_checkable",
    "claim_kinds": ["numerical"],
    "entities": [{"name": "Company X", "entity_type": "company"}],
}
DECOMPOSITION = {
    "atomic_claims": [
        {
            "claim_ref": "claim-1",
            "text": "Company X doubled net income in Q1 2026.",
            "claim_kind": "numerical",
            "importance": "essential",
            "importance_weight": 3,
            "fact_checkability": "fact_checkable",
            "verification_scope": "Compare Q1 net income with the same prior-period metric.",
        }
    ]
}
DECOMPOSITION_DRAFT = {
    "atomic_claims": [
        {
            "text": "Company X doubled net income in Q1 2026.",
            "claim_kind": "numerical",
            "importance": "essential",
            "importance_weight": 3,
            "fact_checkability": "fact_checkable",
            "verification_scope": "Compare Q1 net income with the same prior-period metric.",
        }
    ]
}
GENERATED_CLAIM_REF = normalize_decomposition(
    DecompositionDraftOutput.model_validate(DECOMPOSITION_DRAFT),
    normalized_text=INTAKE["normalized_text"],
    claim_limit=25,
).atomic_claims[0].claim_ref
PLAN = {
    "objectives": [
        {
            "objective_ref": "objective-1",
            "claim_ref": "claim-1",
            "intent": "primary",
            "target": "Locate the original quarterly filing.",
        },
        {
            "objective_ref": "objective-2",
            "claim_ref": "claim-1",
            "intent": "contradiction",
            "target": "Locate corrections or contradictory records.",
        },
    ],
    "queries": [
        {
            "query": "Company X Q1 2026 net income filing",
            "objective_ref": "objective-1",
            "intent": "primary",
        },
        {
            "query": "Company X Q1 2026 net income correction",
            "objective_ref": "objective-2",
            "intent": "contradiction",
        },
    ],
}


DRAFT_PLAN = {
    "objectives": [
        {
            "claim_ref": "claim-1",
            "intent": "primary",
            "target": "Locate the original quarterly filing.",
            "queries": [{"query": "Company X Q1 2026 net income filing"}],
        },
        {
            "claim_ref": "claim-1",
            "intent": "contradiction",
            "target": "Locate corrections or contradictory records.",
            "queries": [{"query": "Company X Q1 2026 net income correction"}],
        },
    ]
}
DRAFT_PLAN_FOR_GENERATED_CLAIMS = deepcopy(DRAFT_PLAN)
for _objective in DRAFT_PLAN_FOR_GENERATED_CLAIMS["objectives"]:
    _objective["claim_ref"] = GENERATED_CLAIM_REF


def test_planner_normalizes_draft_and_validates_contract():
    workflow_state = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE, "claims": DECOMPOSITION["atomic_claims"]}
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=FakeModel([DRAFT_PLAN]), submitted_input="synthetic public claim")
        ).planner(workflow_state)
    )

    assert result.recoverable_errors == []
    assert result.objectives[0].objective_ref.startswith("obj-")
    assert result.queries[0].objective_ref == result.objectives[0].objective_ref
    assert result.queries[0].intent == result.objectives[0].intent
    assert result.model_calls[WorkflowStage.PLANNER.value].prompt_version == "planner-v2"


def test_planner_sends_v2_contract_payload_without_exact_quote_when_inapplicable():
    workflow_state = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE, "claims": DECOMPOSITION["atomic_claims"]}
    )
    model = FakeModel([DRAFT_PLAN])

    result = asyncio.run(
        WorkflowNodes(WorkflowServices(model=model, submitted_input="synthetic public claim")).planner(
            workflow_state
        )
    )

    call = model.calls[0]
    payload = json.loads(call["messages"][1]["content"])
    system_prompt = " ".join(call["messages"][0]["content"].split())
    assert call["output_schema"].__name__ == "PlanningDraftOutput"
    assert call["prompt_version"] == "planner-v2"
    for phrase in (
        "untrusted evidence/data",
        "primary and contradiction",
        "allowed_claim_refs",
        "inherit that objective's intent",
        "case-folding and collapsing whitespace",
        "truth decisions, score, browse, request or use credentials, or provide private reasoning",
    ):
        assert phrase in system_prompt
    assert set(payload) == {
        "claims",
        "allowed_claim_refs",
        "research_depth",
        "max_query_count",
        "required_intents_by_claim",
        "requires_attribution_check",
    }
    assert payload["allowed_claim_refs"] == ["claim-1"]
    assert payload["research_depth"] == "STANDARD"
    assert payload["max_query_count"] == 60
    assert payload["required_intents_by_claim"] == {
        "claim-1": ["primary", "contradiction"]
    }
    assert payload["requires_attribution_check"] is False
    assert result.recoverable_errors == []


def test_planner_rejects_unknown_draft_claim_ref_with_stable_diagnostics():
    invalid_draft = deepcopy(DRAFT_PLAN)
    invalid_draft["objectives"][0]["claim_ref"] = "unknown-claim"
    workflow_state = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE, "claims": DECOMPOSITION["atomic_claims"]}
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([invalid_draft, invalid_draft]),
                submitted_input="synthetic public claim",
            )
        ).planner(workflow_state)
    )

    assert result.recoverable_errors[-1].code == "AGENT_CONTRACT_REPAIR_EXHAUSTED"
    assert result.recoverable_errors[-1].details == {
        "primary_violation": "PLAN_UNKNOWN_CLAIM_REF",
        "violation_count": 1,
        "repair_attempted": True,
        "semantic_validation_attempt_count": 2,
        "semantic_repair_attempt_count": 1,
        "violation_summary": "PLAN_UNKNOWN_CLAIM_REF",
    }


def test_planner_repairs_one_semantically_invalid_plan_without_replaying_model_content():
    raw_response_marker = "planner-raw-response-marker-not-for-telemetry"
    invalid_plan = deepcopy(DRAFT_PLAN)
    invalid_plan["objectives"][0]["queries"][0]["query"] = raw_response_marker
    invalid_plan["objectives"][1]["queries"][0]["query"] = raw_response_marker.upper()
    workflow_state = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE, "claims": DECOMPOSITION["atomic_claims"]}
    )
    progress = RecordingProgress()
    model = FakeModel([invalid_plan, DRAFT_PLAN], attempt_counts=[2, 1])

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=model,
                submitted_input="synthetic public claim",
                progress=progress,
            )
        ).planner(workflow_state)
    )

    assert result.recoverable_errors == []
    assert len(model.calls) == 2
    assert model.calls[0]["repair_invalid_response"] is True
    assert model.calls[1]["repair_invalid_response"] is False
    corrective_instruction = model.calls[1]["messages"][1]["content"]
    assert "PLAN_DUPLICATE_QUERY" in corrective_instruction
    assert "claim-1" in corrective_instruction
    assert raw_response_marker not in corrective_instruction
    assert progress.events[-1]["payload"].get("semantic_validation_attempt_count") == 2
    assert progress.events[-1]["payload"].get("semantic_repair_attempt_count") == 1
    assert raw_response_marker not in str(progress.events)


def planner_contract_cases() -> list[tuple[str, dict[str, object], dict[str, object]]]:
    """Pydantic-valid plans that characterize each workflow-only planner guard."""
    cases: list[tuple[str, dict[str, object], dict[str, object]]] = [
        ("valid_control", deepcopy(PLAN), {}),
    ]

    duplicate_objective = deepcopy(PLAN)
    duplicate_objective["objectives"].insert(
        1,
        {
            "objective_ref": "objective-1",
            "claim_ref": "claim-1",
            "intent": "primary",
            "target": "Locate an additional original filing.",
        },
    )
    cases.append(("duplicate_objective_ref", duplicate_objective, {}))

    unknown_claim = deepcopy(PLAN)
    unknown_claim["objectives"].append(
        {
            "objective_ref": "objective-3",
            "claim_ref": "unknown-claim",
            "intent": "support",
            "target": "Locate a supporting record.",
        }
    )
    unknown_claim["queries"].append(
        {
            "query": "Company X supporting record",
            "objective_ref": "objective-3",
            "intent": "support",
        }
    )
    cases.append(("unknown_claim_ref", unknown_claim, {}))

    missing_coverage = deepcopy(PLAN)
    missing_claim = {
        **DECOMPOSITION["atomic_claims"][0],
        "claim_ref": "claim-2",
        "text": "Company X renamed a product in Q1 2026.",
        "fact_checkability": "not_fact_checkable",
    }
    cases.append(
        (
            "missing_claim_coverage",
            missing_coverage,
            {"claims": [*DECOMPOSITION["atomic_claims"], missing_claim]},
        )
    )

    extra_coverage = deepcopy(unknown_claim)
    cases.append(("extra_claim_coverage", extra_coverage, {}))

    query_limit = deepcopy(PLAN)
    query_limit["queries"].extend(
        {
            "query": f"Company X Q1 2026 primary filing {index}",
            "objective_ref": "objective-1",
            "intent": "primary",
        }
        for index in range(59)
    )
    cases.append(("query_limit", query_limit, {}))

    duplicate_query = deepcopy(PLAN)
    duplicate_query["queries"][1]["query"] = "  COMPANY x q1 2026 NET income FILING  "
    cases.append(("duplicate_normalized_query", duplicate_query, {}))

    primary_missing = deepcopy(PLAN)
    primary_missing["objectives"][0]["intent"] = "support"
    primary_missing["queries"][0]["intent"] = "support"
    cases.append(("missing_primary_path", primary_missing, {}))

    contradiction_missing = deepcopy(PLAN)
    contradiction_missing["objectives"][1]["intent"] = "support"
    contradiction_missing["queries"][1]["intent"] = "support"
    cases.append(("missing_contradiction_path", contradiction_missing, {}))

    attribution_missing = deepcopy(PLAN)
    attribution_input = {**INTAKE, "requires_attribution_check": True}
    cases.append(
        ("missing_attribution_path", attribution_missing, {"normalized_input": attribution_input})
    )

    exact_quote_missing = deepcopy(PLAN)
    quote_input = {
        **INTAKE,
        "input_kind": "quote",
        "normalized_text": "This synthetic statement must be searched verbatim.",
    }
    cases.append(("missing_exact_quote", exact_quote_missing, {"normalized_input": quote_input}))

    intent_mismatch = deepcopy(PLAN)
    intent_mismatch["queries"].append(
        {
            "query": "Company X Q1 2026 supporting context",
            "objective_ref": "objective-1",
            "intent": "support",
        }
    )
    cases.append(("query_objective_intent_mismatch", intent_mismatch, {}))
    return cases


@pytest.mark.skip(reason="Planning drafts cannot supply persisted objective references or query intents.")
@pytest.mark.parametrize(("case_name", "plan", "updates"), planner_contract_cases())
def test_planner_reports_stable_contract_diagnostics_for_pydantic_valid_plans(
    case_name: str, plan: dict[str, object], updates: dict[str, object]
):
    """Freeze the generic v1 failure until Prompt 2 extracts precise validators."""
    PlanningOutput.model_validate(plan)
    workflow_state = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            **updates,
        }
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=FakeModel([plan]), submitted_input="synthetic public claim")
        ).planner(workflow_state)
    )

    expected_primary_violations = {
        "duplicate_objective_ref": "PLAN_DUPLICATE_OBJECTIVE_REF",
        "unknown_claim_ref": "PLAN_EXTRA_CLAIM_COVERAGE",
        "missing_claim_coverage": "PLAN_MISSING_CLAIM_COVERAGE",
        "extra_claim_coverage": "PLAN_EXTRA_CLAIM_COVERAGE",
        "query_limit": "PLAN_QUERY_LIMIT_EXCEEDED",
        "duplicate_normalized_query": "PLAN_DUPLICATE_QUERY",
        "missing_primary_path": "PLAN_PRIMARY_PATH_MISSING",
        "missing_contradiction_path": "PLAN_CONTRADICTION_PATH_MISSING",
        "missing_attribution_path": "PLAN_ATTRIBUTION_PATH_MISSING",
        "missing_exact_quote": "PLAN_EXACT_QUOTE_PATH_MISSING",
        "query_objective_intent_mismatch": "PLAN_INTENT_MISMATCH",
    }
    if case_name == "valid_control":
        assert result.recoverable_errors == []
        assert WorkflowStage.PLANNER in result.completed_stages
    else:
        assert result.recoverable_errors[-1].code == "INVALID_RESEARCH_PLAN"
        assert result.recoverable_errors[-1].details["primary_violation"] == expected_primary_violations[case_name]
        assert result.recoverable_errors[-1].details["violation_count"] == len(
            validate_research_plan(workflow_state, PlanningOutput.model_validate(plan))
        )
        assert result.recoverable_errors[-1].details["repair_attempted"] is False
        assert WorkflowStage.PLANNER not in result.completed_stages


def test_planner_failure_event_contains_only_stable_diagnostics():
    raw_claim = "Raw claim text must never appear in a planner failure event."
    raw_query = "Raw query text must never appear in a planner failure event."
    invalid_plan = deepcopy(DRAFT_PLAN)
    invalid_plan["objectives"][0]["queries"].append(
        {"query": f"  {raw_query.upper()}  "}
    )
    invalid_plan["objectives"][1]["queries"][0]["query"] = raw_query
    workflow_state = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": {**INTAKE, "normalized_text": raw_claim},
            "claims": DECOMPOSITION["atomic_claims"],
        }
    )
    progress = RecordingProgress()

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([invalid_plan, invalid_plan]),
                submitted_input=raw_claim,
                progress=progress,
            )
        ).planner(workflow_state)
    )

    event = progress.events[-1]
    details = event["payload"]["details"]
    assert result.recoverable_errors[-1].code == "AGENT_CONTRACT_REPAIR_EXHAUSTED"
    assert details == {
        "primary_violation": "PLAN_DUPLICATE_QUERY",
        "violation_count": 1,
        "repair_attempted": True,
        "semantic_validation_attempt_count": 2,
        "semantic_repair_attempt_count": 1,
        "violation_summary": "PLAN_DUPLICATE_QUERY",
    }
    assert raw_claim not in str(event)
    assert raw_query not in str(event)


def test_planning_workflow_is_typed_and_persists_public_progress():
    progress = RecordingProgress()
    writer = RecordingStateWriter()
    model = FakeModel([INTAKE, DECOMPOSITION_DRAFT, DRAFT_PLAN_FOR_GENERATED_CLAIMS])
    workflow = build_workflow(
        WorkflowServices(
            model=model,
            submitted_input="Company X doubled net income in Q1 2026.",
            progress=progress,
            state_writer=writer,
        ),
        planning_only=True,
    )

    result = VerificationState.model_validate(asyncio.run(workflow.ainvoke(state())))

    assert result.claims[0].claim_ref == GENERATED_CLAIM_REF
    assert result.queries[0].objective_ref.startswith("obj-")
    assert result.completed_stages == [
        WorkflowStage.INTAKE,
        WorkflowStage.DECOMPOSITION,
        WorkflowStage.PLANNER,
    ]
    assert [call["prompt_version"] for call in model.calls] == [
        "intake-v2",
        "decomposition-v3",
        "planner-v2",
    ]
    assert len(writer.saved) == 3
    assert all("reasoning" not in str(event).lower() for event in progress.events)
    assert progress.events[0]["payload"] == {"completed_steps": 0, "total_steps": 13}
    assert progress.events[-1]["payload"]["completed_steps"] == 3


def test_state_forbids_private_reasoning_fields():
    with pytest.raises(ValidationError):
        VerificationState.model_validate(
            {**state().model_dump(), "private_reasoning": "must not be stored"}
        )
    with pytest.raises(ValidationError):
        VerificationState.model_validate(
            {**state().model_dump(), "started_at": "2026-06-29T12:00:00"}
        )


def test_intake_sends_immutable_expected_input_kind_and_accepts_matching_kind():
    model = FakeModel([INTAKE])
    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=model,
                submitted_input="A claim",
                expected_input_kind=InputKind.CLAIM,
            )
        ).intake(state())
    )

    payload = json.loads(model.calls[0]["messages"][1]["content"])
    system_prompt = " ".join(model.calls[0]["messages"][0]["content"].split())
    assert model.calls[0]["prompt_version"] == "intake-v2"
    assert payload == {"submitted_input": "A claim", "expected_input_kind": "claim"}
    assert "expected_input_kind is immutable task context" in system_prompt
    assert result.normalized_input is not None
    assert result.normalized_input.input_kind == InputKind.CLAIM


def test_intake_rejects_model_input_type_drift_with_stable_details():
    drifted = {**INTAKE, "input_kind": "article_text"}
    progress = RecordingProgress()
    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([drifted]),
                submitted_input="A claim",
                expected_input_kind=InputKind.CLAIM,
                progress=progress,
            )
        ).intake(state())
    )

    assert result.normalized_input is None
    assert result.recoverable_errors[0].code == "INPUT_TYPE_MISMATCH"
    assert progress.events[-1]["payload"]["details"] == {
        "expected_input_kind": "claim",
        "returned_input_kind": "article_text",
    }


@pytest.mark.parametrize(
    "submitted_url",
    [
        "ftp://example.test/report",
        "https:///missing-host",
        "https://user:password@example.test/report",
    ],
)
def test_intake_retains_deterministic_url_scheme_host_and_credential_guard(
    submitted_url: str,
):
    article_url_output = {
        **INTAKE,
        "input_kind": "article_url",
        "normalized_text": "https://model.example/rewritten",
    }

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([article_url_output]),
                submitted_input=submitted_url,
                expected_input_kind=InputKind.ARTICLE_URL,
            )
        ).intake(state())
    )

    assert result.normalized_input is None
    assert result.recoverable_errors[0].code == "INVALID_NORMALIZED_URL"


def test_intake_retains_submitted_safe_article_url_after_model_normalization():
    submitted_url = "https://example.test/report?year=2026"
    article_url_output = {
        **INTAKE,
        "input_kind": "article_url",
        "normalized_text": "https://model.example/rewritten",
    }

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([article_url_output]),
                submitted_input=submitted_url,
                expected_input_kind=InputKind.ARTICLE_URL,
            )
        ).intake(state())
    )

    assert result.normalized_input is not None
    assert result.normalized_input.normalized_text == submitted_url


def test_provider_failure_metadata_is_public_and_recoverable():
    progress = RecordingProgress()
    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FailingModel(),
                submitted_input="A claim",
                expected_input_kind=InputKind.CLAIM,
                progress=progress,
            )
        ).intake(state())
    )

    error = result.recoverable_errors[0]
    assert error.retryable is True
    assert progress.events[-1]["payload"]["details"] == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "status_code": 503,
        "error_code": "provider_unavailable",
    }


def test_decomposition_rejects_parent_cycles():
    cyclical = deepcopy(DECOMPOSITION_DRAFT)
    cyclical["atomic_claims"] = [
        {**DECOMPOSITION_DRAFT["atomic_claims"][0], "parent_claim_index": 1},
        {**DECOMPOSITION_DRAFT["atomic_claims"][0], "text": "Company X reported income in Q1 2026.", "parent_claim_index": 0},
    ]
    value = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE}
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=FakeModel([cyclical]), submitted_input="unused")
        ).decomposition(value)
    )

    assert result.recoverable_errors[0].code == "DECOMPOSITION_CLAIM_CYCLE"


def test_planner_requires_primary_and_contradiction_paths_per_claim():
    second_claim = {
        **DECOMPOSITION["atomic_claims"][0],
        "claim_ref": "claim-2",
        "text": "Demand increased in Q1 2026.",
    }
    incomplete_plan = deepcopy(DRAFT_PLAN)
    incomplete_plan["objectives"].append(
        {
            "claim_ref": "claim-2",
            "intent": "primary",
            "target": "Locate demand records.",
            "queries": [{"query": "Company X Q1 2026 demand records"}],
        }
    )
    value = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": [*DECOMPOSITION["atomic_claims"], second_claim],
        }
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([incomplete_plan, incomplete_plan]),
                submitted_input="unused",
            )
        ).planner(value)
    )

    assert result.recoverable_errors[0].code == "AGENT_CONTRACT_REPAIR_EXHAUSTED"


def test_cancellation_stops_before_model_call_and_is_persisted():
    model = FakeModel([])
    writer = RecordingStateWriter()
    workflow = build_workflow(
        WorkflowServices(
            model=model,
            submitted_input="A claim",
            cancellation=Cancellation(True),
            state_writer=writer,
        ),
        planning_only=True,
    )

    result = VerificationState.model_validate(asyncio.run(workflow.ainvoke(state())))

    assert result.cancelled is True
    assert model.calls == []
    assert writer.saved[0][1].cancelled is True


def test_evidence_guard_rejects_unknown_passage_reference():
    workflow_state = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            "passages": [
                PassageRecord(
                    passage_id="passage-1",
                    source_ref="source-1",
                    snapshot_id="snapshot-1",
                    text="Net income was 20, compared with 10.",
                    text_hash="hash-1",
                    extraction_certainty=Decimal("0.95"),
                )
            ],
        }
    )
    model = FakeModel(
        [
            {
                "classifications": [
                    {
                        "task_ref": classification_task_ref("claim-1", "invented-passage"),
                        "stance": "strongly_supports",
                        "quality": {
                            "relevance": 1,
                            "directness": 1,
                            "claim_specific_authority": 1,
                            "transparency": 1,
                            "temporal_fit": 1,
                            "extraction_certainty": 0.9,
                        },
                        "entity_match": True,
                        "time_period_match": True,
                    }
                ]
            }
        ]
    )

    result = asyncio.run(
        WorkflowNodes(WorkflowServices(model=model, submitted_input="unused")).evidence_classification(
            workflow_state
        )
    )

    assert result.evidence == []
    assert result.recoverable_errors[0].code == "CLASSIFICATION_COVERAGE_MISMATCH"


def _classification_judgment(task_ref: str) -> dict[str, object]:
    return {
        "task_ref": task_ref,
        "stance": "strongly_supports",
        "quality": {
            "relevance": 1,
            "directness": 1,
            "claim_specific_authority": 1,
            "transparency": 1,
            "temporal_fit": 1,
            "extraction_certainty": 1,
        },
        "entity_match": True,
        "time_period_match": True,
        "quotation_or_number_located": True,
    }


def test_evidence_classification_requires_exact_task_coverage_and_uses_v2_payload():
    passage_text = "The Q1 filing reports net income of 20, compared with 10."
    value = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            "passages": [
                {
                    "passage_id": "passage-1",
                    "source_ref": "source-1",
                    "snapshot_id": "snapshot-1",
                    "text": passage_text,
                    "text_hash": "hash-1",
                    "extraction_certainty": "0.95",
                },
                {
                    "passage_id": "passage-2",
                    "source_ref": "source-1",
                    "snapshot_id": "snapshot-1",
                    "text": "The filing is dated after the claim's reporting period.",
                    "text_hash": "hash-2",
                    "extraction_certainty": "0.95",
                },
            ],
        }
    )
    tasks = build_classification_tasks(
        value.claims, value.passages, research_depth=value.research_depth.value
    )
    model = FakeModel([{"classifications": [_classification_judgment(task.task_ref) for task in tasks]}])
    progress = RecordingProgress()

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=model, submitted_input="unused", progress=progress)
        ).evidence_classification(value)
    )

    payload = json.loads(model.calls[0]["messages"][1]["content"])
    assert model.calls[0]["prompt_version"] == "evidence-classification-v2"
    assert set(payload) == {"tasks"}
    assert [task["task_ref"] for task in payload["tasks"]] == [task.task_ref for task in tasks]
    assert {(item.claim_ref, item.passage_id) for item in result.evidence} == {
        (task.claim_ref, task.passage_id) for task in tasks
    }
    assert passage_text not in repr(progress.events)


@pytest.mark.parametrize(
    ("returned_task_refs", "expected_details"),
    [
        ([], {"missing_task_count": 1, "duplicate_task_count": 0, "unknown_task_count": 0}),
        ([("expected"), ("expected")], {"missing_task_count": 0, "duplicate_task_count": 1, "unknown_task_count": 0}),
        ([("unknown")], {"missing_task_count": 1, "duplicate_task_count": 0, "unknown_task_count": 1}),
        ([("expected"), ("unknown")], {"missing_task_count": 0, "duplicate_task_count": 0, "unknown_task_count": 1}),
    ],
    ids=["empty", "duplicate", "unknown", "extra"],
)
def test_evidence_classification_rejects_incomplete_or_undeclared_task_results(
    returned_task_refs: list[str], expected_details: dict[str, int]
):
    value = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            "passages": [
                {
                    "passage_id": "passage-1",
                    "source_ref": "source-1",
                    "snapshot_id": "snapshot-1",
                    "text": "The Q1 filing reports net income of 20, compared with 10.",
                    "text_hash": "hash-1",
                    "extraction_certainty": "0.95",
                }
            ],
        }
    )
    expected_ref = classification_task_ref("claim-1", "passage-1")
    unknown_ref = classification_task_ref("claim-1", "undeclared-passage")
    refs = [expected_ref if ref == "expected" else unknown_ref for ref in returned_task_refs]
    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([{"classifications": [_classification_judgment(ref) for ref in refs]}]),
                submitted_input="unused",
            )
        ).evidence_classification(value)
    )

    error = result.recoverable_errors[0]
    assert error.code == "CLASSIFICATION_COVERAGE_MISMATCH"
    assert {key: error.details[key] for key in expected_details} == expected_details


def test_evidence_guard_applies_deterministic_rejection_thresholds():
    value = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            "passages": [
                {
                    "passage_id": "passage-1",
                    "source_ref": "source-1",
                    "snapshot_id": "snapshot-1",
                    "text": "A related but different period is discussed.",
                    "text_hash": "hash-1",
                    "extraction_certainty": "0.60",
                }
            ],
        }
    )
    classification = {
        "classifications": [
            {
                "task_ref": classification_task_ref("claim-1", "passage-1"),
                "stance": "neutral_or_irrelevant",
                "quality": {
                    "relevance": 0.4,
                    "directness": 0.2,
                    "claim_specific_authority": 0.5,
                    "transparency": 0.5,
                    "temporal_fit": 0.2,
                    "extraction_certainty": 0.6,
                },
                "entity_match": False,
                "time_period_match": False,
                "quotation_or_number_located": False,
            }
        ]
    }

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=FakeModel([classification]), submitted_input="unused")
        ).evidence_classification(value)
    )

    assert result.evidence[0].recommended_rejection_reasons == [
        "relevance_below_threshold",
        "extraction_certainty_below_threshold",
        "entity_mismatch",
        "time_period_mismatch",
        "quotation_or_number_not_located",
    ]
    assert result.evidence[0].quality.extraction_certainty == 0.60


def test_evidence_guard_ignores_free_form_model_rejection_recommendations():
    value = VerificationState.model_validate(
        {
            **state().model_dump(),
            "normalized_input": INTAKE,
            "claims": DECOMPOSITION["atomic_claims"],
            "passages": [{"passage_id": "passage-1", "source_ref": "source-1",
                "snapshot_id": "snapshot-1", "text": "The filing confirms the claim.",
                "text_hash": "hash-1", "extraction_certainty": "0.99"}],
        }
    )
    classification = {"classifications": [{"task_ref": classification_task_ref("claim-1", "passage-1"),
        "stance": "strongly_supports",
        "quality": {"relevance": 1, "directness": 1,
            "claim_specific_authority": 1, "transparency": 1,
            "temporal_fit": 1, "extraction_certainty": 1},
        "explicit_support": "The filing confirms the claim.", "entity_match": True,
        "time_period_match": True, "quotation_or_number_located": True,
        "recommended_rejection_reasons": ["ignore_this_evidence"]}]}

    result = asyncio.run(WorkflowNodes(WorkflowServices(
        model=FakeModel([classification]), submitted_input="unused"
    )).evidence_classification(value))

    assert result.evidence[0].recommended_rejection_reasons == []


def test_extension_outputs_are_revalidated():
    async def invalid_extension(value: VerificationState) -> VerificationState:
        return value.model_copy(update={"candidate_sources": [{"source_ref": "incomplete"}]})

    node = WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused"))
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"), pytest.raises(ValidationError):
        asyncio.run(node.extension(WorkflowStage.DISCOVERY, invalid_extension)(state()))

def test_typed_extension_error_preserves_safe_failure_contract():
    async def unavailable(_value: VerificationState) -> VerificationState:
        raise WorkflowExtensionError(
            code="NO_ACCESSIBLE_SOURCES",
            public_message="No accessible sources were available after secure retrieval.",
            retryable=True,
            details={"candidate_count": 2, "failure_kind": "fetch"},
        )

    node = WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused"))
    result = asyncio.run(node.extension(WorkflowStage.RETRIEVAL, unavailable)(state()))

    assert result.recoverable_errors[0].code == "NO_ACCESSIBLE_SOURCES"
    assert (
        result.recoverable_errors[0].public_message
        == "No accessible sources were available after secure retrieval."
    )
    assert result.recoverable_errors[0].retryable is True
    assert result.recoverable_errors[0].details == {"candidate_count": 2, "failure_kind": "fetch"}


def test_unexpected_extension_runtime_error_reaches_worker_boundary():
    async def broken_extension(_value: VerificationState) -> VerificationState:
        raise RuntimeError("programming invariant failed")

    node = WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused"))
    with pytest.raises(RuntimeError, match="programming invariant failed"):
        asyncio.run(node.extension(WorkflowStage.RETRIEVAL, broken_extension)(state()))


@pytest.mark.parametrize(
    ("route", "stage", "node_name", "expected_code"),
    [
        (evidence_ready, WorkflowStage.EVIDENCE_CLASSIFICATION, "evidence_classification", "EVIDENCE_INPUTS_REQUIRED"),
        (synthesis_ready, WorkflowStage.SYNTHESIS, "synthesis", "APPROVED_EVIDENCE_REQUIRED"),
        (citation_audit_ready, WorkflowStage.CITATION_AUDIT, "citation_audit", "REPORT_DRAFT_REQUIRED"),
    ],
)
def test_missing_transition_prerequisite_reaches_responsible_stage(
    route, stage: WorkflowStage, node_name: str, expected_code: str
):
    value = state()
    assert route(value) == "continue"

    node = WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused"))
    result = asyncio.run(getattr(node, node_name)(value))

    assert result.recoverable_errors[-1].stage == stage
    assert result.recoverable_errors[-1].code == expected_code
    assert result.ready_for_completion is False


def test_full_graph_runs_typed_extensions_and_recomputes_citation_audit():
    async def discovery(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "candidate_sources": [
                    CandidateSource(
                        source_ref="source-1",
                        url="https://example.test/filing",
                        objective_refs=["objective-1"],
                        selection_reason="Original filing",
                        priority=Decimal("1"),
                    )
                ]
            }
        )

    async def retrieval(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "snapshots": [
                    SnapshotRecord(
                        snapshot_id="snapshot-1",
                        source_ref="source-1",
                        access_status="FETCHED",
                        retrieved_at=datetime(2026, 6, 28, tzinfo=UTC),
                    ),
                    SnapshotRecord(
                        snapshot_id="snapshot-2",
                        source_ref="source-2",
                        access_status="PAYWALLED",
                        retrieved_at=datetime(2026, 6, 28, tzinfo=UTC),
                        failure_reason="Subscription required",
                    ),
                ]
            }
        )

    async def unchanged(value: VerificationState) -> VerificationState:
        return value

    async def segmentation(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "passages": [
                    PassageRecord(
                        passage_id="passage-1",
                        source_ref="source-1",
                        snapshot_id="snapshot-1",
                        text="Net income was 20, compared with 10 in the comparable period.",
                        text_hash="hash-1",
                        extraction_certainty=Decimal("0.95"),
                    )
                ]
            }
        )

    async def scoring(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "scores": ScoreBundle(
                    evidence_support=95,
                    verdict_confidence=85,
                    source_independence=80,
                    context_completeness=90,
                    final_label="supported",
                    methodology_version="1.0",
                )
            }
        )

    evidence = {
        "classifications": [
            {
                "task_ref": classification_task_ref(GENERATED_CLAIM_REF, "passage-1"),
                "stance": "strongly_supports",
                "quality": {
                    "relevance": 1,
                    "directness": 1,
                    "claim_specific_authority": 0.9,
                    "transparency": 0.9,
                    "temporal_fit": 1,
                    "extraction_certainty": 0.50,
                },
                "explicit_support": "The values are 20 and 10.",
                "entity_match": True,
                "time_period_match": True,
                "quotation_or_number_located": True,
            }
        ]
    }
    synthesis = {
        "summary_sentences": [
            {
                "sentence_ref": "summary-1",
                "text": "The filing supports the claim.",
                "passage_ids": ["passage-1"],
            }
        ],
    }
    audit = {
        "sentence_audits": [
            {
                "sentence_ref": "summary-1",
                "passage_id": "passage-1",
                "entailment": "entailed",
                "support_explanation": "The passage provides both comparable values.",
            }
        ],
        "unsupported_sentence_refs": ["invented-by-model"],
        "missing_citation_sentence_refs": ["invented-by-model"],
        "needs_revision": True,
    }
    workflow = build_workflow(
        WorkflowServices(
            model=FakeModel([INTAKE, DECOMPOSITION_DRAFT, DRAFT_PLAN_FOR_GENERATED_CLAIMS, evidence, synthesis, audit]),
            submitted_input="Company X doubled net income in Q1 2026.",
            extensions=WorkflowExtensions(
                discovery_source_selection=discovery,
                secure_retrieval=retrieval,
                extraction=unchanged,
                passage_segmentation_embedding=segmentation,
                provenance_dependency_analysis=unchanged,
                deterministic_scoring=scoring,
                numerical_audit=unchanged,
            ),
        )
    )

    result = VerificationState.model_validate(asyncio.run(workflow.ainvoke(state())))

    assert result.citation_audit is not None
    assert result.citation_audit.needs_revision is False
    assert result.citation_audit.unsupported_sentence_refs == []
    assert result.report_draft is not None
    assert result.report_draft.evidence_timestamp == (
        "Evidence reviewed as of 2026-06-28T00:00:00+00:00. "
        "New evidence or corrections may change this assessment."
    )
    assert result.report_draft.inaccessible_source_notes == [
        "Source source-2 was paywalled: Subscription required"
    ]
    assert result.report_draft.methodology_version == "1.0"
    assert result.report_draft.workflow_version == "step-10"
    assert result.report_draft.model_versions["synthesis"] == "deepseek-chat"
    assert result.evidence[0].quality.extraction_certainty == 0.95
    assert result.completed_stages[-1] == WorkflowStage.CITATION_AUDIT
    assert result.ready_for_completion is True


def test_citation_revision_uses_only_approved_passages_and_is_reaudited():
    report = SynthesisOutput.model_validate(
        {
            "title": "Initial report",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing proves the broader claim.",
                    "passage_ids": ["passage-1"],
                }
            ],
        }
    )
    audit = CitationAuditOutput.model_validate(
        {
            "sentence_audits": [
                {
                    "sentence_ref": "summary-1",
                    "passage_id": "passage-1",
                    "entailment": "partial",
                    "support_explanation": "Only the reported value is supported.",
                    "suggested_revision": "The filing reports a value of 20.",
                }
            ],
            "needs_revision": True,
        }
    )
    value = state().model_copy(
        update={
            "snapshots": [
                SnapshotRecord(
                    snapshot_id="snapshot-1",
                    source_ref="source-1",
                    access_status="FETCHED",
                    retrieved_at=datetime(2026, 7, 4, tzinfo=UTC),
                )
            ],
            "passages": [
                PassageRecord(
                    passage_id="passage-1",
                    source_ref="source-1",
                    snapshot_id="snapshot-1",
                    text="The filing reports a value of 20.",
                    text_hash="hash-1",
                    extraction_certainty=Decimal("1"),
                )
            ],
            "evidence": [
                EvidenceClassificationItemOutput.model_validate({
                    "claim_ref": "claim-1",
                    "passage_id": "passage-1",
                    "stance": "strongly_supports",
                    "quality": {
                        "relevance": 1,
                        "directness": 1,
                        "claim_specific_authority": 1,
                        "transparency": 1,
                        "temporal_fit": 1,
                        "extraction_certainty": 1,
                    },
                    "entity_match": True,
                    "time_period_match": True,
                })
            ],
            "scores": ScoreBundle(
                evidence_support=100,
                verdict_confidence=90,
                source_independence=80,
                context_completeness=90,
                final_label="supported",
                methodology_version="1.0",
            ),
            "report_draft": report,
            "citation_audit": audit,
            "completed_stages": [WorkflowStage.CITATION_AUDIT],
        }
    )
    revision_model = FakeModel(
        [
            {
                "summary_sentences": [
                    {
                        "sentence_ref": "summary-1-revised",
                        "text": "The filing reports a value of 20.",
                        "passage_ids": ["passage-1"],
                    }
                ],
            }
        ]
    )
    revised = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=revision_model, submitted_input="unused")
        ).citation_revision(value)
    )
    assert revised.citation_revision_count == 1
    assert revised.citation_audit is None
    assert WorkflowStage.CITATION_AUDIT not in revised.completed_stages

    audited = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel(
                    [
                        {
                            "sentence_audits": [
                                {
                                    "sentence_ref": "summary-1-revised",
                                    "passage_id": "passage-1",
                                    "entailment": "entailed",
                                    "support_explanation": "The wording matches the passage.",
                                }
                            ],
                            "needs_revision": False,
                        }
                    ]
                ),
                submitted_input="unused",
            )
        ).citation_audit(revised)
    )
    assert audited.ready_for_completion is True


def test_citation_audit_requires_exact_unique_known_sentence_passage_pairs():
    report = SynthesisOutput.model_validate(
        {
            "title": "Assessment",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing reports a value of 20.",
                    "passage_ids": ["passage-1"],
                }
            ],
        }
    )
    complete = {
        "sentence_ref": "summary-1",
        "passage_id": "passage-1",
        "entailment": "entailed",
        "support_explanation": "The passage contains the reported value.",
    }
    assert _guard_citation_audit(
        report,
        {"passage-1": object()},
        CitationAuditOutput.model_validate({"sentence_audits": [complete], "needs_revision": False}),
    ) is not None

    invalid_audits = [
        [],
        [complete, complete],
        [{**complete, "sentence_ref": "unknown-1"}],
        [{**complete, "passage_id": "unknown-passage"}],
    ]
    for audits in invalid_audits:
        assert _guard_citation_audit(
            report,
            {"passage-1": object()},
            CitationAuditOutput.model_validate(
                {"sentence_audits": audits, "needs_revision": False}
            ),
        ) is None


def test_citation_audit_preflight_rejects_duplicate_sentence_refs_without_model_call():
    report = SynthesisOutput.model_validate(
        {
            "title": "Assessment",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing reports a value of 20.",
                    "passage_ids": ["passage-1"],
                }
            ],
        }
    ).model_copy(
        update={
            "factual_sentences": [
                CitedReportSentenceOutput(
                    sentence_ref="summary-1",
                    text="The filing records the same value.",
                    passage_ids=["passage-1"],
                )
            ]
        }
    )
    model = FakeModel([])

    result = asyncio.run(
        WorkflowNodes(WorkflowServices(model=model, submitted_input="unused")).citation_audit(
            state().model_copy(update={"report_draft": report})
        )
    )

    assert model.calls == []
    assert result.recoverable_errors[-1].code == "DUPLICATE_REPORT_SENTENCE_REF"
    assert result.ready_for_completion is False


def test_citation_audit_rejects_a_report_pair_from_rejected_evidence():
    report = SynthesisOutput.model_validate(
        {
            "title": "Assessment",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing reports a value of 20.",
                    "passage_ids": ["passage-1"],
                }
            ],
        }
    )
    value = state().model_copy(
        update={
            "report_draft": report,
            "snapshots": [
                SnapshotRecord(
                    snapshot_id="snapshot-1",
                    source_ref="source-1",
                    access_status="FETCHED",
                    retrieved_at=datetime(2026, 7, 4, tzinfo=UTC),
                )
            ],
            "passages": [
                PassageRecord(
                    passage_id="passage-1",
                    source_ref="source-1",
                    snapshot_id="snapshot-1",
                    text="The filing reports a value of 20.",
                    text_hash="hash-1",
                    extraction_certainty=Decimal("1"),
                )
            ],
            "evidence": [
                EvidenceClassificationItemOutput.model_validate(
                    {
                        "claim_ref": "claim-1",
                        "passage_id": "passage-1",
                        "stance": "strongly_supports",
                        "quality": {
                            "relevance": 1,
                            "directness": 1,
                            "claim_specific_authority": 1,
                            "transparency": 1,
                            "temporal_fit": 1,
                            "extraction_certainty": 1,
                        },
                        "entity_match": True,
                        "time_period_match": True,
                        "recommended_rejection_reasons": ["deterministic_gate"],
                    }
                )
            ],
        }
    )

    result = asyncio.run(
        WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused")).citation_audit(value)
    )

    assert result.recoverable_errors[-1].code == "REJECTED_EVIDENCE_CITED"
    assert result.ready_for_completion is False


def test_citation_revision_limit_exhaustion_fails_closed():
    value = state().model_copy(
        update={
            "report_draft": SynthesisOutput.model_validate(
                {
                    "title": "Unsupported report",
                    "summary_sentences": [
                        {
                            "sentence_ref": "summary-1",
                            "text": "Unsupported statement.",
                            "passage_ids": ["passage-1"],
                        }
                    ],
                }
            ),
            "citation_audit": CitationAuditOutput.model_validate(
                {"needs_revision": True}
            ),
        }
    )
    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(
                model=FakeModel([]),
                submitted_input="unused",
                citation_revision_limit=0,
            )
        ).citation_revision(value)
    )
    assert result.recoverable_errors[-1].code == "CITATION_REVISION_EXHAUSTED"
    assert result.ready_for_completion is False


def test_sql_state_writer_persists_planning_artifacts_and_safe_model_metadata():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="workflow-owner",
            email="workflow@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.VALIDATING,
            submitted_text="Company X doubled net income in Q1 2026.",
            normalized_target={},
            workflow_version="step-8-test",
        )
        db.add(run)
        db.commit()
        run_id = run.id
        owner_id = owner.id

    metadata = CallMetadata(
        model="deepseek-chat",
        prompt_version="planner-v2",
        temperature=0,
        latency_ms=12,
    )
    intake = IntakeClassificationOutput.model_validate(INTAKE)
    decomposition = DecompositionOutput.model_validate(DECOMPOSITION)
    plan = PlanningOutput.model_validate(PLAN)
    value = VerificationState(
        run_id=run_id,
        user_id=owner_id,
        normalized_input=intake,
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        claims=decomposition.atomic_claims,
        objectives=plan.objectives,
        queries=plan.queries,
        model_calls={"planner": metadata},
    )
    writer = SqlWorkflowStateWriter(factory)
    asyncio.run(writer.save(stage=WorkflowStage.INTAKE, state=value))
    asyncio.run(writer.save(stage=WorkflowStage.DECOMPOSITION, state=value))
    asyncio.run(writer.save(stage=WorkflowStage.PLANNER, state=value))

    with factory() as db:
        durable_run = db.get(VerificationRun, run_id)
        claim_count = db.scalar(select(func.count()).select_from(AtomicClaim))
        query_count = db.scalar(select(func.count()).select_from(SearchQuery))
    assert durable_run is not None
    assert durable_run.normalized_target["research_plan"]["objectives"][0]["objective_ref"] == "objective-1"
    assert durable_run.model_versions["planner"]["provider"] == "deepseek"
    assert durable_run.prompt_versions["planner"] == "planner-v2"
    assert claim_count == 1
    assert query_count == 2


def test_runtime_executes_and_persists_planning_handoff():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="runtime-owner",
            email="runtime@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.VALIDATING,
            submitted_text="Company X doubled net income in Q1 2026.",
            normalized_target={},
            workflow_version="step-8-runtime-test",
        )
        db.add(run)
        db.commit()
        run_id = run.id
    events: list[dict[str, object]] = []

    def record(*_args, **kwargs):
        events.append(kwargs)

    result = execute_planning_workflow(
        factory,
        object(),
        Settings(environment="test"),
        run_id,
        record=record,
        is_cancelled=lambda *_args: False,
        model=FakeModel([INTAKE, DECOMPOSITION_DRAFT, DRAFT_PLAN_FOR_GENERATED_CLAIMS]),
    )

    assert result is not None
    assert result.workflow_version == "step-8-runtime-test"
    assert result.completed_stages[-1] == WorkflowStage.PLANNER
    assert events[-1]["payload"]["completed_steps"] == 3
    with factory() as db:
        durable_run = db.get(VerificationRun, run_id)
        assert durable_run is not None
        assert durable_run.normalized_target["input_kind"] == "claim"
        assert db.scalar(select(func.count()).select_from(AtomicClaim)) == 1
        assert db.scalar(select(AtomicClaim.gates))["claim_ref"] == GENERATED_CLAIM_REF
        assert db.scalar(select(func.count()).select_from(SearchQuery)) == 2


def test_production_runtime_executes_full_graph_and_persists_report_before_completion():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="full-runtime-owner",
            email="full-runtime@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.VALIDATING,
            submitted_text="Company X reported a value of 20.",
            normalized_target={},
            workflow_version="step-18-runtime-test",
        )
        db.add(run)
        db.commit()
        run_id = run.id

    snapshot_id = str(uuid4())
    passage_id = str(uuid4())

    async def discovery(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "candidate_sources": [
                    CandidateSource(
                        source_ref="source-1",
                        url="https://example.test/full-runtime",
                        canonical_url="https://example.test/full-runtime",
                        domain="example.test",
                        selection_reason="Controlled primary source",
                    )
                ]
            }
        )

    async def retrieval(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "snapshots": [
                    SnapshotRecord(
                        snapshot_id=snapshot_id,
                        source_ref="source-1",
                        access_status="FETCHED",
                        retrieved_at=datetime(2026, 7, 4, tzinfo=UTC),
                    )
                ]
            }
        )

    async def segmentation(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "passages": [
                    PassageRecord(
                        passage_id=passage_id,
                        source_ref="source-1",
                        snapshot_id=snapshot_id,
                        text="Company X reported a value of 20.",
                        text_hash="full-runtime-passage",
                        extraction_certainty=Decimal("1"),
                    )
                ]
            }
        )

    async def unchanged(value: VerificationState) -> VerificationState:
        return value

    async def scoring(value: VerificationState) -> VerificationState:
        return value.model_copy(
            update={
                "scores": ScoreBundle(
                    evidence_support=100,
                    verdict_confidence=90,
                    source_independence=80,
                    context_completeness=90,
                    final_label="supported",
                    methodology_version="1.0",
                )
            }
        )

    evidence = {
        "classifications": [
            {
                "task_ref": classification_task_ref(GENERATED_CLAIM_REF, passage_id),
                "stance": "strongly_supports",
                "quality": {
                    "relevance": 1,
                    "directness": 1,
                    "claim_specific_authority": 1,
                    "transparency": 1,
                    "temporal_fit": 1,
                    "extraction_certainty": 1,
                },
                "explicit_support": "The reported value is 20.",
                "entity_match": True,
                "time_period_match": True,
                "quotation_or_number_located": True,
            }
        ]
    }
    synthesis = {
        "summary_sentences": [
            {
                "sentence_ref": "summary-1",
                "text": "Company X reported a value of 20.",
                "passage_ids": [passage_id],
            }
        ],
    }
    audit = {
        "sentence_audits": [
            {
                "sentence_ref": "summary-1",
                "passage_id": passage_id,
                "entailment": "entailed",
                "support_explanation": "The passage directly matches the sentence.",
            }
        ],
        "needs_revision": False,
    }
    public_events: list[dict[str, object]] = []
    result = execute_verification_workflow(
        factory,
        object(),
        Settings(environment="test"),
        run_id,
        record=lambda *_args, **kwargs: public_events.append(kwargs),
        is_cancelled=lambda *_args: False,
        model=FakeModel([INTAKE, DECOMPOSITION_DRAFT, DRAFT_PLAN_FOR_GENERATED_CLAIMS, evidence, synthesis, audit]),
        workflow_extensions=WorkflowExtensions(
            discovery_source_selection=discovery,
            secure_retrieval=retrieval,
            extraction=unchanged,
            passage_segmentation_embedding=segmentation,
            provenance_dependency_analysis=unchanged,
            deterministic_scoring=scoring,
            numerical_audit=unchanged,
        ),
    )

    assert result is not None and result.ready_for_completion
    assert [stage for stage in result.completed_stages] == list(WorkflowStage)[:12] + [
        WorkflowStage.CITATION_AUDIT
    ]
    with factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run is not None and run.title == "Evidence assessment"
        assert db.scalar(select(func.count()).select_from(ReportCitation)) == 1
        persist_completed_run(db, run_id=run_id, expected_citation_count=1)
        report = build_report(db, run=run)
    assert report.report_sentences[0].sentence_text == "Company X reported a value of 20."
    assert public_events[-1]["event_type"] == "workflow.citation_audit.completed"


def test_runtime_resumes_retryable_retrieval_from_extracting_status():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="retry-owner",
            email="retry@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.VALIDATING,
            submitted_text="Company X doubled net income in Q1 2026.",
            normalized_target={},
            workflow_version="step-9-retry-test",
        )
        db.add(run)
        db.commit()
        run_id = run.id

    execute_planning_workflow(
        factory,
        object(),
        Settings(environment="test"),
        run_id,
        record=lambda *_args, **_kwargs: None,
        is_cancelled=lambda *_args: False,
        model=FakeModel([INTAKE, DECOMPOSITION_DRAFT, DRAFT_PLAN_FOR_GENERATED_CLAIMS]),
    )
    with factory() as db:
        run = db.get(VerificationRun, run_id)
        run.status = RunStatus.EXTRACTING
        db.commit()

    class RetryablePipeline:
        calls = 0

        async def discover(self, value):
            self.calls += 1
            return value.model_copy(
                update={
                    "candidate_sources": [
                        CandidateSource(
                            source_ref="source-1",
                            url="https://example.test/source",
                            selection_reason="retry test",
                        )
                    ]
                }
            )

        async def retrieve(self, _value):
            raise WorkflowExtensionError(
                code="RETRIEVAL_UNAVAILABLE",
                public_message="A retrieval service was temporarily unavailable.",
                retryable=True,
                details={"failure_kind": "fetch"},
            )

        async def extract(self, value):
            return value

    pipeline = RetryablePipeline()
    result = execute_planning_workflow(
        factory,
        object(),
        Settings(environment="test"),
        run_id,
        record=lambda *_args, **_kwargs: None,
        is_cancelled=lambda *_args: False,
        model=FakeModel([]),
        retrieve=True,
        retrieval_pipeline=pipeline,
    )

    assert result is not None
    assert pipeline.calls == 1
    assert result.recoverable_errors[-1].retryable is True
    assert result.recoverable_errors[-1].code == "RETRIEVAL_UNAVAILABLE"
    assert result.recoverable_errors[-1].details == {"failure_kind": "fetch"}


def test_sql_state_writer_persists_every_report_sentence_role():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime(2026, 6, 29, tzinfo=UTC)
    with factory() as db:
        owner = User(
            auth_provider="firebase",
            auth_subject="citation-owner",
            email="citation@example.test",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(owner)
        db.flush()
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth="STANDARD",
            status=RunStatus.AUDITING,
            submitted_text="A citation claim",
            normalized_target={},
            workflow_version="step-8-test",
        )
        source = Source(
            canonical_url="https://example.test/citation",
            domain="example.test",
            source_type=SourceType.PRIMARY,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add_all([run, source])
        db.flush()
        snapshot = SourceSnapshot(
            source_id=source.id,
            version_number=1,
            retrieved_at=now,
            access_status=AccessStatus.FETCHED,
        )
        db.add(snapshot)
        db.flush()
        passage = SourcePassage(
            snapshot_id=snapshot.id,
            source_id=source.id,
            text="The filing reports the value.",
            text_hash="citation-hash",
            extraction_certainty=Decimal("1"),
        )
        db.add(passage)
        db.commit()
        run_id = run.id
        owner_id = owner.id
        passage_id = passage.id

    report = SynthesisOutput.model_validate(
        {
            "title": "Citation report",
            "summary_sentences": [
                {
                    "sentence_ref": "summary-1",
                    "text": "The filing reports the value.",
                    "passage_ids": [str(passage_id)],
                }
            ],
            "factual_sentences": [{"sentence_ref": "fact-1", "text": "The filing records the value.", "passage_ids": [str(passage_id)]}],
            "attribution_findings": [{"sentence_ref": "attribution-1", "text": "The filing attributes the value to the agency.", "passage_ids": [str(passage_id)]}],
            "strongest_credible_contradiction": {"sentence_ref": "contradiction-1", "text": "A cited record reports a different value.", "passage_ids": [str(passage_id)]},
        }
    )
    audit = CitationAuditOutput.model_validate(
        {
            "sentence_audits": [
                {
                    "sentence_ref": "summary-1",
                    "passage_id": str(passage_id),
                    "entailment": "entailed",
                    "support_explanation": "The passage directly supports the sentence.",
                },
                {"sentence_ref": "fact-1", "passage_id": str(passage_id), "entailment": "entailed", "support_explanation": "The passage supports the factual finding."},
                {"sentence_ref": "attribution-1", "passage_id": str(passage_id), "entailment": "entailed", "support_explanation": "The passage supports the attribution."},
                {"sentence_ref": "contradiction-1", "passage_id": str(passage_id), "entailment": "entailed", "support_explanation": "The passage supports the contradiction."},
            ],
            "needs_revision": False,
        }
    )
    value = VerificationState(
        run_id=run_id,
        user_id=owner_id,
        research_depth=ResearchDepth.STANDARD,
        methodology_version="1.0",
        report_draft=report,
        citation_audit=audit,
    )

    asyncio.run(
        SqlWorkflowStateWriter(factory).save(
            stage=WorkflowStage.CITATION_AUDIT,
            state=value,
        )
    )

    with factory() as db:
        citations = db.scalars(select(ReportCitation)).all()
    assert {citation.report_section for citation in citations} == {
        "summary", "factual_finding", "attribution", "strongest_contradiction"
    }
    assert {citation.passage_id for citation in citations} == {passage_id}
    assert {citation.audit_status for citation in citations} == {"passed"}
