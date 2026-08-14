from datetime import UTC, datetime

import pytest

from app.auth.dependencies import get_authenticated_bearer
from app.models import InputType, ResearchDepth, RunStatus, User, VerificationRun
from app.services.demo_runs import DEMO_VISIBILITY
from app.services.verifications import RunNotFoundError, get_authorized_run


def _completed_run(owner: User, *, visibility: str = "private") -> VerificationRun:
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    return VerificationRun(
        user_id=owner.id,
        input_type=InputType.CLAIM,
        research_depth=ResearchDepth.STANDARD,
        status=RunStatus.COMPLETED,
        submitted_text="A completed demo claim",
        normalized_target={},
        workflow_version="demo-test",
        title="Designated Demo report",
        verdict="Supported",
        evidence_reviewed_at=now,
        completed_at=now,
        visibility=visibility,
    )


def test_demo_endpoint_is_public_and_returns_only_designated_citation_audited_reports(
    client, session_factory, owner
):
    with session_factory() as db:
        demo = _completed_run(owner, visibility=DEMO_VISIBILITY)
        private = _completed_run(owner)
        private.title = "Private completed report"
        db.add_all([demo, private])
        db.commit()
        demo_id = demo.id

    client.app.dependency_overrides.pop(get_authenticated_bearer)
    response = client.get("/v1/demo-runs")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["run_id"] for item in response.json()["items"]] == [str(demo_id)]
    assert client.get(f"/v1/demo-runs/{demo_id}").status_code == 200
    assert client.get(f"/v1/verifications/{demo_id}").status_code == 401


def test_designated_demo_reports_are_readable_by_every_account_but_not_exportable(
    session_factory, owner
):
    with session_factory() as db:
        viewer = User(
            auth_provider="firebase",
            auth_subject="firebase-demo-viewer",
            email="demo-viewer@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        demo = _completed_run(owner, visibility=DEMO_VISIBILITY)
        private = _completed_run(owner)
        incomplete_demo = _completed_run(owner, visibility=DEMO_VISIBILITY)
        incomplete_demo.status = RunStatus.RESEARCHING
        incomplete_demo.evidence_reviewed_at = None
        db.add_all([viewer, demo, private, incomplete_demo])
        db.commit()

        assert get_authorized_run(db, viewer_id=viewer.id, run_id=demo.id).id == demo.id
        assert get_authorized_run(
            db, viewer_id=viewer.id, run_id=demo.id, required_scope="sources"
        ).id == demo.id
        with pytest.raises(RunNotFoundError):
            get_authorized_run(db, viewer_id=viewer.id, run_id=demo.id, required_scope="exports")
        with pytest.raises(RunNotFoundError):
            get_authorized_run(db, viewer_id=viewer.id, run_id=private.id)
        with pytest.raises(RunNotFoundError):
            get_authorized_run(db, viewer_id=viewer.id, run_id=incomplete_demo.id)
