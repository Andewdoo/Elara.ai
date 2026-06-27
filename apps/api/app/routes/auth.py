from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.auth.firebase import FirebaseAuthenticationError, FirebaseGateway, get_firebase_gateway
from app.config import Settings, get_settings
from app.schemas.auth import SessionResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post("/session", response_model=SessionResponse)
def create_session(
    response: Response,
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    gateway: FirebaseGateway = Depends(get_firebase_gateway),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    if authenticated.id_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Fresh Firebase ID token is required",
        )
    try:
        session_cookie = gateway.create_session_cookie(authenticated.id_token, authenticated.principal)
    except FirebaseAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Recent Firebase sign-in is required",
        ) from exc
    response.set_cookie(
        key=settings.firebase_session_cookie_name,
        value=session_cookie,
        max_age=gateway.session_ttl_seconds,
        httponly=True,
        secure=True,
        samesite=settings.firebase_session_same_site,
        path="/",
    )
    return SessionResponse(expires_in_seconds=gateway.session_ttl_seconds)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> None:
    response.delete_cookie(
        key=settings.firebase_session_cookie_name,
        httponly=True,
        secure=True,
        samesite=settings.firebase_session_same_site,
        path="/",
    )
