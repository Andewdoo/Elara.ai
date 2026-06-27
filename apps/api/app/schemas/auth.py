from pydantic import BaseModel, Field


class FirebasePrincipal(BaseModel):
    uid: str = Field(min_length=1, max_length=255)
    email: str | None = None
    name: str | None = None
    email_verified: bool = False
    auth_time: int | None = None
    issued_at: int | None = None


class SessionResponse(BaseModel):
    expires_in_seconds: int
