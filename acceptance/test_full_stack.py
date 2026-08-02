from __future__ import annotations

import hashlib
import os
import time
from uuid import UUID

import httpx
from celery import Celery
from redis import Redis
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import (
    AgentEvent,
    AtomicClaim,
    Calculation,
    EvidenceItem,
    InformationCluster,
    ReportCitation,
    RunSource,
    SearchQuery,
    SourceDependency,
    SourcePassage,
    SourceSnapshot,
    VerificationRun,
)


API_BASE_URL = os.environ["API_BASE_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
BROKER_URL = os.environ["CELERY_BROKER_URL"]
RESULT_BACKEND = os.environ["CELERY_RESULT_BACKEND"]
OWNER_TOKEN = "elara-acceptance:owner:owner@example.test"
OTHER_TOKEN = "elara-acceptance:other:other@example.test"
WORKER_LIVENESS_KEY = "elara:worker:liveness"


def _headers(token: str = OWNER_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _submit(client: httpx.Client, text: str, *, research_depth: str = "QUICK") -> str:
    response = client.post(
        "/v1/verifications",
        headers=_headers(),
        json={"input_type": "CLAIM", "research_depth": research_depth, "text": text},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["events_url"] == f"/v1/verifications/{body['run_id']}/events"
    return body["run_id"]


def _wait_for_status(
    client: httpx.Client,
    run_id: str,
    expected: set[str],
    *,
    timeout: float = 45,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/verifications/{run_id}", headers=_headers())
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest["status"] in expected:
            return latest
        if latest["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
            raise AssertionError(
                f"run {run_id} reached unexpected terminal status; latest={latest}"
            )
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not reach {expected}; latest={latest}")


def _wait_for_worker(redis: Redis, *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if redis.get(WORKER_LIVENESS_KEY):
            return
        time.sleep(0.2)
    raise AssertionError("worker liveness signal was not ready")


def _counts(db: Session, run_id: UUID) -> dict[str, int]:
    claim_ids = select(AtomicClaim.id).where(AtomicClaim.run_id == run_id)
    return {
        "claims": db.scalar(select(func.count()).select_from(AtomicClaim).where(AtomicClaim.run_id == run_id)) or 0,
        "queries": db.scalar(select(func.count()).select_from(SearchQuery).where(SearchQuery.run_id == run_id)) or 0,
        "run_sources": db.scalar(select(func.count()).select_from(RunSource).where(RunSource.run_id == run_id)) or 0,
        "evidence": db.scalar(select(func.count()).select_from(EvidenceItem).where(EvidenceItem.atomic_claim_id.in_(claim_ids))) or 0,
        "calculations": db.scalar(select(func.count()).select_from(Calculation).where(Calculation.run_id == run_id)) or 0,
        "clusters": db.scalar(select(func.count()).select_from(InformationCluster).where(InformationCluster.run_id == run_id)) or 0,
        "dependencies": db.scalar(select(func.count()).select_from(SourceDependency).where(SourceDependency.run_id == run_id)) or 0,
        "citations": db.scalar(select(func.count()).select_from(ReportCitation).where(ReportCitation.run_id == run_id)) or 0,
        "events": db.scalar(select(func.count()).select_from(AgentEvent).where(AgentEvent.run_id == run_id)) or 0,
    }


def test_deterministic_full_stack_acceptance() -> None:
    engine = create_engine(DATABASE_URL)
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    celery = Celery("acceptance", broker=BROKER_URL, backend=RESULT_BACKEND)
    _wait_for_worker(redis)

    with httpx.Client(base_url=API_BASE_URL, timeout=15, trust_env=False) as browser:
        session = browser.post("/v1/auth/session", headers=_headers())
        assert session.status_code == 200, session.text
        assert "HttpOnly" in session.headers["set-cookie"]
        assert "Secure" in session.headers["set-cookie"]
        session_cookie = session.cookies.get("elara_session")
        assert session_cookie and OWNER_TOKEN.removeprefix("elara-acceptance:") in session_cookie

        run_id = _submit(browser, "Company X doubled net income in Q1 2026.")
        token_in_url = browser.get(
            f"/v1/verifications/{run_id}/events?token=forbidden",
            headers={"Cookie": f"elara_session={session_cookie}"},
        )
        assert token_in_url.status_code == 400

        terminal = _wait_for_status(browser, run_id, {"COMPLETED"})
        assert terminal["completed_at"] is not None

        for depth in ("STANDARD", "DEEP"):
            depth_run_id = _submit(
                browser,
                "Company X doubled net income in Q1 2026.",
                research_depth=depth,
            )
            depth_terminal = _wait_for_status(browser, depth_run_id, {"COMPLETED"})
            assert depth_terminal["completed_at"] is not None
            with Session(engine) as db:
                depth_queries = db.scalars(
                    select(SearchQuery).where(SearchQuery.run_id == UUID(depth_run_id))
                ).all()
                assert depth_queries
                assert all(row.policy_version == "adaptive-search-v1" for row in depth_queries)
                assert all(
                    row.execution_status in {"executed", "cache_hit", "not_needed"}
                    for row in depth_queries
                )

        # A fresh client is the browser-refresh boundary: all server state reloads.
        with httpx.Client(base_url=API_BASE_URL, timeout=15, trust_env=False) as refreshed:
            report = refreshed.get(f"/v1/verifications/{run_id}/report", headers=_headers())
            sources = refreshed.get(f"/v1/verifications/{run_id}/sources", headers=_headers())
            graph = refreshed.get(f"/v1/verifications/{run_id}/source-graph", headers=_headers())
        assert report.status_code == sources.status_code == graph.status_code == 200
        report_body = report.json()
        source_body = sources.json()
        graph_body = graph.json()
        assert report_body["report_sentences"] and all(
            row["audit_status"] == "passed" for row in report_body["report_sentences"]
        )
        assert report_body["calculations"]
        assert report_body["model_versions"]["intake"]["model"] == "deepseek-acceptance-double"
        assert source_body["sources"] and all(row["snapshot_id"] for row in source_body["sources"])
        assert any(row["passages"] for row in source_body["sources"])
        assert graph_body["nodes"] and graph_body["edges"]

        with Session(engine) as db:
            durable_run = db.get(VerificationRun, UUID(run_id))
            assert durable_run is not None and durable_run.status.value == "COMPLETED"
            assert durable_run.workflow_version == "step-20-acceptance"
            assert db.scalar(select(func.count()).select_from(SourceSnapshot)) >= 2
            assert db.scalar(select(func.count()).select_from(SourcePassage)) >= 2
            before_redelivery = _counts(db, UUID(run_id))
            assert all(before_redelivery[key] > 0 for key in before_redelivery)

        export = browser.post(
            f"/v1/verifications/{run_id}/exports",
            headers=_headers(),
            json={"format": "JSON"},
        )
        assert export.status_code == 201, export.text
        export_id = export.json()["export_id"]
        signed = browser.get(
            f"/v1/verifications/{run_id}/exports/{export_id}", headers=_headers()
        )
        assert signed.status_code == 200
        signed_body = signed.json()
        assert signed_body["download_url"].startswith("http://object-storage:9000/")
        downloaded = httpx.get(signed_body["download_url"], timeout=15, trust_env=False)
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == signed_body["content_hash"]

        for path in (
            f"/v1/verifications/{run_id}",
            f"/v1/verifications/{run_id}/report",
            f"/v1/verifications/{run_id}/sources",
            f"/v1/verifications/{run_id}/source-graph",
            f"/v1/verifications/{run_id}/exports/{export_id}",
        ):
            denied = browser.get(path, headers=_headers(OTHER_TOKEN))
            assert denied.status_code == 404, (path, denied.text)

        # Redis is transient: erase it, then reconnect SSE and recover terminal truth from PostgreSQL.
        redis.flushall()
        replay = browser.get(
            f"/v1/verifications/{run_id}/events",
            headers={
                "Cookie": f"elara_session={session_cookie}",
                "Last-Event-ID": "0-0",
            },
        )
        assert replay.status_code == 200
        assert '"stage":"COMPLETED"' in replay.text

        celery.send_task(
            "verification.verify_run",
            args=[run_id],
            queue="verification.quick",
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and redis.xlen(f"elara:run:{run_id}:events") == 0:
            time.sleep(0.2)
        assert redis.xlen(f"elara:run:{run_id}:events") == before_redelivery["events"]
        with Session(engine) as db:
            assert _counts(db, UUID(run_id)) == before_redelivery

        provider_run = _submit(browser, "[provider-failure] deterministic provider failure")
        provider_terminal = _wait_for_status(browser, provider_run, {"FAILED"}, timeout=60)
        assert provider_terminal["failure_code"] == "PROVIDER_UNAVAILABLE"

        cancellation_run = _submit(browser, "[cancellation] cancel this controlled run")
        cancelled = browser.post(
            f"/v1/verifications/{cancellation_run}/cancel", headers=_headers()
        )
        assert cancelled.status_code == 200
        cancellation_terminal = _wait_for_status(
            browser, cancellation_run, {"CANCELLED"}, timeout=30
        )
        assert cancellation_terminal["status"] == "CANCELLED"

        rejected_run = _submit(browser, "[citation-rejection] reject unsupported citation")
        rejected_terminal = _wait_for_status(browser, rejected_run, {"FAILED"}, timeout=45)
        assert rejected_terminal["failure_code"] == "CITATION_REVISION_EXHAUSTED"
        rejected_report = browser.get(
            f"/v1/verifications/{rejected_run}/report", headers=_headers()
        )
        assert rejected_report.status_code == 409
