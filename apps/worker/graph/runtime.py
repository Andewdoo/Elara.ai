"""Production adapters connecting typed graph nodes to durable run services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from redis import Redis
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from agents.deepseek_client import DeepSeekClient
from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    EvidenceIntent,
    FactCheckability,
    Importance,
    InputKind,
    IntakeClassificationOutput,
    ResearchObjectiveOutput,
    SearchQueryOutput,
)
from app.config import Settings
from app.models.claims import AtomicClaim, SearchQuery
from app.models.enums import InputType, RunStatus
from app.models.evidence import ReportCitation
from app.models.methodology import MethodologyVersion
from app.models.verification_run import VerificationRun
from graph.state import ResearchDepth, VerificationState, WorkflowStage
from graph.workflow import WorkflowServices, build_workflow


_RUN_STATUSES = {
    WorkflowStage.INTAKE: RunStatus.VALIDATING,
    WorkflowStage.DECOMPOSITION: RunStatus.DECOMPOSING,
    WorkflowStage.PLANNER: RunStatus.RESEARCHING,
    WorkflowStage.DISCOVERY: RunStatus.RESEARCHING,
    WorkflowStage.RETRIEVAL: RunStatus.RESEARCHING,
    WorkflowStage.EXTRACTION: RunStatus.EXTRACTING,
    WorkflowStage.SEGMENTATION: RunStatus.EXTRACTING,
    WorkflowStage.PROVENANCE: RunStatus.ANALYZING_PROVENANCE,
    WorkflowStage.EVIDENCE_CLASSIFICATION: RunStatus.SCORING,
    WorkflowStage.SCORING: RunStatus.SCORING,
    WorkflowStage.NUMERICAL_AUDIT: RunStatus.SCORING,
    WorkflowStage.SYNTHESIS: RunStatus.SYNTHESIZING,
    WorkflowStage.CITATION_AUDIT: RunStatus.AUDITING,
}


class DurableProgressWriter:
    def __init__(self, record) -> None:
        self._record = record

    async def publish(
        self,
        *,
        run_id: UUID,
        stage: WorkflowStage,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        status = RunStatus.CANCELLED if event_type == "run.cancelled" else _RUN_STATUSES[stage]
        self._record(
            run_id=run_id,
            stage=status,
            event_type=event_type,
            message=message,
            payload=payload,
        )


class RunCancellationChecker:
    def __init__(self, check) -> None:
        self._check = check

    async def is_cancelled(self, run_id: UUID) -> bool:
        return bool(self._check(run_id))


class SqlWorkflowStateWriter:
    """Persist currently available Step 8 outputs; later stages extend this adapter."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    async def save(self, *, stage: WorkflowStage, state: VerificationState) -> None:
        with self._factory() as db:
            run = db.get(VerificationRun, state.run_id)
            if run is None:
                raise LookupError(f"Verification run {state.run_id} does not exist")
            if stage == WorkflowStage.INTAKE and state.normalized_input is not None:
                run.normalized_target = state.normalized_input.model_dump(mode="json")
            elif stage == WorkflowStage.DECOMPOSITION and state.claims:
                self._persist_claims(db, run, state)
            elif stage == WorkflowStage.PLANNER and state.objectives and state.queries:
                self._persist_plan(db, run, state)
            elif stage == WorkflowStage.SYNTHESIS and state.report_draft is not None:
                run.title = state.report_draft.title
                run.evidence_reviewed_at = state.evidence_reviewed_at
            elif stage == WorkflowStage.CITATION_AUDIT and state.citation_audit is not None:
                self._persist_citation_audit(db, run, state)
            self._persist_model_metadata(run, state)
            db.commit()

    @staticmethod
    def _persist_claims(db: Session, run: VerificationRun, state: VerificationState) -> None:
        db.execute(delete(SearchQuery).where(SearchQuery.run_id == run.id))
        db.execute(delete(AtomicClaim).where(AtomicClaim.run_id == run.id))
        db.flush()
        created: dict[str, AtomicClaim] = {}
        normalized = state.normalized_input
        for claim in state.claims:
            row = AtomicClaim(
                run_id=run.id,
                claim_text=claim.text,
                normalized_claim=claim.text,
                claim_type=claim.claim_kind.value,
                importance_weight=claim.importance_weight,
                entities=[item.model_dump(mode="json") for item in claim.entities]
                or (
                    [item.model_dump(mode="json") for item in normalized.entities]
                    if normalized
                    else []
                ),
                time_period=claim.time_period,
                locations=list(claim.locations)
                or (list(normalized.locations) if normalized else []),
                metrics=[item.model_dump(mode="json") for item in claim.metrics]
                or (
                    [item.model_dump(mode="json") for item in normalized.metrics]
                    if normalized
                    else []
                ),
                comparison=claim.comparison
                or (
                    normalized.comparisons[0]
                    if normalized and normalized.comparisons
                    else None
                ),
                ambiguities=list(claim.ambiguities),
                fact_checkable=claim.fact_checkability.value != "not_fact_checkable",
                gates={
                    "claim_ref": claim.claim_ref,
                    "original_text_span": claim.original_text_span,
                    "verification_scope": claim.verification_scope,
                    "importance": claim.importance.value,
                    "fact_checkability": claim.fact_checkability.value,
                },
            )
            db.add(row)
            db.flush()
            created[claim.claim_ref] = row
        for claim in state.claims:
            if claim.parent_claim_ref is not None:
                created[claim.claim_ref].parent_claim_id = created[claim.parent_claim_ref].id

    @staticmethod
    def _persist_plan(db: Session, run: VerificationRun, state: VerificationState) -> None:
        db.execute(delete(SearchQuery).where(SearchQuery.run_id == run.id))
        claims = db.scalars(select(AtomicClaim).where(AtomicClaim.run_id == run.id)).all()
        claim_ids = {str(row.gates.get("claim_ref")): row.id for row in claims}
        objectives = {objective.objective_ref: objective for objective in state.objectives}
        for query in state.queries:
            objective = objectives[query.objective_ref]
            db.add(
                SearchQuery(
                    run_id=run.id,
                    atomic_claim_id=claim_ids.get(objective.claim_ref),
                    family=query.intent.value,
                    query_text=query.query,
                    generated_by_node=f"planner:{query.objective_ref}"[:100],
                    priority=Decimal(str(query.priority)),
                )
            )
        target = dict(run.normalized_target)
        target["research_plan"] = {
            "objectives": [item.model_dump(mode="json") for item in state.objectives],
            "primary_source_targets": list(state.primary_source_targets),
            "known_evidence_gaps": list(state.known_evidence_gaps),
        }
        run.normalized_target = target

    @staticmethod
    def _persist_model_metadata(run: VerificationRun, state: VerificationState) -> None:
        models = dict(run.model_versions)
        prompts = dict(run.prompt_versions)
        for stage, metadata in state.model_calls.items():
            models[stage] = {
                "provider": metadata.provider,
                "model": metadata.model,
                "latency_ms": metadata.latency_ms,
                "usage": metadata.usage.model_dump(mode="json"),
            }
            prompts[stage] = metadata.prompt_version
        run.model_versions = models
        run.prompt_versions = prompts

    @staticmethod
    def _persist_citation_audit(
        db: Session, run: VerificationRun, state: VerificationState
    ) -> None:
        if state.report_draft is None or state.citation_audit is None:
            return
        sentences = {
            sentence.sentence_ref: sentence
            for sentence in [
                *state.report_draft.summary_sentences,
                *state.report_draft.factual_sentences,
                *state.report_draft.attribution_findings,
                *(
                    [state.report_draft.strongest_credible_contradiction]
                    if state.report_draft.strongest_credible_contradiction is not None
                    else []
                ),
            ]
        }
        db.execute(delete(ReportCitation).where(ReportCitation.run_id == run.id))
        for audit in state.citation_audit.sentence_audits:
            try:
                passage_id = UUID(audit.passage_id)
            except ValueError:
                raise ValueError("citation passage IDs must be durable UUIDs") from None
            sentence = sentences[audit.sentence_ref]
            db.add(
                ReportCitation(
                    run_id=run.id,
                    report_section="report",
                    sentence_text=sentence.text,
                    passage_id=passage_id,
                    audit_status=audit.entailment.value,
                    audit_note=audit.support_explanation,
                )
            )


