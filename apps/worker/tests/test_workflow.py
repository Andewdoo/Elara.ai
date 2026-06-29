import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from agents.deepseek_client import (
    CallMetadata,
    DeepSeekUnavailableError,
    ProviderErrorMetadata,
    StructuredResponse,
)
from agents.schemas import (
    CitationAuditOutput,
    DecompositionOutput,
    InputKind,
    IntakeClassificationOutput,
    PlanningOutput,
    SynthesisOutput,
)
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
from graph.state import (
    CandidateSource,
    PassageRecord,
    ResearchDepth,
    ScoreBundle,
    SnapshotRecord,
    VerificationState,
    WorkflowStage,
)
from graph.workflow import WorkflowExtensions, WorkflowNodes, WorkflowServices, build_workflow
from graph.runtime import SqlWorkflowStateWriter, execute_planning_workflow


class FakeModel:
    def __init__(self, outputs: list[dict[str, object]]) -> None:
        self.outputs = outputs
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


def test_planning_workflow_is_typed_and_persists_public_progress():
    progress = RecordingProgress()
    writer = RecordingStateWriter()
    model = FakeModel([INTAKE, DECOMPOSITION, PLAN])
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

    assert result.claims[0].claim_ref == "claim-1"
    assert result.queries[0].objective_ref == "objective-1"
    assert result.completed_stages == [
        WorkflowStage.INTAKE,
        WorkflowStage.DECOMPOSITION,
        WorkflowStage.PLANNER,
    ]
    assert [call["prompt_version"] for call in model.calls] == [
        "intake-v1",
        "decomposition-v1",
        "planner-v1",
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


def test_intake_rejects_model_input_type_drift():
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
    assert progress.events[-1]["payload"]["details"] == {}


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
    cyclical = deepcopy(DECOMPOSITION)
    cyclical["atomic_claims"] = [
        {**DECOMPOSITION["atomic_claims"][0], "claim_ref": "claim-1", "parent_claim_ref": "claim-2"},
        {**DECOMPOSITION["atomic_claims"][0], "claim_ref": "claim-2", "parent_claim_ref": "claim-1"},
    ]
    value = VerificationState.model_validate(
        {**state().model_dump(), "normalized_input": INTAKE}
    )

    result = asyncio.run(
        WorkflowNodes(
            WorkflowServices(model=FakeModel([cyclical]), submitted_input="unused")
        ).decomposition(value)
    )

    assert result.recoverable_errors[0].code == "INVALID_CLAIM_GRAPH"


def test_planner_requires_primary_and_contradiction_paths_per_claim():
    second_claim = {
        **DECOMPOSITION["atomic_claims"][0],
        "claim_ref": "claim-2",
        "text": "Demand increased in Q1 2026.",
    }
    incomplete_plan = deepcopy(PLAN)
    incomplete_plan["objectives"].append(
        {
            "objective_ref": "objective-3",
            "claim_ref": "claim-2",
            "intent": "primary",
            "target": "Locate demand records.",
        }
    )
    incomplete_plan["queries"].append(
        {
            "query": "Company X Q1 2026 demand records",
            "objective_ref": "objective-3",
            "intent": "primary",
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
            WorkflowServices(model=FakeModel([incomplete_plan]), submitted_input="unused")
        ).planner(value)
    )

    assert result.recoverable_errors[0].code == "INVALID_RESEARCH_PLAN"


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
                        "claim_ref": "claim-1",
                        "passage_id": "invented-passage",
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
    assert result.recoverable_errors[0].code == "INVALID_EVIDENCE_REFERENCES"


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
                "claim_ref": "claim-1",
                "passage_id": "passage-1",
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


def test_extension_outputs_are_revalidated():
    async def invalid_extension(value: VerificationState) -> VerificationState:
        return value.model_copy(update={"candidate_sources": [{"source_ref": "incomplete"}]})

    node = WorkflowNodes(WorkflowServices(model=FakeModel([]), submitted_input="unused"))
    with pytest.warns(UserWarning, match="Pydantic serializer warnings"):
        result = asyncio.run(node.extension(WorkflowStage.DISCOVERY, invalid_extension)(state()))

    assert result.candidate_sources == []
    assert result.recoverable_errors[0].code == "WORKFLOW_EXTENSION_FAILED"


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
                "claim_ref": "claim-1",
                "passage_id": "passage-1",
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
        "title": "Assessment of Company X net income claim",
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
            model=FakeModel([INTAKE, DECOMPOSITION, PLAN, evidence, synthesis, audit]),
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
    assert result.report_draft.workflow_version == "step-8"
    assert result.report_draft.model_versions["synthesis"] == "deepseek-chat"
    assert result.evidence[0].quality.extraction_certainty == 0.95
    assert result.completed_stages[-1] == WorkflowStage.CITATION_AUDIT
    assert result.ready_for_completion is True


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
        prompt_version="planner-v1",
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
    assert durable_run.prompt_versions["planner"] == "planner-v1"
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
        model=FakeModel([INTAKE, DECOMPOSITION, PLAN]),
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
        assert db.scalar(select(func.count()).select_from(SearchQuery)) == 2


def test_sql_state_writer_persists_citation_audit_rows():
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
                }
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
        citation = db.scalar(select(ReportCitation))
    assert citation is not None
    assert citation.passage_id == passage_id
    assert citation.audit_status == "entailed"
