from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User, utc_now
from app.schemas.auth import FirebasePrincipal


class InactiveUserError(PermissionError):
    pass


class UserProvisioningConflictError(RuntimeError):
    pass


def _firebase_email(principal: FirebasePrincipal) -> str:
    return principal.email or f"{principal.uid}@users.firebase.invalid"


def get_or_create_firebase_user(db: Session, principal: FirebasePrincipal) -> User:
    user = db.scalar(
        select(User).where(
            User.auth_provider == "firebase",
            User.auth_subject == principal.uid,
        )
    )
    if user is not None:
        if user.deleted_at is not None:
            raise InactiveUserError("This application account is inactive")
        changed = False
        if principal.email and principal.email != user.email:
            user.email = principal.email
            changed = True
        if principal.name is not None and principal.name != user.display_name:
            user.display_name = principal.name
            changed = True
        if changed:
            user.updated_at = utc_now()
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise UserProvisioningConflictError("Firebase identity conflicts with an existing user") from exc
        return user

    user = User(
        auth_provider="firebase",
        auth_subject=principal.uid,
        email=_firebase_email(principal),
        display_name=principal.name,
        plan_tier="free",
        role="user",
        usage_limits={},
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        concurrent_user = db.scalar(
            select(User).where(
                User.auth_provider == "firebase",
                User.auth_subject == principal.uid,
            )
        )
        if concurrent_user is not None and concurrent_user.deleted_at is None:
            return concurrent_user
        if concurrent_user is not None:
            raise InactiveUserError("This application account is inactive") from exc
        raise UserProvisioningConflictError("Firebase identity conflicts with an existing user") from exc
    db.refresh(user)
    return user
