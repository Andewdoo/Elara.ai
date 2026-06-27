from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.firebase import FirebaseAuthenticationError, FirebaseGateway, get_firebase_gateway
from app.config import Settings, get_settings
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import FirebasePrincipal
from app.services.users import (
    InactiveUserError,
    UserProvisioningConflictError,
    get_or_create_firebase_user,
)

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    principal: FirebasePrincipal
    user: User
    id_token: str | None = None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid Firebase authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _load_user(db: Session, principal: FirebasePrincipal) -> User:
    try:
        return get_or_create_firebase_user(db, principal)
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Application account is inactive") from exc
    except UserProvisioningConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Firebase identity could not be linked to an application account",
        ) from exc


def get_authenticated_bearer(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    gateway: FirebaseGateway = Depends(get_firebase_gateway),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        principal = gateway.verify_id_token(credentials.credentials)
    except FirebaseAuthenticationError as exc:
        raise _unauthorized() from exc
    user = _load_user(db, principal)
    return AuthenticatedUser(principal=principal, user=user, id_token=credentials.credentials)


def get_authenticated_session(
    request: Request,
    gateway: FirebaseGateway = Depends(get_firebase_gateway),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    cookie = request.cookies.get(settings.firebase_session_cookie_name)
    if not cookie:
        raise _unauthorized()
    try:
        principal = gateway.verify_session_cookie(cookie)
    except FirebaseAuthenticationError as exc:
        raise _unauthorized() from exc
    user = _load_user(db, principal)
    return AuthenticatedUser(principal=principal, user=user)
