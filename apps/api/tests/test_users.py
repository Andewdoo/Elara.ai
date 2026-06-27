import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.user import User
from app.schemas.auth import FirebasePrincipal
from app.services.users import InactiveUserError, get_or_create_firebase_user


def test_firebase_identity_loads_or_creates_one_user(session_factory: sessionmaker[Session]):
    principal = FirebasePrincipal(uid="firebase-123", email="person@example.com", name="Person")
    with session_factory() as db:
        first = get_or_create_firebase_user(db, principal)
        second = get_or_create_firebase_user(db, principal)

        assert first.id == second.id
        assert second.auth_provider == "firebase"
        assert second.auth_subject == "firebase-123"
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_soft_deleted_identity_is_not_reprovisioned(session_factory: sessionmaker[Session]):
    principal = FirebasePrincipal(uid="deleted-uid", email="deleted@example.com")
    with session_factory() as db:
        user = get_or_create_firebase_user(db, principal)
        user.deleted_at = user.updated_at
        db.commit()

        with pytest.raises(InactiveUserError):
            get_or_create_firebase_user(db, principal)
        assert db.scalar(select(func.count()).select_from(User)) == 1
