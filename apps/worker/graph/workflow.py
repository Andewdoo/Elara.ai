"""LangGraph nodes and assembly for Elara's controlled verification workflow."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from agents.citation_audit import PROMPT_VERSION as CITATION_AUDIT_PROMPT_VERSION
from agents.citation_audit import SYSTEM_PROMPT as CITATION_AUDIT_PROMPT
from agents.decomposition import PROMPT_VERSION as DECOMPOSITION_PROMPT_VERSION
from agents.decomposition import SYSTEM_PROMPT as DECOMPOSITION_PROMPT
from agents.decomposition import DecompositionNormalizationError, normalize_decomposition
from agents.deepseek_client import DeepSeekError, StructuredResponse
from agents.evidence_classification import (
    PROMPT_VERSION as EVIDENCE_PROMPT_VERSION,
    SYSTEM_PROMPT as EVIDENCE_PROMPT,
    build_classification_tasks,
)
from agents.intake import PROMPT_VERSION as INTAKE_PROMPT_VERSION
from agents.intake import SYSTEM_PROMPT as INTAKE_PROMPT
from agents.planning import PROMPT_VERSION as PLANNER_PROMPT_VERSION
from agents.planning import SYSTEM_PROMPT as PLANNER_PROMPT
from agents.planning import (
    UnknownPlanningDraftClaimRefError,
    build_planner_payload,
    exact_quote_for_state,
    fact_checkable_claim_refs,
    normalize_research_plan,
    requires_attribution_check,
    search_budget_for_state,
    search_policy_for_state,
)
from agents.schemas import (
    CitationAuditOutput,
    DecompositionDraftOutput,
    Entailment,
    EvidenceIntent,
    EvidenceClassificationOutput,
    EvidenceClassificationItemOutput,
    EvidenceStance,
    InputKind,
    IntakeClassificationOutput,
    PlanningDraftOutput,
    PlanningOutput,
    SearchQueryOutput,
    SentenceCitationAuditOutput,
    SynthesisDraftOutput,
    SynthesisOutput,
    iter_auditable_sentences,
)
from agents.synthesis import PROMPT_VERSION as SYNTHESIS_PROMPT_VERSION
from agents.synthesis import SYSTEM_PROMPT as SYNTHESIS_PROMPT
from agents.validation import (
    AgentContractViolation,
    summarize_violation_codes,
    validate_research_plan,
)
from graph.state import (
    CalculationRecord,
    RecoverableError,
    SearchQueryExecutionRecord,
    VerificationState,
    WorkflowStage,
)
from graph.transitions import (
    citation_audit_ready,
    evidence_ready,
    stop_requested,
    synthesis_ready,
)
from research.extension_errors import WorkflowExtensionError
from research.search_policy import (
    CoverageBudgetExceededError,
    query_state_key,
    select_initial_queries,
)


PROMPT_VERSIONS = {
    WorkflowStage.INTAKE: INTAKE_PROMPT_VERSION,
    WorkflowStage.DECOMPOSITION: DECOMPOSITION_PROMPT_VERSION,
    WorkflowStage.PLANNER: PLANNER_PROMPT_VERSION,
    WorkflowStage.EVIDENCE_CLASSIFICATION: EVIDENCE_PROMPT_VERSION,
    WorkflowStage.SYNTHESIS: SYNTHESIS_PROMPT_VERSION,
    WorkflowStage.CITATION_REVISION: SYNTHESIS_PROMPT_VERSION,
    WorkflowStage.CITATION_AUDIT: CITATION_AUDIT_PROMPT_VERSION,
}


PARTIAL_CITATION_EVIDENCE_SUPPORT_PENALTY = 5
PARTIAL_CITATION_CONFIDENCE_PENALTY = 7
MAX_PARTIAL_CITATION_EVIDENCE_SUPPORT_PENALTY = 20
MAX_PARTIAL_CITATION_CONFIDENCE_PENALTY = 25
SYNTHESIS_CITATION_REPAIR_LIMIT = 1

_STAGE_NUMBERS: dict[WorkflowStage, int] = {
    stage: index
    for index, stage in enumerate(
        [item for item in WorkflowStage if item != WorkflowStage.CITATION_REVISION],
        start=1,
    )
}
_STAGE_NUMBERS[WorkflowStage.CITATION_REVISION] = _STAGE_NUMBERS[WorkflowStage.CITATION_AUDIT]
_TOTAL_STAGES = len(WorkflowStage) - 1


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
        repair_invalid_response: bool = True,
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
    citation_revision_limit: int = 2

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
        # A malformed provider response is recoverable once: DeepSeek receives the
        # original trusted context plus a fixed schema-only repair instruction. This
        # is bounded to one extra call and never exposes malformed model content.
        repair_invalid_response: bool = True,
    ) -> StructuredResponse | VerificationState:
        try:
            return await self.services.model.generate_structured(
                messages=messages,
                output_schema=output_schema,
                prompt_version=PROMPT_VERSIONS[stage],
                model_role="chat",
                temperature=0.0,
                max_tokens=max_tokens,
                repair_invalid_response=repair_invalid_response,
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
                {
                    "role": "user",
                    "content": _json(
                        {
                            "submitted_input": self.services.submitted_input,
                            "expected_input_kind": (
                                self.services.expected_input_kind.value
                                if self.services.expected_input_kind is not None
                                else None
                            ),
                        }
                    ),
                },
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
                details={
                    "expected_input_kind": self.services.expected_input_kind.value,
                    "returned_input_kind": output.input_kind.value,
                },
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
        if output.input_kind == InputKind.ARTICLE_TITLE:
            submitted_title = " ".join(self.services.submitted_input.split())
            if not submitted_title or len(submitted_title) > 500:
                return await self._failure(
                    state,
                    WorkflowStage.INTAKE,
                    code="INVALID_ARTICLE_TITLE",
                    message="The submitted article title could not be normalized safely.",
                )
            output = output.model_copy(update={"normalized_text": submitted_title})
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
            output_schema=DecompositionDraftOutput,
            max_tokens=5000,
        )
        if isinstance(response, VerificationState):
            return response
        claim_limit = {"QUICK": 12, "STANDARD": 25, "DEEP": 50}[state.research_depth.value]
        try:
            output = normalize_decomposition(
                response.output,
                normalized_text=state.normalized_input.normalized_text,
                claim_limit=claim_limit,
            )
        except DecompositionNormalizationError as error:
            return await self._failure(
                state,
                WorkflowStage.DECOMPOSITION,
                code=error.code,
                message=error.public_message,
            )
        updated = state.complete(
            WorkflowStage.DECOMPOSITION,
            claims=output.atomic_claims,
            claim_ambiguities=output.claim_ambiguities,
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
        try:
            policy = search_policy_for_state(state)
            budget = search_budget_for_state(state)
        except CoverageBudgetExceededError as exc:
            return await self._failure(
                state,
                WorkflowStage.PLANNER,
                code="SEARCH_COVERAGE_BUDGET_EXCEEDED",
                message="The submitted target requires more search coverage than this research depth supports.",
                details={
                    "mandatory_floor": exc.mandatory_floor,
                    "supported_ceiling": exc.supported_ceiling,
                },
            )
        allowed_claim_refs = [claim.claim_ref for claim in state.claims]
        planner_messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": _json(build_planner_payload(state))},
        ]
        response = await self._call(
            state,
            WorkflowStage.PLANNER,
            messages=planner_messages,
            output_schema=PlanningDraftOutput,
            max_tokens=6000,
            repair_invalid_response=True,
        )
        if isinstance(response, VerificationState):
            return response
        output, violations = _validate_planner_output(
            state,
            response.output,
            allowed_claim_refs=allowed_claim_refs,
        )
        semantic_repair_attempt_count = 0
        if violations:
            semantic_repair_attempt_count = 1
            await self.services.progress.publish(
                run_id=state.run_id,
                stage=WorkflowStage.PLANNER,
                event_type="workflow.planner.semantic_repair_started",
                message="Research planning is being regenerated to satisfy deterministic checks.",
                payload={
                    **_stage_progress(WorkflowStage.PLANNER, completed=False),
                    "primary_violation": violations[0].code,
                    "violation_count": len(violations),
                    "semantic_repair_attempt_count": semantic_repair_attempt_count,
                },
            )
            repaired_response = await self._call(
                state,
                WorkflowStage.PLANNER,
                messages=[
                    {"role": "system", "content": PLANNER_PROMPT},
                    {
                        "role": "system",
                        "content": _planner_repair_instruction(
                            violations,
                            allowed_claim_refs=allowed_claim_refs,
                        ),
                    },
                    {"role": "user", "content": _json(build_planner_payload(state))},
                ],
                output_schema=PlanningDraftOutput,
                max_tokens=6000,
                repair_invalid_response=response.metadata.attempt_count == 1,
            )
            if isinstance(repaired_response, VerificationState):
                return repaired_response
            response = repaired_response
            output, violations = _validate_planner_output(
                state,
                response.output,
                allowed_claim_refs=allowed_claim_refs,
            )
        if violations or output is None:
            return await self._failure(
                state,
                WorkflowStage.PLANNER,
                code="AGENT_CONTRACT_REPAIR_EXHAUSTED",
                message="Research planning returned an invalid plan contract.",
                details={
                    "primary_violation": violations[0].code,
                    "violation_count": len(violations),
                    "repair_attempted": True,
                    "semantic_validation_attempt_count": 2,
                    "semantic_repair_attempt_count": semantic_repair_attempt_count,
                    "violation_summary": summarize_violation_codes(violations),
                },
            )
        exact_quote = exact_quote_for_state(state)
        phase_one_queries, reserve_queries = select_initial_queries(
            output.queries,
            output.objectives,
            fact_checkable_claim_refs=fact_checkable_claim_refs(state),
            attribution_required=requires_attribution_check(state, exact_quote),
            exact_quote=exact_quote,
            policy=policy,
            budget=budget,
        )
        phase_one_keys = {query_state_key(query) for query in phase_one_queries}
        reserve_keys = {query_state_key(query) for query in reserve_queries}
        query_executions = [
            SearchQueryExecutionRecord(
                query_key=query_state_key(query),
                discovery_phase=(
                    "phase_one" if query_state_key(query) in phase_one_keys else "phase_two"
                ),
                execution_status=(
                    "planned" if query_state_key(query) in phase_one_keys | reserve_keys else "not_needed"
                ),
                skip_reason=(
                    None if query_state_key(query) in phase_one_keys | reserve_keys else "outside_effective_budget"
                ),
            )
            for query in output.queries
        ]
        updated = state.complete(
            WorkflowStage.PLANNER,
            objectives=output.objectives,
            queries=output.queries,
            primary_source_targets=output.primary_source_targets,
            known_evidence_gaps=output.known_evidence_gaps,
            search_query_executions=query_executions,
            search_mandatory_floor=budget.mandatory_floor,
            search_effective_budget=budget.effective_total_budget,
            model_calls={**state.model_calls, WorkflowStage.PLANNER.value: response.metadata},
        )
        return await self._finish(
            updated,
            WorkflowStage.PLANNER,
            payload={
                "objective_count": len(output.objectives),
                "query_count": len(output.queries),
                "semantic_validation_attempt_count": semantic_repair_attempt_count + 1,
                "semantic_repair_attempt_count": semantic_repair_attempt_count,
            },
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
        tasks = build_classification_tasks(
            state.claims,
            state.passages,
            research_depth=state.research_depth.value,
        )
        if not tasks:
            return await self._failure(
                state,
                WorkflowStage.EVIDENCE_CLASSIFICATION,
                code="CLASSIFICATION_COVERAGE_MISMATCH",
                message="Evidence classification did not produce required bounded tasks.",
                details={"expected_task_count": 0, "returned_task_count": 0},
            )
        response = await self._call(
            state,
            WorkflowStage.EVIDENCE_CLASSIFICATION,
            messages=[
                {"role": "system", "content": EVIDENCE_PROMPT},
                {"role": "user", "content": _json({"tasks": [task.prompt_payload() for task in tasks]})},
            ],
            output_schema=EvidenceClassificationOutput,
            max_tokens=8000,
        )
        if isinstance(response, VerificationState):
            return response
        output = response.output
        tasks_by_ref = {task.task_ref: task for task in tasks}
        expected_task_refs = set(tasks_by_ref)
        returned_task_refs = [item.task_ref for item in output.classifications]
        returned_task_ref_set = set(returned_task_refs)
        duplicate_count = len(returned_task_refs) - len(returned_task_ref_set)
        missing_count = len(expected_task_refs - returned_task_ref_set)
        unknown_count = len(returned_task_ref_set - expected_task_refs)
        if duplicate_count or missing_count or unknown_count:
            return await self._failure(
                state,
                WorkflowStage.EVIDENCE_CLASSIFICATION,
                code="CLASSIFICATION_COVERAGE_MISMATCH",
                message="Evidence classification did not return exactly one result for every required task.",
                details={
                    "expected_task_count": len(expected_task_refs),
                    "returned_task_count": len(returned_task_refs),
                    "missing_task_count": missing_count,
                    "duplicate_task_count": duplicate_count,
                    "unknown_task_count": unknown_count,
                    "extra_task_count": unknown_count,
                },
            )
        passages = {passage.passage_id: passage for passage in state.passages}
        guarded_classifications = []
        for result in output.classifications:
            task = tasks_by_ref[result.task_ref]
            item = EvidenceClassificationItemOutput.model_validate(
                {
                    **result.model_dump(exclude={"task_ref"}),
                    "claim_ref": task.claim_ref,
                    "passage_id": task.passage_id,
                }
            )
            passage = passages[task.passage_id]
            quality = item.quality.model_copy(
                update={"extraction_certainty": float(passage.extraction_certainty)}
            )
            deterministic_reasons = []
            if item.quality.relevance < 0.50:
                deterministic_reasons.append("relevance_below_threshold")
            if passage is not None and passage.extraction_certainty < 0.65:
                deterministic_reasons.append("extraction_certainty_below_threshold")
            # A claim asserting an event or an entity can be directly contradicted
            # by evidence that the asserted thing has not happened or does not
            # exist. Requiring a literal entity match in that narrow case would
            # discard the strongest contradiction (for example, evidence that no
            # universal cure has been found). The semantic classifier must still
            # provide explicit contradictory text, and every other deterministic
            # relevance, extraction, time, and quote gate still applies.
            explicit_contradiction = bool(
                item.explicit_contradiction and item.explicit_contradiction.strip()
            )
            grounded_contradiction = (
                item.stance
                in {EvidenceStance.STRONGLY_CONTRADICTS, EvidenceStance.PARTIALLY_CONTRADICTS}
                and explicit_contradiction
            )
            if not item.entity_match and not grounded_contradiction:
                deterministic_reasons.append("entity_mismatch")
            if not item.time_period_match:
                deterministic_reasons.append("time_period_mismatch")
            if item.quotation_or_number_located is False:
                deterministic_reasons.append("quotation_or_number_not_located")
            if (
                not deterministic_reasons
                and item.stance == EvidenceStance.NEUTRAL
                and not item.explicit_support
                and not item.explicit_contradiction
            ):
                deterministic_reasons.append("no_evidence_for_exact_claim")
            guarded_classifications.append(
                item.model_copy(
                    update={
                        "quality": quality,
                        # Free-form model recommendations are advisory only. Final
                        # evidence inclusion is controlled by deterministic gates.
                        "recommended_rejection_reasons": deterministic_reasons,
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
        approved_evidence = [
            item for item in state.evidence if item.passage_id in approved_passage_ids
        ]
        synthesis_input = {
            "submitted_target": (
                state.normalized_input.normalized_text
                if state.normalized_input is not None
                else None
            ),
            "claims": state.claims,
            "approved_evidence": approved_evidence,
            "approved_passages": passages,
            "source_snapshots": state.snapshots,
            "scores": state.scores,
            "methodology_version": state.methodology_version,
        }
        response = await self._call(
            state,
            WorkflowStage.SYNTHESIS,
            messages=[
                {"role": "system", "content": SYNTHESIS_PROMPT},
                {"role": "user", "content": _json(synthesis_input)},
            ],
            output_schema=SynthesisDraftOutput,
            max_tokens=8000,
        )
        if isinstance(response, VerificationState):
            return response
        cited = _cited_passage_ids(response.output)
        if not cited.issubset(approved_passage_ids):
            await self.services.progress.publish(
                run_id=state.run_id,
                stage=WorkflowStage.SYNTHESIS,
                event_type="workflow.synthesis.citation_repair",
                message="Regenerating the report with approved citations.",
                payload={
                    **_stage_progress(WorkflowStage.SYNTHESIS, completed=False),
                    "citation_repair_attempt": SYNTHESIS_CITATION_REPAIR_LIMIT,
                },
            )
            response = await self._call(
                state,
                WorkflowStage.SYNTHESIS,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{SYNTHESIS_PROMPT}\n"
                            "Regenerate the report now. A prior draft cited an ID outside the "
                            "approved evidence. Use only these exact approved passage IDs: "
                            f"{', '.join(sorted(approved_passage_ids))}."
                        ),
                    },
                    {"role": "user", "content": _json(synthesis_input)},
                ],
                output_schema=SynthesisDraftOutput,
                max_tokens=8000,
            )
            if isinstance(response, VerificationState):
                return response
            cited = _cited_passage_ids(response.output)
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
        model_versions = {
            stage: metadata.model for stage, metadata in state.model_calls.items()
        }
        model_versions[WorkflowStage.SYNTHESIS.value] = response.metadata.model
        prompt_versions = {
            stage: metadata.prompt_version for stage, metadata in state.model_calls.items()
        }
        prompt_versions[WorkflowStage.SYNTHESIS.value] = response.metadata.prompt_version
        guarded_report = _build_deterministic_report(
            state,
            response.output,
            approved_passage_ids=approved_passage_ids,
            evidence_reviewed_at=reviewed_at,
            evidence_timestamp=timestamp,
            model_versions=model_versions,
            prompt_versions=prompt_versions,
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
            payload={"sentence_count": sum(1 for _ in iter_auditable_sentences(guarded_report))},
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
        auditable_sentences = list(iter_auditable_sentences(state.report_draft))
        sentence_refs = [sentence.sentence_ref for _, sentence in auditable_sentences]
        if len(sentence_refs) != len(set(sentence_refs)):
            return await self._failure(
                state,
                WorkflowStage.CITATION_AUDIT,
                code="DUPLICATE_REPORT_SENTENCE_REF",
                message="Citation audit requires unique report sentence references.",
            )
        passage_map = {p.passage_id: p for p in state.passages}
        approved_passages = _approved_passage_ids(state)
        report_passages = {
            passage_id
            for _, sentence in auditable_sentences
            for passage_id in sentence.passage_ids
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
                            "report_sentences": [
                                sentence
                                for _, sentence in auditable_sentences
                            ],
                            "cited_passages": [
                                passage_map[pid]
                                for pid in {
                                    pid
                                    for _, sentence in auditable_sentences
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
        if not guarded.needs_revision:
            updated = _apply_partial_citation_penalty(updated)
        return await self._finish(
            updated,
            WorkflowStage.CITATION_AUDIT,
            payload={
                "needs_revision": guarded.needs_revision,
                "unsupported_sentence_count": len(guarded.unsupported_sentence_refs),
            },
        )

    async def citation_revision(self, state: VerificationState) -> VerificationState:
        if cancelled := await self._begin(state, WorkflowStage.CITATION_REVISION):
            return cancelled
        if state.report_draft is None or state.citation_audit is None:
            return await self._failure(
                state,
                WorkflowStage.CITATION_REVISION,
                code="CITATION_REVISION_INPUT_REQUIRED",
                message="Citation revision requires an audited report draft.",
            )
        if not state.citation_audit.needs_revision:
            return state
        if state.citation_revision_count >= self.services.citation_revision_limit:
            return await self._failure(
                state,
                WorkflowStage.CITATION_REVISION,
                code="CITATION_REVISION_EXHAUSTED",
                message="The report could not be fully supported after bounded citation revision.",
            )

        approved_ids = _approved_passage_ids(state)
        approved_passages = [
            passage for passage in state.passages if passage.passage_id in approved_ids
        ]
        response = await self._call(
            state,
            WorkflowStage.CITATION_REVISION,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{SYNTHESIS_PROMPT}\nRevise the supplied report after citation audit. "
                        "Remove unsupported factual sentences. Rewrite partially supported sentences "
                        "only when the approved passages fully support the narrower wording. Use only "
                        "the supplied approved passage IDs and preserve no unsupported factual detail."
                    ),
                },
                {
                    "role": "user",
                    "content": _json(
                        {
                            "report": state.report_draft,
                            "citation_audit": state.citation_audit,
                            "approved_passages": approved_passages,
                            "deterministic_scores": state.scores,
                        }
                    ),
                },
            ],
            output_schema=SynthesisDraftOutput,
            max_tokens=8000,
        )
        if isinstance(response, VerificationState):
            return response
        cited = {
            passage_id
            for _, sentence in iter_auditable_sentences(response.output)
            for passage_id in sentence.passage_ids
        }
        if not cited.issubset(approved_ids):
            return await self._failure(
                state,
                WorkflowStage.CITATION_REVISION,
                code="UNAPPROVED_REVISION_CITATION",
                message="The revised report cited evidence that was not approved.",
            )
        has_contradiction = any(
            item.passage_id in approved_ids and "contradicts" in item.stance.value
            for item in state.evidence
        )
        if has_contradiction and response.output.strongest_credible_contradiction is None:
            return await self._failure(
                state,
                WorkflowStage.CITATION_REVISION,
                code="CONTRADICTION_OMITTED",
                message="The revised report omitted the strongest credible contradiction.",
            )
        prior = state.report_draft
        revised = SynthesisOutput(
            title=prior.title,
            summary_sentences=response.output.summary_sentences,
            factual_sentences=response.output.factual_sentences,
            strongest_credible_contradiction=response.output.strongest_credible_contradiction,
            attribution_findings=response.output.attribution_findings,
            limitations=prior.limitations,
            inaccessible_source_notes=prior.inaccessible_source_notes,
            evidence_gaps=prior.evidence_gaps,
            evidence_reviewed_at=prior.evidence_reviewed_at,
            evidence_timestamp=prior.evidence_timestamp,
            methodology_version=prior.methodology_version,
            workflow_version=prior.workflow_version,
            model_versions={
                **prior.model_versions,
                WorkflowStage.CITATION_REVISION.value: response.metadata.model,
            },
            prompt_versions={
                **prior.prompt_versions,
                WorkflowStage.CITATION_REVISION.value: response.metadata.prompt_version,
            },
            parser_versions=prior.parser_versions,
        )
        completed = [
            stage for stage in state.completed_stages if stage != WorkflowStage.CITATION_AUDIT
        ]
        updated = state.model_copy(
            update={
                "report_draft": revised,
                "citation_audit": None,
                "citation_revision_count": state.citation_revision_count + 1,
                "completed_stages": completed,
                "model_calls": {
                    **state.model_calls,
                    WorkflowStage.CITATION_REVISION.value: response.metadata,
                },
            }
        ).complete(WorkflowStage.CITATION_REVISION)
        finished_revision = await self._finish(
            updated,
            WorkflowStage.CITATION_REVISION,
            payload={"revision_count": updated.citation_revision_count},
        )
        # Re-audit the in-memory revised draft before returning control to the graph.
        # LangGraph state merging must not retain the prior audit merely because the
        # revision clears an optional field, or the old needs_revision decision would
        # consume the remaining revision budget without assessing the new wording.
        return await self.citation_audit(finished_revision)

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
            except WorkflowExtensionError as exc:
                return await self._failure(
                    exc.state if isinstance(exc.state, VerificationState) else state,
                    stage,
                    code=exc.code,
                    message=exc.public_message,
                    retryable=exc.retryable,
                    details=exc.details,
                )
            if len(updated.recoverable_errors) > len(state.recoverable_errors):
                error = updated.recoverable_errors[-1]
                await self.services.state_writer.save(stage=stage, state=updated)
                await self.services.progress.publish(
                    run_id=state.run_id,
                    stage=stage,
                    event_type=f"workflow.{stage.value}.recoverable_failure",
                    message=error.public_message,
                    payload={
                        **_stage_progress(stage, completed=False),
                        "code": error.code,
                        "retryable": error.retryable,
                        "details": error.details,
                    },
                )
                return updated
            updated = updated.complete(stage)
            return await self._finish(updated, stage)

        return run


def build_workflow(
    services: WorkflowServices,
    *,
    planning_only: bool = False,
    retrieval_only: bool = False,
    segmentation_only: bool = False,
    provenance_only: bool = False,
    scoring_only: bool = False,
    numerical_only: bool = False,
):
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
    graph.add_node("citation_revision", nodes.citation_revision)

    graph.add_edge(START, "intake")
    _conditional(graph, "intake", "decomposition", stop_requested)
    _conditional(graph, "decomposition", "planner", stop_requested)
    if planning_only:
        graph.add_edge("planner", END)
    else:
        _conditional(graph, "planner", "discovery_source_selection", stop_requested)
        _conditional(graph, "discovery_source_selection", "secure_retrieval", stop_requested)
        _conditional(graph, "secure_retrieval", "extraction", stop_requested)
        if retrieval_only:
            graph.add_edge("extraction", END)
            return graph.compile()
        _conditional(graph, "extraction", "passage_segmentation_embedding", stop_requested)
        if segmentation_only:
            graph.add_edge("passage_segmentation_embedding", END)
            return graph.compile()
        _conditional(
            graph,
            "passage_segmentation_embedding",
            "provenance_dependency_analysis",
            stop_requested,
        )
        if provenance_only:
            graph.add_edge("provenance_dependency_analysis", END)
            return graph.compile()
        _conditional(graph, "provenance_dependency_analysis", "evidence_classification", evidence_ready)
        _conditional(graph, "evidence_classification", "deterministic_scoring", stop_requested)
        if scoring_only:
            graph.add_edge("deterministic_scoring", END)
            return graph.compile()
        _conditional(graph, "deterministic_scoring", "numerical_audit", stop_requested)
        if numerical_only:
            graph.add_edge("numerical_audit", END)
            return graph.compile()
        _conditional(graph, "numerical_audit", "synthesis", synthesis_ready)
        _conditional(graph, "synthesis", "citation_audit", citation_audit_ready)
        graph.add_conditional_edges(
            "citation_audit",
            _citation_revision_route,
            {"complete": END, "revise": "citation_revision", "stop": END},
        )
        _conditional(graph, "citation_revision", "citation_audit", stop_requested)
    return graph.compile()


def _conditional(
    graph: StateGraph,
    source: str,
    target: str,
    route: Callable[[VerificationState], str],
) -> None:
    graph.add_conditional_edges(source, route, {"continue": target, "stop": END})


def _citation_revision_route(state: VerificationState) -> str:
    if state.cancelled or state.recoverable_errors or state.citation_audit is None:
        return "stop"
    return "revise" if state.citation_audit.needs_revision else "complete"


def _stage_progress(stage: WorkflowStage, *, completed: bool) -> dict[str, object]:
    stage_number = _STAGE_NUMBERS[stage]
    return {
        "completed_steps": stage_number if completed else stage_number - 1,
        "total_steps": _TOTAL_STAGES,
    }


def _cited_passage_ids(report: SynthesisDraftOutput) -> set[str]:
    return {
        passage_id
        for _, sentence in iter_auditable_sentences(report)
        for passage_id in sentence.passage_ids
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


def _validate_planner_output(
    state: VerificationState,
    draft: PlanningDraftOutput,
    *,
    allowed_claim_refs: Sequence[str],
) -> tuple[PlanningOutput | None, tuple[AgentContractViolation, ...]]:
    """Normalize and validate one planner response without retaining its contents."""
    try:
        output = normalize_research_plan(draft, allowed_claim_refs=allowed_claim_refs)
    except UnknownPlanningDraftClaimRefError:
        return None, (
            AgentContractViolation(
                code="PLAN_UNKNOWN_CLAIM_REF",
                field="objectives.claim_ref",
            ),
        )
    output = _with_article_title_query(state, output)
    return output, validate_research_plan(state, output)


def _with_article_title_query(state: VerificationState, output: PlanningOutput) -> PlanningOutput:
    """Ensure a title submission starts discovery with an exact Brave query."""
    normalized_input = state.normalized_input
    if normalized_input is None or normalized_input.input_kind != InputKind.ARTICLE_TITLE:
        return output
    article_title = normalized_input.normalized_text
    canonical_title = " ".join(article_title.casefold().split())
    if any(
        query.intent == EvidenceIntent.PRIMARY
        and " ".join(query.query.casefold().split()) == canonical_title
        for query in output.queries
    ):
        return output
    primary_objective = next(
        (objective for objective in output.objectives if objective.intent == EvidenceIntent.PRIMARY),
        None,
    )
    if primary_objective is None:
        return output
    title_query = SearchQueryOutput(
        query=article_title,
        objective_ref=primary_objective.objective_ref,
        intent=EvidenceIntent.PRIMARY,
        priority=1.0,
    )
    return output.model_copy(update={"queries": [title_query, *output.queries]})


def _planner_repair_instruction(
    violations: Sequence[AgentContractViolation],
    *,
    allowed_claim_refs: Sequence[str],
) -> str:
    """Build a bounded corrective instruction without model content or error values."""
    violation_codes = ",".join(sorted({violation.code for violation in violations}))
    allowed_refs = ",".join(sorted(allowed_claim_refs))
    return (
        "Regenerate the complete planning response. Correct the deterministic contract "
        f"violation codes: {violation_codes}. Use only these allowed claim references: "
        f"{allowed_refs}. Return only one JSON object."
    )


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


def _sanitize_inaccessible_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    sanitized = " ".join("".join(char for char in reason if char.isprintable()).split())
    return sanitized[:300] or None


def _deterministic_inaccessible_source_notes(state: VerificationState) -> list[str]:
    notes: list[str] = []
    for snapshot in sorted(
        state.snapshots,
        key=lambda item: (item.source_ref, item.snapshot_id),
    ):
        if snapshot.access_status.upper() == "FETCHED":
            continue
        note = f"Source {snapshot.source_ref} was {snapshot.access_status.lower()}"
        if reason := _sanitize_inaccessible_reason(snapshot.failure_reason):
            note += f": {reason}"
        if note not in notes:
            notes.append(note)
    return notes


def _deterministic_evidence_gaps(
    state: VerificationState, approved_passage_ids: set[str]
) -> list[str]:
    supported_claim_refs = {
        item.claim_ref for item in state.evidence if item.passage_id in approved_passage_ids
    }
    return [
        f"No approved evidence was available for claim {claim.claim_ref}."
        for claim in state.claims
        if claim.claim_ref not in supported_claim_refs
    ]


def _deterministic_ambiguity_limitations(state: VerificationState) -> list[str]:
    """Describe only typed, non-blocking ambiguity decisions without model text."""
    non_blocking_claim_refs = {
        calculation.claim_ref
        for calculation in state.calculations
        if calculation.formula_name == "ambiguity_gate"
        and calculation.claim_ref is not None
        and calculation.result.get("non_blocking") is True
    }
    supporting_labels = {"Supported", "Mostly supported", "Leaning supported"}
    labels_by_claim = {
        score.claim_ref: score.final_label for score in state.claim_scores
    }
    ambiguity_counts = {
        claim_ref: sum(
            ambiguity.claim_ref == claim_ref
            for ambiguity in state.claim_ambiguities
        )
        for claim_ref in non_blocking_claim_refs
    }
    return [
        (
            f"Claim {claim_ref} is supported with an unresolved interpretation "
            f"({ambiguity_counts[claim_ref]} claim-local limitation(s)); accepted "
            "evidence was adequate and unopposed."
        )
        for claim_ref in sorted(non_blocking_claim_refs)
        if labels_by_claim.get(claim_ref) in supporting_labels
        and ambiguity_counts.get(claim_ref, 0) > 0
    ]


_GENERIC_REPORT_TITLES = {
    "assessment",
    "evidence assessment",
    "report",
    "untitled verification",
    "verification",
    "verification report",
}
_REPORT_TITLE_MAX_LENGTH = 96


def _normalize_report_title(value: str | None) -> str | None:
    if not value:
        return None
    title = re.sub(r"[\x00-\x1f\x7f]", "", " ".join(value.split())).strip()
    if not title or title.casefold() in _GENERIC_REPORT_TITLES:
        return None
    if len(title) <= _REPORT_TITLE_MAX_LENGTH:
        return title
    boundary = title.rfind(" ", 0, _REPORT_TITLE_MAX_LENGTH - 1)
    return f"{title[:boundary if boundary > 24 else _REPORT_TITLE_MAX_LENGTH - 1].rstrip(' ,;:—-')}…"


def _report_title(state: VerificationState, suggested_title: str | None) -> str:
    """Prefer the constrained model paraphrase, with a deterministic target fallback."""

    if title := _normalize_report_title(suggested_title):
        return title
    submitted_target = (
        state.normalized_input.normalized_text
        if state.normalized_input is not None
        else None
    )
    first_claim = state.claims[0].text if state.claims else None
    return _normalize_report_title(submitted_target) or _normalize_report_title(first_claim) or "Verification report"


def _build_deterministic_report(
    state: VerificationState,
    draft: SynthesisDraftOutput,
    *,
    approved_passage_ids: set[str],
    evidence_reviewed_at: datetime,
    evidence_timestamp: str,
    model_versions: dict[str, str],
    prompt_versions: dict[str, str],
) -> SynthesisOutput:
    return SynthesisOutput(
        title=_report_title(state, draft.report_title),
        summary_sentences=draft.summary_sentences,
        factual_sentences=draft.factual_sentences,
        strongest_credible_contradiction=draft.strongest_credible_contradiction,
        attribution_findings=draft.attribution_findings,
        limitations=[
            "This assessment is limited to the submitted target and approved evidence reviewed at the stated timestamp.",
            *_deterministic_ambiguity_limitations(state),
        ],
        inaccessible_source_notes=_deterministic_inaccessible_source_notes(state),
        evidence_gaps=_deterministic_evidence_gaps(state, approved_passage_ids),
        evidence_reviewed_at=evidence_reviewed_at,
        evidence_timestamp=evidence_timestamp,
        methodology_version=state.methodology_version,
        workflow_version=state.workflow_version,
        model_versions=model_versions,
        prompt_versions=prompt_versions,
        parser_versions=state.parser_versions,
    )


def _guard_citation_audit(
    report: SynthesisOutput,
    passage_map: Mapping[str, object],
    audit: CitationAuditOutput,
) -> CitationAuditOutput | None:
    auditable_sentences = list(iter_auditable_sentences(report))
    sentences = {sentence.sentence_ref: sentence for _, sentence in auditable_sentences}
    if len(sentences) != len(auditable_sentences):
        return None
    required = {
        (sentence.sentence_ref, passage_id)
        for _, sentence in auditable_sentences
        for passage_id in sentence.passage_ids
    }
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
    missing = sorted(ref for ref, sentence in sentences.items() if not sentence.passage_ids)
    needs_revision = bool(unsupported or missing)
    return CitationAuditOutput(
        sentence_audits=[SentenceCitationAuditOutput.model_validate(item) for item in audit.sentence_audits],
        unsupported_sentence_refs=unsupported,
        missing_citation_sentence_refs=missing,
        needs_revision=needs_revision,
    )


def _apply_partial_citation_penalty(state: VerificationState) -> VerificationState:
    """Keep narrowly supported prose publishable with deterministic capped deductions."""
    if state.scores is None or state.citation_audit is None:
        return state
    partial_sentence_refs = {
        item.sentence_ref
        for item in state.citation_audit.sentence_audits
        if item.entailment == Entailment.PARTIAL
    }
    if not partial_sentence_refs:
        return state
    count = len(partial_sentence_refs)
    evidence_support_penalty = min(
        MAX_PARTIAL_CITATION_EVIDENCE_SUPPORT_PENALTY,
        PARTIAL_CITATION_EVIDENCE_SUPPORT_PENALTY * count,
    )
    confidence_penalty = min(
        MAX_PARTIAL_CITATION_CONFIDENCE_PENALTY,
        PARTIAL_CITATION_CONFIDENCE_PENALTY * count,
    )

    def penalize(value: int | None, penalty: int) -> int | None:
        return max(0, value - penalty) if value is not None else None

    scores = state.scores.model_copy(
        update={
            "evidence_support": penalize(
                state.scores.evidence_support, evidence_support_penalty
            ),
            "verdict_confidence": penalize(
                state.scores.verdict_confidence, confidence_penalty
            ),
        }
    )
    calculations: list[CalculationRecord] = []
    for calculation in state.calculations:
        inputs = dict(calculation.inputs)
        result = dict(calculation.result)
        if calculation.claim_ref is None and calculation.formula_name == "article_factual_accuracy":
            result["score"] = str(
                penalize(
                    int(float(result["score"])), evidence_support_penalty
                )
            ) if result.get("score") is not None else None
            inputs["citation_partial_support_penalty"] = str(evidence_support_penalty)
        elif calculation.claim_ref is None and calculation.formula_name == "verdict_confidence":
            result["score"] = str(scores.verdict_confidence) if scores.verdict_confidence is not None else None
            penalties = inputs.get("penalties")
            inputs["penalties"] = {
                **(penalties if isinstance(penalties, dict) else {}),
                "citation_partial_support": str(confidence_penalty),
            }
        calculations.append(calculation.model_copy(update={"inputs": inputs, "result": result}))
    calculations.append(
        CalculationRecord(
            calculation_ref=str(uuid4()),
            formula_name="citation_partial_support_penalty",
            formula_text="reported score = clamp(original score - partial citation penalty, 0, 100)",
            inputs={
                "partial_sentence_count": count,
                "evidence_support_penalty": str(evidence_support_penalty),
                "verdict_confidence_penalty": str(confidence_penalty),
            },
            result={
                "evidence_support": scores.evidence_support,
                "verdict_confidence": scores.verdict_confidence,
            },
            units="score_0_100",
            decimal_context={"precision": 28, "rounding": "ROUND_HALF_UP"},
            audit_status="passed",
        )
    )
    return state.model_copy(update={"scores": scores, "calculations": calculations})


_START_MESSAGES = {stage: f"Starting {stage.value.replace('_', ' ')}." for stage in WorkflowStage}
_COMPLETE_MESSAGES = {stage: f"Completed {stage.value.replace('_', ' ')}." for stage in WorkflowStage}


__all__ = [
    "PROMPT_VERSIONS",
    "WorkflowExtensions",
    "WorkflowNodes",
    "WorkflowServices",
    "build_workflow",
]
