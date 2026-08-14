from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.database.session import get_db
from app.schemas.verifications import HistoryResponse
from app.services.demo_runs import list_demo_runs

router = APIRouter(prefix="/v1/demo-runs", tags=["demo"])


@router.get("", response_model=HistoryResponse)
def get_demo_runs(
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    """List the owner-designated, shared citation-audited Demo reports."""
    del authenticated
    return list_demo_runs(db)
