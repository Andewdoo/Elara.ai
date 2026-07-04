from app.services.object_storage import get_object_storage
from app.models import Upload, User


class RecordingStorage:
    def __init__(self):
        self.objects = {}

    def put_private_object(self, *, key, body, content_type):
        self.objects[key] = (body, content_type)

    def delete_object(self, *, key):
        self.objects.pop(key, None)

    def signed_download_url(self, **_):
        raise AssertionError("uploads never issue public URLs")


def test_upload_endpoint_stores_validated_bytes_privately_and_returns_no_url(client):
    storage = RecordingStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage

    response = client.post(
        "/v1/uploads",
        files={"file": ("evidence.pdf", b"%PDF-1.7\nminimal", "application/pdf")},
    )

    assert response.status_code == 201
    assert "download_url" not in response.json()
    key = next(iter(storage.objects))
    assert key.startswith("uploads/") and key.endswith("/source.pdf")


def test_upload_endpoint_rejects_disguised_executable_without_storage_write(client):
    storage = RecordingStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage

    response = client.post(
        "/v1/uploads",
        files={"file": ("evidence.pdf", b"MZmalware", "application/pdf")},
    )

    assert response.status_code == 415
    assert storage.objects == {}


def test_validated_upload_is_owner_scoped_and_single_use(client):
    storage = RecordingStorage()
    client.app.dependency_overrides[get_object_storage] = lambda: storage
    created = client.post(
        "/v1/uploads",
        files={"file": ("evidence.txt", b"public evidence text", "text/plain")},
    )
    upload_id = created.json()["upload_id"]
    payload = {"input_type": "UPLOADED_DOCUMENT", "upload_id": upload_id}

    first = client.post("/v1/verifications", json=payload)
    second = client.post("/v1/verifications", json=payload)

    assert first.status_code == 202
    assert second.status_code == 404


def test_cross_user_upload_id_is_not_disclosed(client, session_factory):
    with session_factory() as db:
        other = User(
            auth_provider="firebase",
            auth_subject="other-upload-owner",
            email="other-upload@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(other)
        db.flush()
        upload = Upload(
            user_id=other.id,
            object_path=f"uploads/{other.id}/private/source.txt",
            original_filename="private.txt",
            content_type="text/plain",
            size_bytes=7,
            content_hash="a" * 64,
        )
        db.add(upload)
        db.commit()
        upload_id = str(upload.id)

    response = client.post(
        "/v1/verifications",
        json={"input_type": "UPLOADED_DOCUMENT", "upload_id": upload_id},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Upload not found"
