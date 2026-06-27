from datetime import timedelta
from functools import lru_cache
from threading import Lock
from time import time
from typing import Any

import firebase_admin
from firebase_admin import auth, credentials

from app.config import Settings, get_settings
from app.schemas.auth import FirebasePrincipal


class FirebaseAuthenticationError(ValueError):
    pass


class FirebaseConfigurationError(RuntimeError):
    pass


_firebase_app_lock = Lock()


class FirebaseGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _app(self) -> firebase_admin.App:
        try:
            return firebase_admin.get_app(name="elara-api")
        except ValueError:
            pass
        with _firebase_app_lock:
            try:
                return firebase_admin.get_app(name="elara-api")
            except ValueError:
                try:
                    credential = credentials.Certificate(self.settings.firebase_admin_credentials())
                    return firebase_admin.initialize_app(
                        credential,
                        options={"projectId": self.settings.firebase_project_id},
                        name="elara-api",
                    )
                except Exception as exc:
                    raise FirebaseConfigurationError("Firebase Admin is not configured correctly") from exc

    @staticmethod
    def _principal(claims: dict[str, Any]) -> FirebasePrincipal:
        uid = claims.get("uid") or claims.get("sub")
        if not isinstance(uid, str) or not uid:
            raise FirebaseAuthenticationError("Firebase token has no subject")
        return FirebasePrincipal(
            uid=uid,
            email=claims.get("email"),
            name=claims.get("name"),
            email_verified=bool(claims.get("email_verified", False)),
            auth_time=claims.get("auth_time"),
            issued_at=claims.get("iat"),
        )

    def verify_id_token(self, token: str) -> FirebasePrincipal:
        try:
            claims = auth.verify_id_token(token, app=self._app())
            return self._principal(claims)
        except FirebaseConfigurationError:
            raise
        except FirebaseAuthenticationError:
            raise
        except Exception as exc:
            raise FirebaseAuthenticationError("Invalid Firebase ID token") from exc

    def verify_session_cookie(self, cookie: str) -> FirebasePrincipal:
        try:
            claims = auth.verify_session_cookie(cookie, app=self._app(), check_revoked=True)
            return self._principal(claims)
        except FirebaseConfigurationError:
            raise
        except FirebaseAuthenticationError:
            raise
        except Exception as exc:
            raise FirebaseAuthenticationError("Invalid Firebase session cookie") from exc

    def create_session_cookie(self, id_token: str, principal: FirebasePrincipal) -> str:
        if principal.issued_at is None:
            raise FirebaseAuthenticationError("Firebase token has no issue time")
        age = int(time()) - principal.issued_at
        if age < -60 or age > self.settings.firebase_fresh_token_max_age_seconds:
            raise FirebaseAuthenticationError("A fresh Firebase ID token is required")
        try:
            return auth.create_session_cookie(
                id_token,
                expires_in=timedelta(seconds=self.session_ttl_seconds),
                app=self._app(),
            )
        except FirebaseConfigurationError:
            raise
        except Exception as exc:
            raise FirebaseAuthenticationError("Could not create Firebase session") from exc

    @property
    def session_ttl_seconds(self) -> int:
        return self.settings.firebase_session_ttl_minutes * 60


@lru_cache
def get_firebase_gateway() -> FirebaseGateway:
    return FirebaseGateway(get_settings())
