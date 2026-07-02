import hashlib
import json
from datetime import UTC, datetime

import boto3
import pytest
from sqlalchemy import select

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.config import Settings
from app.models import Export, InputType, ResearchDepth, RunStatus, User, UserFeedback, VerificationRun
from app.schemas.auth import FirebasePrincipal
from app.services.object_storage import get_object_storage
from app.services.report_actions import create_json_export
import app.services.object_storage as object_storage_module


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.deleted: list[str] = []

    def put_private_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def signed_download_url(
        self, *, key: str, filename: str, content_type: str, expires_in: int
    ) -> str:
        assert key in self.objects
        assert expires_in == 300
        return f"https://objects.example.test/signed/{key}?expires={expires_in}"

    def delete_object(self, *, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)


def create_run(session_factory, owner, *, status=RunStatus.COMPLETED, title="A saved report"):
    now = datetime(2026, 7, 2, 12, tzinfo=UTC)
    with session_factory() as db:
        run = VerificationRun(
            user_id=owner.id,
            input_type=InputType.CLAIM,
            research_depth=ResearchDepth.STANDARD,
            status=status,
            submitted_text="A searchable claim",
            normalized_target={},
            workflow_version="step-15-test",
            title=title,
            verdict="Supported" if status == RunStatus.COMPLETED else None,
            verdict_confidence=88 if status == RunStatus.COMPLETED else None,
            evidence_reviewed_at=now if status == RunStatus.COMPLETED else None,
            completed_at=now if status == RunStatus.COMPLETED else None,
        )
        db.add(run)
        db.commit()
        return run.id


def test_history_filters_save_and_unsave(client, session_factory, owner):
    run_id = create_run(session_factory, owner)

    saved = client.post(f"/v1/verifications/{run_id}/save")
    assert saved.status_code == 200
    assert saved.json()["saved_at"] is not None
    assert client.post(f"/v1/verifications/{run_id}/save").json()["saved_at"] == saved.json()["saved_at"]

    history = client.get("/v1/history", params={"query": "searchable", "saved_only": True})
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["run_id"] == str(run_id)

    unsaved = client.delete(f"/v1/verifications/{run_id}/save")
    assert unsaved.status_code == 200
    assert unsaved.json()["saved_at"] is None
    assert client.get("/v1/history", params={"saved_only": True}).json()["total"] == 0
    invalid_range = client.get(
        "/v1/history",
        params={
            "created_from": "2026-07-03T00:00:00Z",
            "created_to": "2026-07-02T00:00:00Z",
        },
    )
    assert invalid_range.status_code == 422


def test_feedback_categories_are_typed_and_persist_submitter(client, session_factory, owner):
    run_id = create_run(session_factory, owner)
    response = client.post(
        f"/v1/verifications/{run_id}/feedback",
        json={
            "category": "BROKEN_CITATION",
            "message": "The linked passage no longer opens.",
            "source_url": "https://example.com/source",
        },
    )
    assert response.status_code == 201
    assert response.json()["category"] == "BROKEN_CITATION"
    with session_factory() as db:
        row = db.scalar(select(UserFeedback))
        assert row is not None and row.user_id == owner.id
        assert row.category == "BROKEN_CITATION"
    invalid = client.post(
        f"/v1/verifications/{run_id}/feedback",
        json={"category": "GENERAL", "message": "Not a supported category"},
    )
    assert invalid.status_code == 422


def test_json_export_is_private_hashed_and_signed_only_on_authorized_read(
    client, session_factory, owner
):
    run_id = create_run(session_factory, owner)
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage

    created = client.post(
        f"/v1/verifications/{run_id}/exports", json={"format": "JSON"}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["download_url"] is None
    assert len(storage.objects) == 1
    key, (payload, content_type) = next(iter(storage.objects.items()))
    assert not key.startswith("http")
    assert content_type == "application/json"
    assert json.loads(payload)["run_id"] == str(run_id)
    assert body["content_hash"] == hashlib.sha256(payload).hexdigest()

    download = client.get(
        f"/v1/verifications/{run_id}/exports/{body['export_id']}"
    )
    assert download.status_code == 200
    assert download.json()["download_url"].startswith("https://objects.example.test/signed/")
    assert download.json()["expires_at"] is not None
    with session_factory() as db:
        row = db.scalar(select(Export))
        assert row is not None and row.object_path == key


def test_delete_hides_report_and_removes_export_objects(client, session_factory, owner):
    run_id = create_run(session_factory, owner)
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    created = client.post(
        f"/v1/verifications/{run_id}/exports", json={"format": "JSON"}
    ).json()

    deleted = client.delete(f"/v1/verifications/{run_id}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    assert len(storage.deleted) == 1
    assert client.get(f"/v1/verifications/{run_id}").status_code == 404
    assert client.get("/v1/history").json()["total"] == 0
    assert client.get(
        f"/v1/verifications/{run_id}/exports/{created['export_id']}"
    ).status_code == 404
    with session_factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run is not None and run.deleted_at is not None
        assert db.scalar(select(Export)) is None


def test_active_report_cannot_be_saved_exported_or_deleted(client, session_factory, owner):
    run_id = create_run(session_factory, owner, status=RunStatus.RESEARCHING)
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    assert client.post(f"/v1/verifications/{run_id}/save").status_code == 409
    assert client.post(
        f"/v1/verifications/{run_id}/exports", json={"format": "JSON"}
    ).status_code == 409
    assert client.delete(f"/v1/verifications/{run_id}").status_code == 409


def test_new_routes_preserve_owner_and_share_authorization(client, session_factory, owner):
    run_id = create_run(session_factory, owner)
    storage = FakeStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    export_id = client.post(
        f"/v1/verifications/{run_id}/exports", json={"format": "JSON"}
    ).json()["export_id"]
    with session_factory() as db:
        other = User(
            auth_provider="firebase",
            auth_subject="firebase-other",
            email="other@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        db.expunge(other)

    client.app.dependency_overrides[get_authenticated_bearer] = lambda: AuthenticatedUser(
        principal=FirebasePrincipal(
            uid=other.auth_subject,
            email=other.email,
            auth_time=1_900_000_000,
            issued_at=1_900_000_000,
        ),
        user=other,
        id_token="other-token",
    )
    feedback = {"category": "APPEAL", "message": "Please review this assessment."}
    assert client.get("/v1/history").json()["total"] == 0
    assert client.post(f"/v1/verifications/{run_id}/feedback", json=feedback).status_code == 404
    assert client.get(f"/v1/verifications/{run_id}/exports/{export_id}").status_code == 404
    assert client.post(f"/v1/verifications/{run_id}/save").status_code == 404
    assert client.post(
        f"/v1/verifications/{run_id}/exports", json={"format": "JSON"}
    ).status_code == 404
    assert client.delete(f"/v1/verifications/{run_id}").status_code == 404

    with session_factory() as db:
        run = db.get(VerificationRun, run_id)
        assert run is not None
        run.visibility = "public"
        db.commit()
    shared_run = client.get(f"/v1/verifications/{run_id}")
    assert shared_run.status_code == 200 and shared_run.json()["is_owner"] is False
    assert client.post(f"/v1/verifications/{run_id}/feedback", json=feedback).status_code == 201
    assert client.get(f"/v1/verifications/{run_id}/exports/{export_id}").status_code == 200
    assert client.post(f"/v1/verifications/{run_id}/save").status_code == 404
    assert client.delete(f"/v1/verifications/{run_id}").status_code == 404


def test_failed_database_commit_removes_uploaded_export(session_factory, owner, monkeypatch):
    run_id = create_run(session_factory, owner)
    storage = FakeStorage()
    with session_factory() as db:
        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            create_json_export(db, owner_id=owner.id, run_id=run_id, storage=storage)
    assert storage.objects == {}
    assert len(storage.deleted) == 1


def test_s3_uses_internal_endpoint_for_storage_and_public_endpoint_for_signing(monkeypatch):
    endpoints: list[str] = []

    class FakeClient:
        def generate_presigned_url(self, *_args, **_kwargs):
            return "https://downloads.example.test/signed"

    def fake_client(_service: str, *, endpoint_url: str, **_kwargs):
        endpoints.append(endpoint_url)
        return FakeClient()

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(
        object_storage_module,
        "get_settings",
        lambda: Settings(
            environment="test",
            database_url="sqlite+pysqlite://",
            cors_allowed_origins=["http://localhost:3000"],
            s3_endpoint_url="http://object-storage:9000",
            s3_public_endpoint_url="https://downloads.example.test",
            s3_access_key_id="key",
            s3_secret_access_key="secret",
        ),
    )
    storage = object_storage_module.S3ObjectStorage()
    assert endpoints == ["http://object-storage:9000", "https://downloads.example.test"]
    assert storage.signed_download_url(
        key="exports/a.json",
        filename="report.json",
        content_type="application/json",
        expires_in=300,
    ) == "https://downloads.example.test/signed"
