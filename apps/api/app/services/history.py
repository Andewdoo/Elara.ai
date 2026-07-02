from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ResearchDepth, RunStatus, VerificationRun
from app.schemas.verifications import HistoryItemResponse, HistoryResponse


def list_history(
    db: Session,
    *,
    owner_id: UUID,
    query: str | None,
    status: RunStatus | None,
    research_depth: ResearchDepth | None,
    verdict: str | None,
    saved_only: bool,
    created_from: datetime | None,
    created_to: datetime | None,
    sort: str,
    page: int,
    page_size: int,
) -> HistoryResponse:
    filters = [
        VerificationRun.user_id == owner_id,
        VerificationRun.deleted_at.is_(None),
    ]
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(
            or_(
                VerificationRun.title.ilike(pattern),
                VerificationRun.submitted_text.ilike(pattern),
                VerificationRun.submitted_url.ilike(pattern),
                VerificationRun.verdict.ilike(pattern),
            )
        )
    if status is not None:
        filters.append(VerificationRun.status == status)
    if research_depth is not None:
        filters.append(VerificationRun.research_depth == research_depth)
    if verdict:
        filters.append(VerificationRun.verdict.ilike(f"%{verdict.strip()}%"))
    if saved_only:
        filters.append(VerificationRun.saved_at.is_not(None))
    if created_from is not None:
        filters.append(VerificationRun.created_at >= created_from)
    if created_to is not None:
        filters.append(VerificationRun.created_at <= created_to)

    order = {
        "oldest": VerificationRun.created_at.asc(),
        "confidence": VerificationRun.verdict_confidence.desc().nullslast(),
    }.get(sort, VerificationRun.created_at.desc())
    total = int(
        db.scalar(select(func.count()).select_from(VerificationRun).where(*filters)) or 0
    )
    rows = db.scalars(
        select(VerificationRun)
        .where(*filters)
        .order_by(order, VerificationRun.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return HistoryResponse(
        items=[
            HistoryItemResponse(
                run_id=row.id,
                status=row.status,
                input_type=row.input_type,
                research_depth=row.research_depth,
                title=row.title,
                submitted_text_preview=(row.submitted_text or "")[:240] or None,
                verdict=row.verdict,
                verdict_confidence=row.verdict_confidence,
                evidence_reviewed_at=row.evidence_reviewed_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
                saved_at=row.saved_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )
