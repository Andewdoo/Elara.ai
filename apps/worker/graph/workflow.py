"""LangGraph nodes and assembly for Elara's controlled verification workflow."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from agents.citation_audit import PROMPT_VERSION as CITATION_AUDIT_PROMPT_VERSION
from agents.citation_audit import SYSTEM_PROMPT as CITATION_AUDIT_PROMPT
from agents.decomposition import PROMPT_VERSION as DECOMPOSITION_PROMPT_VERSION
from agents.decomposition import SYSTEM_PROMPT as DECOMPOSITION_PROMPT
from agents.deepseek_client import DeepSeekError, StructuredResponse
from agents.evidence_classification import PROMPT_VERSION as EVIDENCE_PROMPT_VERSION
from agents.evidence_classification import SYSTEM_PROMPT as EVIDENCE_PROMPT
from agents.intake import PROMPT_VERSION as INTAKE_PROMPT_VERSION
from agents.intake import SYSTEM_PROMPT as INTAKE_PROMPT
from agents.planning import PROMPT_VERSION as PLANNER_PROMPT_VERSION
from agents.planning import SYSTEM_PROMPT as PLANNER_PROMPT
from agents.schemas import (
    CitationAuditOutput,
    DecompositionOutput,
    Entailment,
    EvidenceClassificationOutput,
    FactCheckability,
    InputKind,
    IntakeClassificationOutput,
    PlanningOutput,
    SentenceCitationAuditOutput,
    SynthesisOutput,
)
from agents.synthesis import PROMPT_VERSION as SYNTHESIS_PROMPT_VERSION
from agents.synthesis import SYSTEM_PROMPT as SYNTHESIS_PROMPT
from graph.state import RecoverableError, VerificationState, WorkflowStage
from graph.transitions import (
    citation_audit_ready,
    evidence_ready,
    stop_requested,
    synthesis_ready,
)


PROMPT_VERSIONS = {
    WorkflowStage.INTAKE: INTAKE_PROMPT_VERSION,
    WorkflowStage.DECOMPOSITION: DECOMPOSITION_PROMPT_VERSION,
    WorkflowStage.PLANNER: PLANNER_PROMPT_VERSION,
    WorkflowStage.EVIDENCE_CLASSIFICATION: EVIDENCE_PROMPT_VERSION,
    WorkflowStage.SYNTHESIS: SYNTHESIS_PROMPT_VERSION,
    WorkflowStage.CITATION_AUDIT: CITATION_AUDIT_PROMPT_VERSION,
}

_STAGE_NUMBERS = {stage: index for index, stage in enumerate(WorkflowStage, start=1)}
_TOTAL_STAGES = len(WorkflowStage)


class StructuredModelClient(Protocol):
    async def generate_structured(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: type,
        prompt_version: str,
        model_role: str = "chat",
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> StructuredResponse: ...


class ProgressWriter(Protocol):
    async def publish(
        self,
        *,
        run_id: UUID,
        stage: WorkflowStage,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None: ...


class CancellationChecker(Protocol):
    async def is_cancelled(self, run_id: UUID) -> bool: ...


class StateWriter(Protocol):
    async def save(self, *, stage: WorkflowStage, state: VerificationState) -> None: ...


ExtensionNode = Callable[[VerificationState], Awaitable[VerificationState]]


class NullProgressWriter:
    async def publish(self, **_: object) -> None:
        return None


class NullCancellationChecker:
    async def is_cancelled(self, _run_id: UUID) -> bool:
        return False


class NullStateWriter:
    async def save(self, **_: object) -> None:
        return None


@dataclass(slots=True)
class WorkflowExtensions:
    """Typed hooks implemented by Steps 9-13 without changing graph state."""

    discovery_source_selection: ExtensionNode | None = None
    secure_retrieval: ExtensionNode | None = None
    extraction: ExtensionNode | None = None
    passage_segmentation_embedding: ExtensionNode | None = None
    provenance_dependency_analysis: ExtensionNode | None = None
    deterministic_scoring: ExtensionNode | None = None
    numerical_audit: ExtensionNode | None = None


@dataclass(slots=True)
class WorkflowServices:
    model: StructuredModelClient
    submitted_input: str
    expected_input_kind: InputKind | None = None
    progress: ProgressWriter = field(default_factory=NullProgressWriter)
    cancellation: CancellationChecker = field(default_factory=NullCancellationChecker)
    state_writer: StateWriter = field(default_factory=NullStateWriter)
    extensions: WorkflowExtensions = field(default_factory=WorkflowExtensions)

class WorkflowNodes:
    def __init__(self, services: WorkflowServices) -> None:
        self.services = services

    async def _begin(self, state: VerificationState, stage: WorkflowStage) -> VerificationState | None:
        if await self.services.cancellation.is_cancelled(state.run_id):
            cancelled = state.model_copy(update={"cancelled": True})
            await self.services.progress.publish(
                run_id=state.run_id,
                stage=stage,
                event_type="run.cancelled",
                message="Verification cancelled before the next expensive stage.",
                payload=_stage_progress(stage, completed=False),
            )
            await self.services.state_writer.save(stage=stage, state=cancelled)
            return cancelled
        await self.services.progress.publish(
            run_id=state.run_id,
            stage=stage,
            event_type=f"workflow.{stage.value}.started",
            message=_START_MESSAGES[stage],
            payload=_stage_progress(stage, completed=False),
        )
        return None

    async def _finish(
        self,
        state: VerificationState,
        stage: WorkflowStage,
        *,
        payload: dict[str, object] | None = None,
    ) -> VerificationState:
        await self.services.state_writer.save(stage=stage, state=state)
        public_payload = {**_stage_progress(stage, completed=True), **(payload or {})}
        await self.services.progress.publish(
            run_id=state.run_id,
            stage=stage,
            event_type=f"workflow.{stage.value}.completed",
            message=_COMPLETE_MESSAGES[stage],
            payload=public_payload,
        )
        return state

    async def _failure(
        self,
        state: VerificationState,
        stage: WorkflowStage,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, str | int | bool | None] | None = None,
    ) -> VerificationState:
        failed = state.with_error(
            RecoverableError(
                stage=stage,
                code=code,
                public_message=message,
                retryable=retryable,
                details=details or {},
            )
        )
        await self.services.state_writer.save(stage=stage, state=failed)
        public_details = details or {}
        await self.services.progress.publish(
            run_id=state.run_id,
            stage=stage,
            event_type=f"workflow.{stage.value}.recoverable_failure",
            message=message,
            payload={
                **_stage_progress(stage, completed=False),
                "code": code,
                "retryable": retryable,
                "details": public_details,
            },
        )
        return failed

    async def _call(
        self,
        state: VerificationState,
        stage: WorkflowStage,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: type,
        max_tokens: int,
    ) -> StructuredResponse | VerificationState:
        try:
            return await self.services.model.generate_structured(
                messages=messages,
                output_schema=output_schema,
                prompt_version=PROMPT_VERSIONS[stage],
                model_role="chat",
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except DeepSeekError as exc:
            return await self._failure(
                state,
                stage,
                code="DEEPSEEK_LANGUAGE_STEP_FAILED",
                message="A language-analysis step could not be completed.",
                retryable=exc.metadata.retryable,
                details={
                    "provider": exc.metadata.provider,
                    "model": exc.metadata.model,
                    "status_code": exc.metadata.status_code,
                    "error_code": exc.metadata.error_code,
                },
            )

    async def intake(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.INTAKE in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.INTAKE):
            return cancelled
        if not self.services.submitted_input.strip() or len(self.services.submitted_input) > 100_000:
            return await self._failure(
                state,
                WorkflowStage.INTAKE,
                code="INVALID_INPUT_SIZE",
                message="The submitted target is empty or exceeds the supported size.",
            )
        response = await self._call(
            state,
            WorkflowStage.INTAKE,
            messages=[
                {"role": "system", "content": INTAKE_PROMPT},
                {"role": "user", "content": self.services.submitted_input},
            ],
            output_schema=IntakeClassificationOutput,
            max_tokens=2500,
        )
        if isinstance(response, VerificationState):
            return response
        output = response.output
        if (
            self.services.expected_input_kind is not None
            and output.input_kind != self.services.expected_input_kind
        ):
            return await self._failure(
                state,
                WorkflowStage.INTAKE,
                code="INPUT_TYPE_MISMATCH",
                message="Language analysis did not preserve the submitted input type.",
            )
        if not output.normalized_text.strip() or len(output.normalized_text) > 100_000:
            return await self._failure(
                state,
                WorkflowStage.INTAKE,
                code="INVALID_NORMALIZED_INPUT",
                message="The submitted target could not be normalized safely.",
            )
        if output.input_kind.value == "article_url":
            submitted_url = self.services.submitted_input.strip()
            parsed = urlsplit(submitted_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username
                or parsed.password
            ):
                return await self._failure(
                    state,
                    WorkflowStage.INTAKE,
                    code="INVALID_NORMALIZED_URL",
                    message="The submitted article URL could not be normalized safely.",
                )
            output = output.model_copy(update={"normalized_text": submitted_url})
        updated = state.complete(
            WorkflowStage.INTAKE,
            normalized_input=output,
            model_calls={**state.model_calls, WorkflowStage.INTAKE.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.INTAKE,
            payload={"fact_checkability": output.fact_checkability.value},
        )

    async def decomposition(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.DECOMPOSITION in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.DECOMPOSITION):
            return cancelled
        if state.normalized_input is None:
            return await self._failure(
                state,
                WorkflowStage.DECOMPOSITION,
                code="NORMALIZED_INPUT_REQUIRED",
                message="Claim decomposition requires normalized input.",
            )
        response = await self._call(
            state,
            WorkflowStage.DECOMPOSITION,
            messages=[
                {"role": "system", "content": DECOMPOSITION_PROMPT},
                {"role": "user", "content": _json(state.normalized_input)},
            ],
            output_schema=DecompositionOutput,
            max_tokens=5000,
        )
        if isinstance(response, VerificationState):
            return response
        output = response.output
        refs = {claim.claim_ref for claim in output.atomic_claims}
        claim_limit = {"QUICK": 12, "STANDARD": 25, "DEEP": 50}[state.research_depth.value]
        normalized_claims = [" ".join(claim.text.casefold().split()) for claim in output.atomic_claims]
        invalid_spans = any(
            claim.original_text_span is not None
            and claim.original_text_span not in state.normalized_input.normalized_text
            for claim in output.atomic_claims
        )
        if (
            len(output.atomic_claims) > claim_limit
            or len(normalized_claims) != len(set(normalized_claims))
            or any(
                claim.parent_claim_ref is not None and claim.parent_claim_ref not in refs
                for claim in output.atomic_claims
            )
            or _has_claim_cycle(output)
            or invalid_spans
        ):
            return await self._failure(
                state,
                WorkflowStage.DECOMPOSITION,
                code="INVALID_CLAIM_GRAPH",
                message="Claim decomposition returned invalid claim references.",
            )
        updated = state.complete(
            WorkflowStage.DECOMPOSITION,
            claims=output.atomic_claims,
            unresolved_ambiguities=output.unresolved_ambiguities,
            model_calls={**state.model_calls, WorkflowStage.DECOMPOSITION.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.DECOMPOSITION,
            payload={"claim_count": len(output.atomic_claims)},
        )

    async def planner(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.PLANNER in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.PLANNER):
            return cancelled
        if not state.claims:
            return await self._failure(
                state,
                WorkflowStage.PLANNER,
                code="CLAIMS_REQUIRED",
                message="Research planning requires at least one atomic claim.",
            )
        response = await self._call(
            state,
            WorkflowStage.PLANNER,
            messages=[
                {"role": "system", "content": PLANNER_PROMPT},
                {"role": "user", "content": _json(state.claims)},
            ],
            output_schema=PlanningOutput,
            max_tokens=6000,
        )
        if isinstance(response, VerificationState):
            return response
        output = response.output
        claim_refs = {claim.claim_ref for claim in state.claims}
        objective_refs = {objective.objective_ref for objective in output.objectives}
        query_limit = {"QUICK": 24, "STANDARD": 60, "DEEP": 120}[state.research_depth.value]
        planned_claim_refs = {objective.claim_ref for objective in output.objectives}
        query_texts = [" ".join(query.query.casefold().split()) for query in output.queries]
        objective_by_ref = {objective.objective_ref: objective for objective in output.objectives}
        intents_by_claim: dict[str, set[str]] = {claim_ref: set() for claim_ref in claim_refs}
        for query in output.queries:
            objective = objective_by_ref.get(query.objective_ref)
            if objective is not None:
                intents_by_claim[objective.claim_ref].add(query.intent.value)
        fact_checkable_claim_refs = {
            claim.claim_ref
            for claim in state.claims
            if claim.fact_checkability != FactCheckability.NOT_FACT_CHECKABLE
        }
        required_paths_missing = any(
            not {"primary", "contradiction"}.issubset(intents_by_claim[claim_ref])
            for claim_ref in fact_checkable_claim_refs
        )
        attribution_required = bool(
            state.normalized_input
            and state.normalized_input.requires_attribution_check
        ) or any(claim.claim_kind.value in {"quotation", "attribution"} for claim in state.claims)
        attribution_missing = attribution_required and not any(
            query.intent.value == "attribution" for query in output.queries
        )
        exact_quote_missing = (
            state.normalized_input is not None
            and state.normalized_input.input_kind.value == "quote"
            and len(state.normalized_input.normalized_text) <= 300
            and not any(state.normalized_input.normalized_text in query.query for query in output.queries)
        )
        invalid = (
            len(objective_refs) != len(output.objectives)
            or any(objective.claim_ref not in claim_refs for objective in output.objectives)
            or planned_claim_refs != claim_refs
            or len(output.queries) > query_limit
            or len(query_texts) != len(set(query_texts))
            or required_paths_missing
            or attribution_missing
            or exact_quote_missing
            or any(query.objective_ref not in objective_refs for query in output.queries)
            or any(
                query.objective_ref in objective_by_ref
                and query.intent != objective_by_ref[query.objective_ref].intent
                for query in output.queries
            )
        )
        if invalid:
            return await self._failure(
                state,
                WorkflowStage.PLANNER,
                code="INVALID_RESEARCH_PLAN",
                message="Research planning returned invalid claim or objective references.",
            )
        updated = state.complete(
            WorkflowStage.PLANNER,
            objectives=output.objectives,
            queries=output.queries,
            primary_source_targets=output.primary_source_targets,
            known_evidence_gaps=output.known_evidence_gaps,
            model_calls={**state.model_calls, WorkflowStage.PLANNER.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.PLANNER,
            payload={"objective_count": len(output.objectives), "query_count": len(output.queries)},
        )

    async def evidence_classification(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.EVIDENCE_CLASSIFICATION in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.EVIDENCE_CLASSIFICATION):
            return cancelled
        if not state.claims or not state.passages:
            return await self._failure(
                state,
                WorkflowStage.EVIDENCE_CLASSIFICATION,
                code="EVIDENCE_INPUTS_REQUIRED",
                message="Evidence classification requires claims and extracted passages.",
            )
        response = await self._call(
            state,
            WorkflowStage.EVIDENCE_CLASSIFICATION,
            messages=[
                {"role": "system", "content": EVIDENCE_PROMPT},
                {"role": "user", "content": _json({"claims": state.claims, "passages": state.passages})},
            ],
            output_schema=EvidenceClassificationOutput,
            max_tokens=8000,
        )
        if isinstance(response, VerificationState):
            return response
        output = response.output
        claim_refs = {claim.claim_ref for claim in state.claims}
        passages = {passage.passage_id: passage for passage in state.passages}
        pairs = [(item.claim_ref, item.passage_id) for item in output.classifications]
        invalid = (
            len(pairs) != len(set(pairs))
            or any(
                item.claim_ref not in claim_refs or item.passage_id not in passages
                for item in output.classifications
            )
        )
        if invalid:
            return await self._failure(
                state,
                WorkflowStage.EVIDENCE_CLASSIFICATION,
                code="INVALID_EVIDENCE_REFERENCES",
                message="Evidence classification referenced unavailable claims or passages.",
            )
        guarded_classifications = []
        for item in output.classifications:
            reasons = list(item.recommended_rejection_reasons)
            passage = passages.get(item.passage_id)
            if passage is None:
                continue
            quality = item.quality.model_copy(
                update={"extraction_certainty": float(passage.extraction_certainty)}
            )
            deterministic_reasons = []
            if item.quality.relevance < 0.50:
                deterministic_reasons.append("relevance_below_threshold")
            if passage is not None and passage.extraction_certainty < 0.65:
                deterministic_reasons.append("extraction_certainty_below_threshold")
            if not item.entity_match:
                deterministic_reasons.append("entity_mismatch")
            if not item.time_period_match:
                deterministic_reasons.append("time_period_mismatch")
            if item.quotation_or_number_located is False:
                deterministic_reasons.append("quotation_or_number_not_located")
            for reason in deterministic_reasons:
                if reason not in reasons:
                    reasons.append(reason)
            guarded_classifications.append(
                item.model_copy(
                    update={
                        "quality": quality,
                        "recommended_rejection_reasons": reasons,
                    }
                )
            )
        updated = state.complete(
            WorkflowStage.EVIDENCE_CLASSIFICATION,
            evidence=guarded_classifications,
            model_calls={
                **state.model_calls,
                WorkflowStage.EVIDENCE_CLASSIFICATION.value: response.metadata,
            },
        )
        return await self._finish(
            updated,
            WorkflowStage.EVIDENCE_CLASSIFICATION,
            payload={"classification_count": len(output.classifications)},
        )

    async def synthesis(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.SYNTHESIS in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.SYNTHESIS):
            return cancelled
        if not state.evidence or state.scores is None:
            return await self._failure(
                state,
                WorkflowStage.SYNTHESIS,
                code="APPROVED_EVIDENCE_REQUIRED",
                message="Report synthesis requires classified evidence and deterministic scores.",
            )
        approved_passage_ids = _approved_passage_ids(state)
        if not approved_passage_ids:
            return await self._failure(
                state,
                WorkflowStage.SYNTHESIS,
                code="NO_APPROVED_EVIDENCE",
                message="No approved evidence passages are available for report synthesis.",
            )
        passages = [p for p in state.passages if p.passage_id in approved_passage_ids]
        response = await self._call(
            state,
            WorkflowStage.SYNTHESIS,
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {
                    "role": "user",
                    "content": _json(
                        {
                            "claims": state.claims,
                            "approved_evidence": state.evidence,
                            "approved_passages": passages,
                            "source_snapshots": state.snapshots,
                            "scores": state.scores,
                            "methodology_version": state.methodology_version,
                        }
                    ),
                },
            ],
            output_schema=SynthesisOutput,
            max_tokens=8000,
        )
        if isinstance(response, VerificationState):
            return response
        cited = {pid for sentence in _sentences(response.output) for pid in sentence.passage_ids}
        if not cited.issubset(approved_passage_ids):
            return await self._failure(
                state,
                WorkflowStage.SYNTHESIS,
                code="UNAPPROVED_REPORT_CITATION",
                message="The report draft cited a passage that was not approved as evidence.",
            )
        has_contradiction = any(
            item.passage_id in approved_passage_ids and "contradicts" in item.stance.value
            for item in state.evidence
        )
        if has_contradiction and response.output.strongest_credible_contradiction is None:
            return await self._failure(
                state,
                WorkflowStage.SYNTHESIS,
                code="CONTRADICTION_OMITTED",
                message="The report draft omitted the strongest credible contradiction.",
            )
        reviewed_at = state.evidence_reviewed_at
        if reviewed_at is None and state.snapshots:
            reviewed_at = max(snapshot.retrieved_at for snapshot in state.snapshots)
        reviewed_at = reviewed_at or datetime.now(UTC)
        timestamp = (
            f"Evidence reviewed as of {reviewed_at.isoformat()}. "
            "New evidence or corrections may change this assessment."
        )
        inaccessible_notes = list(response.output.inaccessible_source_notes)
        for snapshot in state.snapshots:
            if snapshot.access_status.upper() == "FETCHED":
                continue
            note = f"Source {snapshot.source_ref} was {snapshot.access_status.lower()}"
            if snapshot.failure_reason:
                note += f": {snapshot.failure_reason}"
            if note not in inaccessible_notes:
                inaccessible_notes.append(note)
        model_versions = {
            stage: metadata.model for stage, metadata in state.model_calls.items()
        }
        model_versions[WorkflowStage.SYNTHESIS.value] = response.metadata.model
        prompt_versions = {
            stage: metadata.prompt_version for stage, metadata in state.model_calls.items()
        }
        prompt_versions[WorkflowStage.SYNTHESIS.value] = response.metadata.prompt_version
        guarded_report = response.output.model_copy(
            update={
                "inaccessible_source_notes": inaccessible_notes,
                "evidence_reviewed_at": reviewed_at,
                "evidence_timestamp": timestamp,
                "methodology_version": state.methodology_version,
                "workflow_version": state.workflow_version,
                "model_versions": model_versions,
                "prompt_versions": prompt_versions,
                "parser_versions": state.parser_versions,
            }
        )
        updated = state.complete(
            WorkflowStage.SYNTHESIS,
            report_draft=guarded_report,
            evidence_reviewed_at=reviewed_at,
            model_calls={**state.model_calls, WorkflowStage.SYNTHESIS.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.SYNTHESIS,
            payload={"sentence_count": len(_sentences(response.output))},
        )

    async def citation_audit(self, state: VerificationState) -> VerificationState:
        if WorkflowStage.CITATION_AUDIT in state.completed_stages:
            return state
        if cancelled := await self._begin(state, WorkflowStage.CITATION_AUDIT):
            return cancelled
        if state.report_draft is None:
            return await self._failure(
                state,
                WorkflowStage.CITATION_AUDIT,
                code="REPORT_DRAFT_REQUIRED",
                message="Citation audit requires an evidence-grounded report draft.",
            )
        passage_map = {p.passage_id: p for p in state.passages}
        approved_passages = _approved_passage_ids(state)
        report_passages = {
            passage_id for sentence in _sentences(state.report_draft) for passage_id in sentence.passage_ids
        }
        if not report_passages.issubset(passage_map):
            return await self._failure(
                state,
                WorkflowStage.CITATION_AUDIT,
                code="MISSING_CITATION_PASSAGE",
                message="Citation audit found a citation to an unavailable passage.",
            )
        if not report_passages.issubset(approved_passages):
            return await self._failure(
                state,
                WorkflowStage.CITATION_AUDIT,
                code="REJECTED_EVIDENCE_CITED",
                message="Citation audit found a report citation to rejected evidence.",
            )
        response = await self._call(
            state,
            WorkflowStage.CITATION_AUDIT,
            messages=[
                {"role": "system", "content": CITATION_AUDIT_PROMPT},
                {
                    "role": "user",
                    "content": _json(
                        {
                            "report_sentences": _sentences(state.report_draft),
                            "cited_passages": [
                                passage_map[pid]
                                for pid in {
                                    pid
                                    for sentence in _sentences(state.report_draft)
                                    for pid in sentence.passage_ids
                                }
                                if pid in passage_map
                            ],
                        }
                    ),
                },
            ],
            output_schema=CitationAuditOutput,
            max_tokens=6000,
        )
        if isinstance(response, VerificationState):
            return response
        guarded = _guard_citation_audit(state.report_draft, passage_map, response.output)
        if guarded is None:
            return await self._failure(
                state,
                WorkflowStage.CITATION_AUDIT,
                code="INCOMPLETE_CITATION_AUDIT",
                message="Citation audit did not evaluate every cited sentence and passage.",
            )
        updated = state.complete(
            WorkflowStage.CITATION_AUDIT,
            citation_audit=guarded,
            model_calls={**state.model_calls, WorkflowStage.CITATION_AUDIT.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.CITATION_AUDIT,
            payload={
                "needs_revision": guarded.needs_revision,
                "unsupported_sentence_count": len(guarded.unsupported_sentence_refs),
            },
        )

    def extension(self, stage: WorkflowStage, implementation: ExtensionNode | None) -> ExtensionNode:
        async def run(state: VerificationState) -> VerificationState:
            if stage in state.completed_stages:
                return state
            if cancelled := await self._begin(state, stage):
                return cancelled
            if implementation is None:
                return await self._failure(
                    state,
                    stage,
                    code="WORKFLOW_EXTENSION_PENDING",
                    message=f"The {stage.value.replace('_', ' ')} stage is not installed yet.",
                )
            try:
                updated = await implementation(state)
                if not isinstance(updated, VerificationState):
                    raise TypeError("workflow extensions must return VerificationState")
                updated = VerificationState.model_validate(updated.model_dump())
            except Exception:
                return await self._failure(
                    state,
                    stage,
                    code="WORKFLOW_EXTENSION_FAILED",
                    message=f"The {stage.value.replace('_', ' ')} stage could not be completed.",
                )
            updated = updated.complete(stage)
            return await self._finish(updated, stage)

        return run


def build_workflow(services: WorkflowServices, *, planning_only: bool = False):
    """Compile the controlled graph; planning-only is the Step 8 production handoff."""
    nodes = WorkflowNodes(services)
    graph = StateGraph(VerificationState)
    graph.add_node("intake", nodes.intake)
    graph.add_node("decomposition", nodes.decomposition)
    graph.add_node("planner", nodes.planner)
    graph.add_node(
        "discovery_source_selection",
        nodes.extension(WorkflowStage.DISCOVERY, services.extensions.discovery_source_selection),
    )
    graph.add_node(
        "secure_retrieval",
        nodes.extension(WorkflowStage.RETRIEVAL, services.extensions.secure_retrieval),
    )
    graph.add_node("extraction", nodes.extension(WorkflowStage.EXTRACTION, services.extensions.extraction))
    graph.add_node(
        "passage_segmentation_embedding",
        nodes.extension(WorkflowStage.SEGMENTATION, services.extensions.passage_segmentation_embedding),
    )
    graph.add_node(
        "provenance_dependency_analysis",
        nodes.extension(WorkflowStage.PROVENANCE, services.extensions.provenance_dependency_analysis),
    )
    graph.add_node("evidence_classification", nodes.evidence_classification)
    graph.add_node(
        "deterministic_scoring",
        nodes.extension(WorkflowStage.SCORING, services.extensions.deterministic_scoring),
    )
    graph.add_node(
        "numerical_audit",
        nodes.extension(WorkflowStage.NUMERICAL_AUDIT, services.extensions.numerical_audit),
    )
    graph.add_node("synthesis", nodes.synthesis)
    graph.add_node("citation_audit", nodes.citation_audit)

    graph.add_edge(START, "intake")
    _conditional(graph, "intake", "decomposition", stop_requested)
    _conditional(graph, "decomposition", "planner", stop_requested)
    if planning_only:
        graph.add_edge("planner", END)
    else:
        _conditional(graph, "planner", "discovery_source_selection", stop_requested)
        _conditional(graph, "discovery_source_selection", "secure_retrieval", stop_requested)
        _conditional(graph, "secure_retrieval", "extraction", stop_requested)
        _conditional(graph, "extraction", "passage_segmentation_embedding", stop_requested)
        _conditional(
            graph,
            "passage_segmentation_embedding",
            "provenance_dependency_analysis",
            stop_requested,
        )
        _conditional(graph, "provenance_dependency_analysis", "evidence_classification", evidence_ready)
        _conditional(graph, "evidence_classification", "deterministic_scoring", stop_requested)
        _conditional(graph, "deterministic_scoring", "numerical_audit", stop_requested)
        _conditional(graph, "numerical_audit", "synthesis", synthesis_ready)
        _conditional(graph, "synthesis", "citation_audit", citation_audit_ready)
        graph.add_edge("citation_audit", END)
    return graph.compile()


def _conditional(
    graph: StateGraph,
    source: str,
    target: str,
    route: Callable[[VerificationState], str],
) -> None:
    graph.add_conditional_edges(source, route, {"continue": target, "stop": END})


def _stage_progress(stage: WorkflowStage, *, completed: bool) -> dict[str, object]:
    stage_number = _STAGE_NUMBERS[stage]
    return {
        "completed_steps": stage_number if completed else stage_number - 1,
        "total_steps": _TOTAL_STAGES,
    }


def _approved_passage_ids(state: VerificationState) -> set[str]:
    accessible_snapshots = {
        snapshot.snapshot_id: snapshot.source_ref
        for snapshot in state.snapshots
        if snapshot.access_status.upper() == "FETCHED"
    }
    passage_map = {passage.passage_id: passage for passage in state.passages}
    return {
        item.passage_id
        for item in state.evidence
        if not item.recommended_rejection_reasons
        and item.passage_id in passage_map
        and passage_map[item.passage_id].snapshot_id in accessible_snapshots
        and passage_map[item.passage_id].source_ref
        == accessible_snapshots[passage_map[item.passage_id].snapshot_id]
    }


def _has_claim_cycle(output: DecompositionOutput) -> bool:
    parents = {
        claim.claim_ref: claim.parent_claim_ref for claim in output.atomic_claims
    }
    for claim_ref in parents:
        seen: set[str] = set()
        current: str | None = claim_ref
        while current is not None:
            if current in seen:
                return True
            seen.add(current)
            current = parents.get(current)
    return False


def _json(value: object) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, separators=(",", ":"), default=str)


def _jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _sentences(report: SynthesisOutput):
    values = [*report.summary_sentences, *report.factual_sentences, *report.attribution_findings]
    if report.strongest_credible_contradiction is not None:
        values.append(report.strongest_credible_contradiction)
    return values


def _guard_citation_audit(
    report: SynthesisOutput,
    passage_map: dict[str, object],
    audit: CitationAuditOutput,
) -> CitationAuditOutput | None:
    sentences = {sentence.sentence_ref: sentence for sentence in _sentences(report)}
    required = {(ref, pid) for ref, sentence in sentences.items() for pid in sentence.passage_ids}
    received = {(item.sentence_ref, item.passage_id) for item in audit.sentence_audits}
    if (
        received != required
        or len(audit.sentence_audits) != len(required)
        or any(pid not in passage_map for _, pid in received)
    ):
        return None
    unsupported = sorted(
        {
            item.sentence_ref
            for item in audit.sentence_audits
            if item.entailment in {Entailment.NOT_ENTAILED, Entailment.INSUFFICIENT}
        }
    )
    partial = {item.sentence_ref for item in audit.sentence_audits if item.entailment == Entailment.PARTIAL}
    missing = sorted(ref for ref, sentence in sentences.items() if not sentence.passage_ids)
    needs_revision = bool(unsupported or partial or missing)
    return CitationAuditOutput(
        sentence_audits=[SentenceCitationAuditOutput.model_validate(item) for item in audit.sentence_audits],
        unsupported_sentence_refs=unsupported,
        missing_citation_sentence_refs=missing,
        needs_revision=needs_revision,
    )


_START_MESSAGES = {stage: f"Starting {stage.value.replace('_', ' ')}." for stage in WorkflowStage}
_COMPLETE_MESSAGES = {stage: f"Completed {stage.value.replace('_', ' ')}." for stage in WorkflowStage}


__all__ = [
    "PROMPT_VERSIONS",
    "WorkflowExtensions",
    "WorkflowNodes",
    "WorkflowServices",
    "build_workflow",
]
