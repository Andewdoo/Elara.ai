from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.database.session import get_db
from app.models import ResearchDepth, RunStatus
from app.schemas.verifications import HistoryResponse
from app.services.history import list_history

router = APIRouter(prefix="/v1/history", tags=["history"])


@router.get("", response_model=HistoryResponse)
def get_history(
    query: str | None = Query(default=None, max_length=200),
    status: RunStatus | None = None,
    research_depth: ResearchDepth | None = None,
    verdict: str | None = Query(default=None, max_length=100),
    saved_only: bool = False,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = Query(
        default="date_desc",
        pattern="^(date_desc|date_asc|confidence_desc|confidence_asc|recent|oldest|confidence)$",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="created_from must not be later than created_to",
        )
    return list_history(
        db,
        owner_id=authenticated.user.id,
        query=query,
        status=status,
        research_depth=research_depth,
        verdict=verdict,
        saved_only=saved_only,
        created_from=created_from,
        created_to=created_to,
        sort=sort,
        page=page,
        page_size=page_size,
    )
