"""Production adapters connecting typed graph nodes to durable run services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID
from urllib.parse import urlsplit

import boto3
from botocore.config import Config as BotoConfig
from redis import Redis
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from agents.deepseek_client import DeepSeekClient
from agents.schemas import (
    AtomicClaimOutput,
    ClaimKind,
    EvidenceIntent,
    Entailment,
    FactCheckability,
    Importance,
    InputKind,
    IntakeClassificationOutput,
    ResearchObjectiveOutput,
    SearchQueryOutput,
)
from app.config import Settings
from app.models.claims import AtomicClaim, SearchQuery
from app.models.enums import AccessStatus, DependencyRelationship, EvidenceStance, InputType, RunStatus, SourceType
from app.models.evidence import EvidenceItem, ReportCitation
from app.models.records import Calculation
from app.models.methodology import MethodologyVersion
from app.models.provenance import InformationCluster, SourceDependency
from app.models.sources import RunSource, Source, SourcePassage, SourceSnapshot
from app.models.verification_run import VerificationRun
from graph.state import ResearchDepth, VerificationState, WorkflowStage
from graph.workflow import WorkflowExtensions, WorkflowServices, build_workflow
from extraction.service import ExtractionService
from extraction.playwright import PlaywrightExtractor, PlaywrightLimits
from extraction.passages import PassageEmbeddingService, PassagePipeline, PassageSegmenter
from research.cache import RetrievalCache, RetrievalRateLimiter
from research.fetcher import S3SnapshotStore, SecureFetcher, SnapshotFileStore
from research.pipeline import RetrievalPipeline
from research.search import BraveSearchClient
from research.url_guard import UrlGuard
from provenance.dependencies import ProvenancePipeline
from scoring.service import DeterministicScoringService
from auditing.numerical import NumericalAuditor


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
    WorkflowStage.CITATION_REVISION: RunStatus.AUDITING,
    WorkflowStage.CITATION_AUDIT: RunStatus.AUDITING,
}


def _uses_s3_snapshot_store(settings: Settings) -> bool:
    return bool(
        settings.s3_access_key_id and settings.s3_secret_access_key
    ) or settings.environment in {"staging", "production"}


def _s3_client_options(settings: Settings) -> dict[str, object]:
    options: dict[str, object] = {
        "endpoint_url": settings.s3_endpoint_url,
        "region_name": settings.s3_region,
        "config": BotoConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_force_path_style else "virtual"},
        ),
    }
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        options.update(
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
    return options


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
    """Persist typed workflow outputs at their durable stage boundaries."""

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
            elif stage == WorkflowStage.DISCOVERY and state.query_result_counts:
                self._persist_search_execution(db, run, state)
            elif (
                stage == WorkflowStage.EXTRACTION
                and WorkflowStage.EXTRACTION in state.completed_stages
                and state.snapshots
            ):
                self._persist_sources(db, run, state)
            elif (
                stage == WorkflowStage.SEGMENTATION
                and WorkflowStage.SEGMENTATION in state.completed_stages
            ):
                self._persist_passages(db, run, state)
            elif (
                stage == WorkflowStage.PROVENANCE
                and WorkflowStage.PROVENANCE in state.completed_stages
            ):
                self._persist_provenance(db, run, state)
            elif (
                stage == WorkflowStage.SCORING
                and WorkflowStage.SCORING in state.completed_stages
                and state.scores is not None
            ):
                self._persist_scoring(db, run, state)
            elif (
                stage == WorkflowStage.NUMERICAL_AUDIT
                and WorkflowStage.NUMERICAL_AUDIT in state.completed_stages
            ):
                self._persist_calculations(db, run, state)
            elif stage == WorkflowStage.SYNTHESIS and state.report_draft is not None:
                run.title = state.report_draft.title
                run.evidence_reviewed_at = state.evidence_reviewed_at
            elif stage == WorkflowStage.CITATION_REVISION and state.report_draft is not None:
                run.title = state.report_draft.title
                run.evidence_reviewed_at = state.evidence_reviewed_at
            elif stage == WorkflowStage.CITATION_AUDIT and state.citation_audit is not None:
                self._persist_citation_audit(db, run, state)
            self._persist_model_metadata(run, state)
            db.commit()

    @staticmethod
    def _persist_search_execution(db: Session, run: VerificationRun, state: VerificationState) -> None:
        executed_at = datetime.now(UTC)
        rows = db.scalars(select(SearchQuery).where(SearchQuery.run_id == run.id)).all()
        for row in rows:
            key = f"{row.generated_by_node.removeprefix('planner:')}:{row.query_text}"
            if key in state.query_result_counts:
                row.executed_at = executed_at
                row.result_count = state.query_result_counts[key]

    @staticmethod
    def _persist_sources(db: Session, run: VerificationRun, state: VerificationState) -> None:
        candidates = {item.source_ref: item for item in state.candidate_sources}
        extracted = {item.source_ref: item for item in state.extracted_sources}
        for rank, snapshot in enumerate(state.snapshots, start=1):
            if snapshot.snapshot_path and urlsplit(snapshot.snapshot_path).scheme in {"http", "https"}:
                raise ValueError("permanent public snapshot URLs are not allowed")
            candidate = candidates[snapshot.source_ref]
            canonical_url = candidate.canonical_url or candidate.url
            source = db.scalar(select(Source).where(Source.canonical_url == canonical_url))
            document = extracted.get(snapshot.source_ref)
            if source is None:
                source = Source(
                    canonical_url=canonical_url,
                    domain=candidate.domain or "",
                    title=document.title if document else candidate.title,
                    author=document.author if document else None,
                    publisher=document.publisher if document else None,
                    source_type=SourceType(candidate.source_type),
                    content_type=snapshot.content_type,
                    first_seen_at=snapshot.retrieved_at,
                    last_seen_at=snapshot.retrieved_at,
                )
                db.add(source)
                db.flush()
            else:
                source.last_seen_at = snapshot.retrieved_at
                source.title = source.title or (document.title if document else candidate.title)
                source.author = source.author or (document.author if document else None)
                source.publisher = source.publisher or (document.publisher if document else None)
                source.content_type = snapshot.content_type or source.content_type
            snapshot_id = UUID(snapshot.snapshot_id)
            durable_snapshot = db.get(SourceSnapshot, snapshot_id)
            if durable_snapshot is None:
                version = (db.scalar(select(func.max(SourceSnapshot.version_number)).where(SourceSnapshot.source_id == source.id)) or 0) + 1
                durable_snapshot = SourceSnapshot(
                    id=snapshot_id,
                    source_id=source.id,
                    version_number=version,
                    retrieved_at=snapshot.retrieved_at,
                    published_at=snapshot.published_at,
                    updated_at=snapshot.updated_at,
                    access_status=AccessStatus(snapshot.access_status),
                    content_hash=snapshot.content_hash,
                    snapshot_path=snapshot.snapshot_path,
                    parser_name=snapshot.parser_name,
                    parser_version=snapshot.parser_version,
                    extraction_quality=snapshot.extraction_quality,
                    correction_status=(
                        "NOTICE_DETECTED"
                        if document is not None and document.correction_notices
                        else None
                    ),
                    snapshot_metadata=snapshot.metadata,
                    failure_reason=snapshot.failure_reason,
                )
                db.add(durable_snapshot)
                db.flush()
            run_source = db.get(RunSource, (run.id, source.id))
            if run_source is None:
                run_source = RunSource(run_id=run.id, source_id=source.id, role=candidate.source_type)
                db.add(run_source)
            run_source.snapshot_id = durable_snapshot.id
            run_source.retrieval_reason = candidate.selection_reason
            run_source.priority_score = candidate.priority
            run_source.selected_rank = rank
            run_source.inaccessible_reason = (
                snapshot.failure_reason if snapshot.access_status != AccessStatus.FETCHED.value else None
            )
        run.parser_versions = dict(state.parser_versions)

    @staticmethod
    def _persist_passages(db: Session, run: VerificationRun, state: VerificationState) -> None:
        source_by_snapshot = {
            str(snapshot_id): source_id
            for snapshot_id, source_id in db.execute(
                select(RunSource.snapshot_id, RunSource.source_id).where(
                    RunSource.run_id == run.id,
                    RunSource.snapshot_id.is_not(None),
                )
            )
        }
        for passage in state.passages:
            source_id = source_by_snapshot.get(passage.snapshot_id)
            if source_id is None:
                raise ValueError("passage snapshot is not attached to this verification run")
            snapshot_id = UUID(passage.snapshot_id)
            existing = db.scalar(
                select(SourcePassage).where(
                    SourcePassage.snapshot_id == snapshot_id,
                    SourcePassage.text_hash == passage.text_hash,
                )
            )
            if existing is None:
                existing = SourcePassage(
                    id=UUID(passage.passage_id),
                    snapshot_id=snapshot_id,
                    source_id=source_id,
                    text=passage.text,
                    text_hash=passage.text_hash,
                    extraction_certainty=passage.extraction_certainty,
                )
                db.add(existing)
            existing.heading_path = passage.heading_path
            existing.page_or_position = passage.page_or_position
            existing.paragraph_index = passage.paragraph_index
            existing.speaker = passage.speaker
            existing.table_ref = passage.table_ref
            existing.embedding = passage.embedding
            existing.embedding_model = passage.embedding_model
            existing.passage_metadata = passage.metadata
        models = dict(run.model_versions)
        models["embedding"] = {
            **(
                state.embedding_run_metadata.model_dump(mode="json")
                if state.embedding_run_metadata is not None
                else {
                    "provider": "deepseek",
                    "configured_model": state.embedding_model_version,
                    "used_model": state.embedding_model_version,
                    "status": (
                        "embedded"
                        if state.embedding_model_version
                        else "unconfigured_fallback"
                    ),
                }
            ),
            "retrieval_mode": state.passage_retrieval_mode,
        }
        run.model_versions = models

    @staticmethod
    def _persist_provenance(db: Session, run: VerificationRun, state: VerificationState) -> None:
        snapshot_by_ref = {
            snapshot.source_ref: UUID(snapshot.snapshot_id) for snapshot in state.snapshots
        }
        source_by_snapshot = {
            snapshot_id: source_id
            for snapshot_id, source_id in db.execute(
                select(RunSource.snapshot_id, RunSource.source_id).where(
                    RunSource.run_id == run.id,
                    RunSource.snapshot_id.is_not(None),
                )
            )
        }
        source_by_ref = {
            source_ref: source_by_snapshot[snapshot_id]
            for source_ref, snapshot_id in snapshot_by_ref.items()
            if snapshot_id in source_by_snapshot
        }
        expected_refs = {source.source_ref for source in state.candidate_sources}
        if expected_refs - source_by_ref.keys():
            raise ValueError("provenance source is not attached to this verification run")

        db.execute(delete(SourceDependency).where(SourceDependency.run_id == run.id))
        db.execute(delete(InformationCluster).where(InformationCluster.run_id == run.id))
        for cluster in state.information_clusters:
            db.add(
                InformationCluster(
                    id=UUID(cluster.cluster_ref),
                    run_id=run.id,
                    label=cluster.label,
                    origin_type=cluster.origin_type,
                    representative_source_id=source_by_ref[cluster.representative_source_ref],
                )
            )
        db.flush()
        for edge in state.dependencies:
            db.add(
                SourceDependency(
                    run_id=run.id,
                    parent_source_id=source_by_ref[edge.parent_source_ref],
                    child_source_id=source_by_ref[edge.child_source_ref],
                    relationship=DependencyRelationship(edge.relationship),
                    confidence=edge.confidence,
                    detection_method=edge.detection_method,
                    information_cluster_id=(
                        UUID(edge.information_cluster_ref)
                        if edge.information_cluster_ref is not None
                        else None
                    ),
                )
            )

    @staticmethod
    def _persist_scoring(db: Session, run: VerificationRun, state: VerificationState) -> None:
        claims = db.scalars(select(AtomicClaim).where(AtomicClaim.run_id == run.id)).all()
        claim_by_ref = {str(row.gates.get("claim_ref")): row for row in claims}
        claim_ids = [row.id for row in claims]
        if claim_ids:
            db.execute(delete(EvidenceItem).where(EvidenceItem.atomic_claim_id.in_(claim_ids)))
        db.execute(delete(Calculation).where(Calculation.run_id == run.id))
        stance_names = {
            Decimal("-1.00"): "STRONGLY_CONTRADICTS", Decimal("-0.50"): "PARTIALLY_CONTRADICTS",
            Decimal("0.00"): "NEUTRAL", Decimal("0.50"): "PARTIALLY_SUPPORTS",
            Decimal("1.00"): "STRONGLY_SUPPORTS",
        }
        classifications = {(item.claim_ref, item.passage_id): item for item in state.evidence}
        for item in state.scored_evidence:
            classification = classifications[(item.claim_ref, item.passage_id)]
            db.add(EvidenceItem(
                atomic_claim_id=claim_by_ref[item.claim_ref].id, passage_id=UUID(item.passage_id),
                stance=EvidenceStance[stance_names[item.stance_value]], stance_value=item.stance_value,
                relevance=Decimal(str(classification.quality.relevance)), directness=Decimal(str(classification.quality.directness)),
                authority=Decimal(str(classification.quality.claim_specific_authority)), transparency=Decimal(str(classification.quality.transparency)),
                temporal_fit=Decimal(str(classification.quality.temporal_fit)), extraction_certainty=Decimal(str(classification.quality.extraction_certainty)),
                base_quality=item.base_quality, dependency_multiplier=item.dependency_multiplier, adjusted_weight=item.adjusted_weight,
                rejection_reason=";".join(item.rejection_reasons) or None, citation_status="rejected" if item.rejection_reasons else "pending",
            ))
        SqlWorkflowStateWriter._add_calculations(db, run, state, claim_by_ref)
        for item in state.claim_scores:
            row = claim_by_ref[item.claim_ref]
            row.support_score, row.confidence_score = item.evidence_support, item.verdict_confidence
            row.context_completeness, row.final_label = item.context_completeness, item.final_label
            row.gates = {**row.gates, **item.gates, "adequate_evidence": item.adequate_evidence}
        run.evidence_support, run.verdict_confidence = state.scores.evidence_support, state.scores.verdict_confidence
        run.source_independence, run.context_completeness = state.scores.source_independence, state.scores.context_completeness
        run.verdict = state.scores.final_label

    @staticmethod
    def _persist_calculations(
        db: Session, run: VerificationRun, state: VerificationState
    ) -> None:
        claims = db.scalars(select(AtomicClaim).where(AtomicClaim.run_id == run.id)).all()
        claim_by_ref = {str(row.gates.get("claim_ref")): row for row in claims}
        db.execute(delete(Calculation).where(Calculation.run_id == run.id))
        SqlWorkflowStateWriter._add_calculations(db, run, state, claim_by_ref)

    @staticmethod
    def _add_calculations(db: Session, run: VerificationRun, state: VerificationState, claim_by_ref) -> None:
        for item in state.calculations:
            if item.claim_ref is not None and item.claim_ref not in claim_by_ref:
                raise ValueError("calculation references an unknown atomic claim")
            db.add(Calculation(id=UUID(item.calculation_ref), run_id=run.id,
                atomic_claim_id=claim_by_ref[item.claim_ref].id if item.claim_ref else None,
                formula_name=item.formula_name, formula_text=item.formula_text, inputs=item.inputs,
                result=item.result, units=item.units, decimal_context=item.decimal_context,
                audit_status=item.audit_status))

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
        sentence_groups = (
            ("summary", state.report_draft.summary_sentences),
            ("factual_finding", state.report_draft.factual_sentences),
            ("attribution", state.report_draft.attribution_findings),
            (
                "strongest_contradiction",
                [state.report_draft.strongest_credible_contradiction]
                if state.report_draft.strongest_credible_contradiction is not None
                else [],
            ),
        )
        sentences = {
            sentence.sentence_ref: (section, sentence)
            for section, group in sentence_groups
            for sentence in group
        }
        db.execute(delete(ReportCitation).where(ReportCitation.run_id == run.id))
        claim_ids = select(AtomicClaim.id).where(AtomicClaim.run_id == run.id)
        evidence_rows = db.scalars(
            select(EvidenceItem).where(EvidenceItem.atomic_claim_id.in_(claim_ids))
        ).all()
        for row in evidence_rows:
            if row.citation_status != "rejected":
                row.citation_status = "pending"
        accepted_passages: set[UUID] = set()
        for audit in state.citation_audit.sentence_audits:
            try:
                passage_id = UUID(audit.passage_id)
            except ValueError:
                raise ValueError("citation passage IDs must be durable UUIDs") from None
            report_section, sentence = sentences[audit.sentence_ref]
            passed = audit.entailment == Entailment.ENTAILED
            if passed:
                accepted_passages.add(passage_id)
            db.add(
                ReportCitation(
                    run_id=run.id,
                    report_section=report_section,
                    sentence_text=sentence.text,
                    passage_id=passage_id,
                    audit_status="passed" if passed else audit.entailment.value,
                    audit_note=audit.support_explanation,
                )
            )
        for row in evidence_rows:
            if row.passage_id in accepted_passages and row.citation_status != "rejected":
                row.citation_status = "accepted"


def execute_verification_workflow(
    factory: sessionmaker[Session],
    redis_client: Redis,
    settings: Settings,
    run_id: UUID,
    *,
    record,
    is_cancelled,
    model: DeepSeekClient | None = None,
    retrieve: bool = True,
    retrieval_pipeline: RetrievalPipeline | None = None,
    workflow_extensions: WorkflowExtensions | None = None,
) -> VerificationState | None:
    """Run the complete production verification workflow."""
    with factory() as db:
        run = db.get(VerificationRun, run_id)
        if run is None:
            raise LookupError(f"Verification run {run_id} does not exist")
        if run.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.QUEUED}:
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
        if normalized is not None and claims and objectives and queries and not retrieve:
            return None
        completed: list[WorkflowStage] = []
        if normalized is not None:
            completed.append(WorkflowStage.INTAKE)
        if claims:
            completed.append(WorkflowStage.DECOMPOSITION)
        if objectives and queries:
            completed.append(WorkflowStage.PLANNER)
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
        pipeline = retrieval_pipeline
        owns_pipeline = False
        try:
            if retrieve and pipeline is None and workflow_extensions is None:
                cache = RetrievalCache(
                    redis_client,
                    lock_ttl_seconds=settings.redis_lock_ttl_seconds,
                )
                search = BraveSearchClient(
                    provider=settings.search_provider,
                    api_key=settings.search_api_key,
                    base_url=settings.search_base_url,
                    cache=cache,
                    cache_ttl_seconds=settings.search_cache_ttl_seconds,
                )
                staging = SnapshotFileStore(settings.fetch_storage_dir)
                if _uses_s3_snapshot_store(settings):
                    object_client = boto3.client("s3", **_s3_client_options(settings))
                    snapshot_store = S3SnapshotStore(
                        client=object_client,
                        bucket=settings.s3_bucket_name,
                        staging=staging,
                        create_bucket_if_missing=settings.environment in {"development", "test"},
                        region=settings.s3_region,
                        server_side_encryption=settings.s3_server_side_encryption,
                    )
                else:
                    snapshot_store = staging
                fetcher = SecureFetcher(
                    guard=UrlGuard(allowed_ports=settings.allowed_fetch_ports),
                    store=snapshot_store,
                    connect_timeout=settings.fetch_connect_timeout_seconds,
                    read_timeout=settings.fetch_read_timeout_seconds,
                    total_timeout=settings.fetch_total_timeout_seconds,
                    max_redirects=settings.fetch_max_redirects,
                    max_html_bytes=settings.fetch_max_html_bytes,
                    max_pdf_bytes=settings.fetch_max_pdf_bytes,
                    cache=cache,
                    cache_ttl_seconds=settings.fetch_cache_ttl_seconds,
                    network_retries=settings.fetch_network_retries,
                )
                pipeline = RetrievalPipeline(
                    search=search,
                    fetcher=fetcher,
                    extractor=ExtractionService(
                        playwright_extractor=PlaywrightExtractor(
                            guard=fetcher.guard,
                            limits=PlaywrightLimits(
                                navigation_timeout_seconds=(
                                    settings.playwright_navigation_timeout_seconds
                                ),
                                total_timeout_seconds=settings.playwright_total_timeout_seconds,
                                max_response_bytes=settings.playwright_max_response_bytes,
                                max_total_response_bytes=(
                                    settings.playwright_max_total_response_bytes
                                ),
                                max_dom_bytes=settings.playwright_max_dom_bytes,
                                max_dom_nodes=settings.playwright_max_dom_nodes,
                                max_redirects=settings.fetch_max_redirects,
                                max_retries=settings.playwright_max_retries,
                                settle_time_ms=settings.playwright_settle_time_ms,
                            ),
                        )
                    ),
                    rate_limiter=RetrievalRateLimiter(redis_client),
                )
                owns_pipeline = True
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
                citation_revision_limit=settings.citation_revision_limit,
                extensions=workflow_extensions or (
                    WorkflowExtensions(
                        discovery_source_selection=pipeline.discover,
                        secure_retrieval=pipeline.retrieve,
                        extraction=pipeline.extract,
                        passage_segmentation_embedding=PassagePipeline(
                            PassageSegmenter(),
                            PassageEmbeddingService(
                                client,
                                expected_dimension=settings.passage_embedding_dimension,
                            ),
                        ).process,
                        provenance_dependency_analysis=ProvenancePipeline().process,
                        deterministic_scoring=DeterministicScoringService().process,
                        numerical_audit=NumericalAuditor().process,
                    )
                    if pipeline is not None else WorkflowExtensions()
                ),
            )
            result = await build_workflow(services, planning_only=not retrieve).ainvoke(initial)
            return VerificationState.model_validate(result)
        finally:
            if pipeline is not None and owns_pipeline:
                await pipeline.aclose()
            if owns_model:
                await client.aclose()

    return asyncio.run(invoke())


def execute_planning_workflow(*args, **kwargs) -> VerificationState | None:
    """Compatibility wrapper for callers that intentionally stop after planning."""
    kwargs.setdefault("retrieve", False)
    return execute_verification_workflow(*args, **kwargs)


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
    "execute_verification_workflow",
    "execute_planning_workflow",
]
