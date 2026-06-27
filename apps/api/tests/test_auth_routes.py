from fastapi.testclient import TestClient

from app.auth.firebase import get_firebase_gateway


class FakeFirebaseGateway:
    session_ttl_seconds = 3600

    def create_session_cookie(self, id_token, principal):
        assert id_token == "fresh-id-token"
        assert principal.uid == "firebase-owner"
        return "signed-session-cookie"


def test_session_exchange_sets_secure_http_only_cookie(client: TestClient):
    client.app.dependency_overrides[get_firebase_gateway] = lambda: FakeFirebaseGateway()
    response = client.post("/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {"expires_in_seconds": 3600}
    cookie = response.headers["set-cookie"].lower()
    assert "elara_session=signed-session-cookie" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie


def test_session_delete_clears_cookie(client: TestClient):
    response = client.delete("/v1/auth/session")
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "elara_session=" in cookie
    assert "max-age=0" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
