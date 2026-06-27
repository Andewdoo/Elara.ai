from collections.abc import Generator

from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import AuthenticatedUser, get_authenticated_session
from app.auth.firebase import get_firebase_gateway
from app.config import get_settings
from app.database.session import get_db
from app.main import create_app
from app.models import User
from app.schemas.auth import FirebasePrincipal


class SessionVerifier:
    def verify_session_cookie(self, cookie: str) -> FirebasePrincipal:
        assert cookie == "valid-session-cookie"
        return FirebasePrincipal(uid="session-uid", email="session@example.com")


def test_session_cookie_boundary_verifies_cookie_and_loads_database_user(
    session_factory: sessionmaker[Session], settings
):
    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    @app.get("/test/session-protected")
    def session_protected(authenticated: AuthenticatedUser = Depends(get_authenticated_session)):
        return {"user_id": str(authenticated.user.id)}

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_firebase_gateway] = lambda: SessionVerifier()

    with TestClient(app, base_url="https://api.example.test") as client:
        unauthorized = client.get("/test/session-protected")
        client.cookies.set(settings.firebase_session_cookie_name, "valid-session-cookie")
        authorized = client.get("/test/session-protected")

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    with session_factory() as db:
        user = db.scalar(select(User))
        assert user is not None and user.auth_subject == "session-uid"
        assert authorized.json()["user_id"] == str(user.id)
