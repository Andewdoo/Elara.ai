from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.config import Settings, get_settings
from app.database.base import Base
from app.database.session import get_db
from app.main import create_app
from app.models import User
from app.schemas.auth import FirebasePrincipal


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        cors_allowed_origins=["http://localhost:3000"],
        firebase_session_cookie_name="elara_session",
    )


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def owner(session_factory: sessionmaker[Session]) -> User:
    with session_factory() as db:
        user = User(
            auth_provider="firebase",
            auth_subject="firebase-owner",
            email="owner@example.com",
            plan_tier="free",
            role="user",
            usage_limits={},
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], owner: User, settings: Settings
) -> Generator[TestClient, None, None]:
    app = create_app()

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    def override_authenticated() -> AuthenticatedUser:
        return AuthenticatedUser(
            principal=FirebasePrincipal(
                uid=owner.auth_subject,
                email=owner.email,
                auth_time=1_900_000_000,
                issued_at=1_900_000_000,
            ),
            user=owner,
            id_token="fresh-id-token",
        )

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_authenticated_bearer] = override_authenticated
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, base_url="https://api.example.test") as test_client:
        yield test_client
