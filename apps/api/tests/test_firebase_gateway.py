from datetime import timedelta
from time import time

import pytest

from app.auth import firebase as firebase_module
from app.auth.firebase import FirebaseAuthenticationError, FirebaseGateway
from app.config import Settings
from app.schemas.auth import FirebasePrincipal


def test_gateway_uses_admin_sdk_for_id_and_revocation_checked_session_tokens(monkeypatch):
    gateway = FirebaseGateway(Settings(environment="test"))
    app_marker = object()
    monkeypatch.setattr(gateway, "_app", lambda: app_marker)

    def verify_id_token(token, *, app):
        assert token == "id-token"
        assert app is app_marker
        return {"uid": "firebase-uid", "email": "person@example.com", "iat": 1_900_000_000}

    def verify_session_cookie(cookie, *, app, check_revoked):
        assert cookie == "session-cookie"
        assert app is app_marker
        assert check_revoked is True
        return {"sub": "firebase-uid", "email": "person@example.com"}

    monkeypatch.setattr(firebase_module.auth, "verify_id_token", verify_id_token)
    monkeypatch.setattr(firebase_module.auth, "verify_session_cookie", verify_session_cookie)

    assert gateway.verify_id_token("id-token").uid == "firebase-uid"
    assert gateway.verify_session_cookie("session-cookie").uid == "firebase-uid"


def test_gateway_creates_short_lived_session_from_recent_authentication(monkeypatch):
    settings = Settings(environment="test", firebase_session_ttl_minutes=30)
    gateway = FirebaseGateway(settings)
    app_marker = object()
    monkeypatch.setattr(gateway, "_app", lambda: app_marker)

    def create_session_cookie(token, *, expires_in, app):
        assert token == "fresh-token"
        assert expires_in == timedelta(minutes=30)
        assert app is app_marker
        return "signed-cookie"

    monkeypatch.setattr(firebase_module.auth, "create_session_cookie", create_session_cookie)
    principal = FirebasePrincipal(uid="firebase-uid", auth_time=int(time()), issued_at=int(time()))

    assert gateway.create_session_cookie("fresh-token", principal) == "signed-cookie"


def test_gateway_rejects_stale_id_token_for_session_exchange(monkeypatch):
    settings = Settings(environment="test", firebase_fresh_token_max_age_seconds=60)
    gateway = FirebaseGateway(settings)
    monkeypatch.setattr(gateway, "_app", lambda: object())
    principal = FirebasePrincipal(uid="firebase-uid", issued_at=int(time()) - 61)

    with pytest.raises(FirebaseAuthenticationError, match="fresh Firebase ID token"):
        gateway.create_session_cookie("stale-token", principal)
