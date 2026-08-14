from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.verifications import (
    HistoryResponse,
    ReportResponse,
    SourceGraphResponse,
    SourcesResponse,
    VerificationRunResponse,
)
from app.services.demo_runs import DemoRunNotFoundError, demo_run_response, get_demo_run, list_demo_runs
from app.services.reports import build_report
from app.services.source_graph import build_source_graph
from app.services.sources import build_sources

router = APIRouter(prefix="/v1/demo-runs", tags=["demo"])


@router.get("", response_model=HistoryResponse)
def get_demo_runs(
    db: Session = Depends(get_db),
) -> HistoryResponse:
    """List the owner-designated, shared citation-audited Demo reports."""
    return list_demo_runs(db)


def _demo_or_404(db: Session, run_id: UUID):
    try:
        return get_demo_run(db, run_id=run_id)
    except DemoRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{run_id}", response_model=VerificationRunResponse)
def get_demo_run_record(run_id: UUID, db: Session = Depends(get_db)) -> VerificationRunResponse:
    return demo_run_response(_demo_or_404(db, run_id))


@router.get("/{run_id}/report", response_model=ReportResponse)
def get_demo_report(run_id: UUID, db: Session = Depends(get_db)) -> ReportResponse:
    return build_report(db, run=_demo_or_404(db, run_id))


@router.get("/{run_id}/sources", response_model=SourcesResponse)
def get_demo_sources(run_id: UUID, db: Session = Depends(get_db)) -> SourcesResponse:
    return build_sources(db, run_id=_demo_or_404(db, run_id).id)


@router.get("/{run_id}/source-graph", response_model=SourceGraphResponse)
def get_demo_source_graph(run_id: UUID, db: Session = Depends(get_db)) -> SourceGraphResponse:
    return build_source_graph(db, run_id=_demo_or_404(db, run_id).id)
