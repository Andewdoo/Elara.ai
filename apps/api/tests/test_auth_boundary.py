from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.firebase import get_firebase_gateway
from app.config import get_settings
from app.database.session import get_db
from app.main import create_app
from app.models import User, VerificationRun
from app.schemas.auth import FirebasePrincipal


class TokenVerifier:
    def verify_id_token(self, token: str) -> FirebasePrincipal:
        assert token == "valid-firebase-token"
        return FirebasePrincipal(uid="verified-uid", email="verified@example.com")


def test_bearer_boundary_verifies_identity_and_persists_owner(
    session_factory: sessionmaker[Session], settings
):
    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_firebase_gateway] = lambda: TokenVerifier()

    with TestClient(app) as client:
        unauthenticated = client.post(
            "/v1/verifications",
            json={"input_type": "CLAIM", "text": "A claim"},
        )
        authenticated = client.post(
            "/v1/verifications",
            headers={"Authorization": "Bearer valid-firebase-token"},
            json={"input_type": "CLAIM", "text": "A claim"},
        )

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 202
    with session_factory() as db:
        user = db.scalar(select(User))
        run = db.scalar(select(VerificationRun))
        assert user is not None and user.auth_subject == "verified-uid"
        assert run is not None and run.user_id == user.id
        assert db.scalar(select(func.count()).select_from(User)) == 1
