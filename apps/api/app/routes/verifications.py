from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.config import Settings, get_settings
from app.database.session import get_db
from app.schemas.verifications import VerificationCreateRequest, VerificationCreateResponse
from app.services.verifications import (
    ActiveRunLimitExceededError,
    ResearchDepthNotAllowedError,
    create_queued_verification,
)

router = APIRouter(prefix="/v1/verifications", tags=["verifications"])


@router.post("", response_model=VerificationCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_verification(
    request: VerificationCreateRequest,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> VerificationCreateResponse:
    try:
        run = create_queued_verification(db, owner=authenticated.user, request=request, settings=settings)
    except ResearchDepthNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ActiveRunLimitExceededError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return VerificationCreateResponse(
        run_id=run.id,
        status=run.status,
        events_url=f"/v1/verifications/{run.id}/events",
    )