def execute_planning_workflow(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
    *,
    record,
    is_cancelled,
    model: DeepSeekClient | None = None,
) -> VerificationState | None:
    """Run Step 8 through planning, leaving discovery to the Step 9 extension."""
    with factory() as db:
        run = db.get(VerificationRun, run_id)
        if run is None:
            raise LookupError(f"Verification run {run_id} does not exist")
        if run.status not in {RunStatus.VALIDATING, RunStatus.DECOMPOSING, RunStatus.RESEARCHING}:
            return None
        submitted_input = run.submitted_text or run.submitted_url
        if not submitted_input:
            return None
        methodology = (
            db.get(MethodologyVersion, run.methodology_version_id)
            if run.methodology_version_id is not None
            else None
        )
        target = dict(run.normalized_target)
        plan_data = target.pop("research_plan", None)
        normalized = IntakeClassificationOutput.model_validate(target) if target.get("input_kind") else None
        claim_rows = db.scalars(select(AtomicClaim).where(AtomicClaim.run_id == run.id)).all()
        row_refs = {row.id: str(row.gates.get("claim_ref")) for row in claim_rows}
        claims = [
            AtomicClaimOutput(
                claim_ref=row_refs[row.id],
                text=row.claim_text,
                claim_kind=ClaimKind(row.claim_type),
                importance=Importance(str(row.gates.get("importance", "minor"))),
                importance_weight=row.importance_weight,
                fact_checkability=FactCheckability(
                    str(row.gates.get("fact_checkability", "fact_checkable"))
                ),
                original_text_span=(
                    str(row.gates["original_text_span"])
                    if row.gates.get("original_text_span") is not None
                    else None
                ),
                entities=row.entities,
                time_period=row.time_period,
                locations=row.locations,
                metrics=row.metrics,
                comparison=row.comparison,
                parent_claim_ref=row_refs.get(row.parent_claim_id),
                ambiguities=[str(value) for value in row.ambiguities],
                verification_scope=str(row.gates.get("verification_scope", row.claim_text)),
            )
            for row in claim_rows
        ]
        objectives = [
            ResearchObjectiveOutput.model_validate(item)
            for item in (plan_data or {}).get("objectives", [])
        ]
        primary_source_targets = [str(value) for value in (plan_data or {}).get("primary_source_targets", [])]
        known_evidence_gaps = [str(value) for value in (plan_data or {}).get("known_evidence_gaps", [])]
        query_rows = db.scalars(select(SearchQuery).where(SearchQuery.run_id == run.id)).all()
        queries = [
            SearchQueryOutput(
                query=row.query_text,
                objective_ref=row.generated_by_node.removeprefix("planner:"),
                intent=EvidenceIntent(row.family),
                priority=float(row.priority) if row.priority is not None else 0.5,
            )
            for row in query_rows
        ]
        if normalized is not None and claims and objectives and queries:
            return None
        completed: list[WorkflowStage] = []
        if normalized is not None:
            completed.append(WorkflowStage.INTAKE)
        if claims:
            completed.append(WorkflowStage.DECOMPOSITION)
        initial = VerificationState(
            run_id=run.id,
            user_id=run.user_id,
            research_depth=ResearchDepth(run.research_depth.value),
            methodology_version=methodology.version if methodology is not None else "1.0",
            workflow_version=run.workflow_version,
            parser_versions={
                str(key): str(value) for key, value in run.parser_versions.items()
            },
            started_at=_as_utc(run.started_at or run.queued_at),
            normalized_input=normalized,
            claims=claims,
            objectives=objectives,
            queries=queries,
            primary_source_targets=primary_source_targets,
            known_evidence_gaps=known_evidence_gaps,
            completed_stages=completed,
        )

    async def invoke() -> VerificationState:
        owns_model = model is None
        client = model or DeepSeekClient()
        try:
            services = WorkflowServices(
                model=client,
                submitted_input=submitted_input,
                expected_input_kind=_INPUT_KINDS[run.input_type],
                progress=DurableProgressWriter(
                    lambda **kwargs: record(
                        factory,
                        redis_client,
                        settings,
                        **kwargs,
                    )
                ),
                cancellation=RunCancellationChecker(
                    lambda checked_run_id: is_cancelled(factory, redis_client, checked_run_id)
                ),
                state_writer=SqlWorkflowStateWriter(factory),
            )
            result = await build_workflow(services, planning_only=True).ainvoke(initial)
            return VerificationState.model_validate(result)
        finally:
            if owns_model:
                await client.aclose()

    return asyncio.run(invoke())


_INPUT_KINDS = {
    InputType.CLAIM: InputKind.CLAIM,
    InputType.ARTICLE_URL: InputKind.ARTICLE_URL,
    InputType.ARTICLE_TEXT: InputKind.ARTICLE_TEXT,
    InputType.QUOTE: InputKind.QUOTE,
    InputType.PARAPHRASE: InputKind.PARAPHRASE,
    InputType.UPLOADED_DOCUMENT: InputKind.DOCUMENT,
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


__all__ = [
    "DurableProgressWriter",
    "RunCancellationChecker",
    "SqlWorkflowStateWriter",
    "execute_planning_workflow",
]
