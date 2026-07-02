"""Authorized report source projection with exact stored passages and citation audits."""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReportCitation, RunSource, Source, SourcePassage, SourceSnapshot
from app.schemas.verifications import (
    ReportCitationResponse,
    SourcePassageResponse,
    SourceResponse,
    SourcesResponse,
)


def build_sources(db: Session, *, run_id: UUID) -> SourcesResponse:
    rows = db.execute(
        select(RunSource, Source, SourceSnapshot)
        .join(Source, Source.id == RunSource.source_id)
        .outerjoin(SourceSnapshot, SourceSnapshot.id == RunSource.snapshot_id)
        .where(RunSource.run_id == run_id)
        .order_by(RunSource.selected_rank.asc().nullslast(), Source.id)
    ).all()
    snapshot_ids = [snapshot.id for _, _, snapshot in rows if snapshot is not None]
    passages = (
        db.scalars(
            select(SourcePassage)
            .where(SourcePassage.snapshot_id.in_(snapshot_ids))
            .order_by(SourcePassage.paragraph_index.asc().nullslast(), SourcePassage.id)
        ).all()
        if snapshot_ids
        else []
    )
    passage_ids = [passage.id for passage in passages]
    citations = (
        db.scalars(
            select(ReportCitation)
            .where(ReportCitation.run_id == run_id, ReportCitation.passage_id.in_(passage_ids))
            .order_by(ReportCitation.created_at, ReportCitation.id)
        ).all()
        if passage_ids
        else []
    )
    citations_by_passage = defaultdict(list)
    for citation in citations:
        citations_by_passage[citation.passage_id].append(_citation(citation))
    passages_by_snapshot = defaultdict(list)
    for passage in passages:
        passages_by_snapshot[passage.snapshot_id].append(
            SourcePassageResponse(
                id=passage.id,
                text=passage.text,
                heading_path=passage.heading_path,
                page_or_position=passage.page_or_position,
                paragraph_index=passage.paragraph_index,
                speaker=passage.speaker,
                table_ref=passage.table_ref,
                extraction_certainty=float(passage.extraction_certainty),
                metadata=passage.passage_metadata,
                citations=citations_by_passage[passage.id],
            )
        )
    return SourcesResponse(
        sources=[
            SourceResponse(
                id=source.id,
                canonical_url=source.canonical_url,
                domain=source.domain,
                title=source.title,
                author=source.author,
                publisher=source.publisher,
                source_type=source.source_type.value,
                content_type=source.content_type,
                role=run_source.role,
                retrieval_reason=run_source.retrieval_reason,
                inaccessible_reason=run_source.inaccessible_reason,
                snapshot_id=snapshot.id if snapshot else None,
                snapshot_version=snapshot.version_number if snapshot else None,
                access_status=(
                    snapshot.access_status.value
                    if snapshot
                    else "INACCESSIBLE" if run_source.inaccessible_reason else "PENDING"
                ),
                retrieved_at=snapshot.retrieved_at if snapshot else None,
                published_at=snapshot.published_at if snapshot else None,
                content_hash=snapshot.content_hash if snapshot else None,
                parser_name=snapshot.parser_name if snapshot else None,
                parser_version=snapshot.parser_version if snapshot else None,
                correction_status=snapshot.correction_status if snapshot else None,
                snapshot_metadata=snapshot.snapshot_metadata if snapshot else {},
                failure_reason=snapshot.failure_reason if snapshot else None,
                passages=passages_by_snapshot[snapshot.id] if snapshot else [],
            )
            for run_source, source, snapshot in rows
        ]
    )


def _citation(citation: ReportCitation) -> ReportCitationResponse:
    return ReportCitationResponse(
        id=citation.id,
        report_section=citation.report_section,
        sentence_text=citation.sentence_text,
        passage_id=citation.passage_id,
        audit_status=citation.audit_status,
        audit_note=citation.audit_note,
    )


__all__ = ["build_sources"]
