"""Durable, authorized report projection with transparent calculation audits."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AtomicClaim,
    Calculation,
    EvidenceItem,
    MethodologyVersion,
    ReportCitation,
    RunSource,
    Source,
    SourcePassage,
    VerificationRun,
)
from app.schemas.verifications import (
    AtomicClaimResponse,
    CalculationResponse,
    EvidenceItemResponse,
    ReportCitationResponse,
    ReportResponse,
    ScoreBundle,
)
from app.services.source_graph import build_source_graph


def build_report(db: Session, *, run: VerificationRun) -> ReportResponse:
    claims = db.scalars(
        select(AtomicClaim)
        .where(AtomicClaim.run_id == run.id)
        .order_by(AtomicClaim.importance_weight.desc(), AtomicClaim.created_at, AtomicClaim.id)
    ).all()
    claim_ids = [claim.id for claim in claims]
    evidence_rows = (
        db.execute(
            select(EvidenceItem, SourcePassage, Source)
            .join(SourcePassage, SourcePassage.id == EvidenceItem.passage_id)
            .join(Source, Source.id == SourcePassage.source_id)
            .where(EvidenceItem.atomic_claim_id.in_(claim_ids))
            .order_by(EvidenceItem.created_at, EvidenceItem.id)
        ).all()
        if claim_ids
        else []
    )
    calculations = db.scalars(
        select(Calculation)
        .where(Calculation.run_id == run.id)
        .order_by(Calculation.created_at, Calculation.id)
    ).all()
    methodology = (
        db.get(MethodologyVersion, run.methodology_version_id)
        if run.methodology_version_id is not None
        else None
    )
    inaccessible = db.scalars(
        select(RunSource.inaccessible_reason).where(
            RunSource.run_id == run.id, RunSource.inaccessible_reason.is_not(None)
        )
    ).all()
    failed_audits = [row for row in calculations if row.audit_status != "passed"]
    global_score_records = {
        row.formula_name: row
        for row in calculations
        if row.atomic_claim_id is None and row.result.get("score") is not None
    }

    def calculated_score(name: str) -> int | None:
        row = global_score_records.get(name)
        return (
            int(Decimal(str(row.result["score"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            if row is not None
            else None
        )
    report_citations = db.scalars(
        select(ReportCitation)
        .where(ReportCitation.run_id == run.id)
        .order_by(ReportCitation.created_at, ReportCitation.id)
    ).all()
    limitations = [f"Inaccessible source: {reason}" for reason in inaccessible]
    if failed_audits:
        limitations.append(
            f"{len(failed_audits)} calculation audit(s) require review; inspect audit_status and inputs."
        )
    return ReportResponse(
        run_id=run.id,
        verdict=run.verdict,
        scores=ScoreBundle(
            evidence_support=run.evidence_support,
            attribution_support=calculated_score("attribution_support"),
            quote_fidelity=calculated_score("quote_fidelity"),
            verdict_confidence=run.verdict_confidence,
            source_independence=run.source_independence,
            context_completeness=run.context_completeness,
        ),
        atomic_claims=[
            AtomicClaimResponse(
                id=row.id,
                claim_text=row.claim_text,
                importance_weight=row.importance_weight,
                claim_type=row.claim_type,
                final_label=row.final_label,
                support_score=row.support_score,
                confidence_score=row.confidence_score,
                context_completeness=row.context_completeness,
                ambiguities=[str(value) for value in row.ambiguities],
                gaps=[str(value) for value in row.gates.get("gaps", [])],
            )
            for row in claims
        ],
        evidence=[
            EvidenceItemResponse(
                id=item.id,
                atomic_claim_id=item.atomic_claim_id,
                passage_id=item.passage_id,
                stance=item.stance.value,
                base_quality=float(item.base_quality),
                dependency_multiplier=float(item.dependency_multiplier),
                adjusted_weight=float(item.adjusted_weight),
                citation_status=item.citation_status,
                passage_text=passage.text,
                source_title=source.title,
                source_url=source.canonical_url,
                page_or_position=passage.page_or_position,
            )
            for item, passage, source in evidence_rows
        ],
        source_graph=build_source_graph(db, run_id=run.id),
        calculations=[
            CalculationResponse(
                id=row.id,
                atomic_claim_id=row.atomic_claim_id,
                formula_name=row.formula_name,
                formula_text=row.formula_text,
                inputs=row.inputs,
                result=row.result,
                units=row.units,
                decimal_context=row.decimal_context,
                audit_status=row.audit_status,
            )
            for row in calculations
        ],
        methodology_version=methodology.version if methodology else "not-recorded",
        workflow_version=run.workflow_version,
        model_versions=run.model_versions,
        prompt_versions=run.prompt_versions,
        parser_versions=run.parser_versions,
        report_sentences=[
            ReportCitationResponse(
                id=row.id,
                report_section=row.report_section,
                sentence_text=row.sentence_text,
                passage_id=row.passage_id,
                audit_status=row.audit_status,
                audit_note=row.audit_note,
            )
            for row in report_citations
        ],
        evidence_reviewed_at=run.evidence_reviewed_at or run.updated_at,
        limitations=limitations,
    )


__all__ = ["build_report"]
