from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ResponseError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import (
    AuthenticatedUser,
    get_authenticated_bearer,
    get_authenticated_session,
)
from app.config import Settings, get_settings
from app.database.base import Base
from app.database.session import get_db
from app.main import create_app
from app.routes.verifications import get_request_redis_client
from app.models import User
from app.schemas.auth import FirebasePrincipal
from app.services.queueing import get_verification_dispatcher


class FakeRedis:
    def __init__(self) -> None:
        self.streams: dict[str, list[dict[str, str]]] = {}
        self.stream_ids: dict[str, set[str]] = {}
        self.stream_entries: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.values: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    def xadd(self, key: str, fields: dict[str, str], **_: object) -> str:
        event_id = str(_.get("id", f"{len(self.streams.get(key, [])) + 1}-0"))
        ids = self.stream_ids.setdefault(key, set())
        if event_id in ids:
            raise ResponseError("ID is equal or smaller than the target stream top item")
        ids.add(event_id)
        events = self.streams.setdefault(key, [])
        events.append(fields)
        self.stream_entries.setdefault(key, []).append((event_id, fields))
        return event_id

    def xread(self, streams: dict[str, str], **_: object):
        batches = []
        for key, cursor in streams.items():
            cursor_parts = tuple(int(part) for part in cursor.split("-", maxsplit=1))
            entries = [
                (event_id, fields)
                for event_id, fields in self.stream_entries.get(key, [])
                if tuple(int(part) for part in event_id.split("-", maxsplit=1)) > cursor_parts
            ]
            if entries:
                batches.append((key, entries))
        return batches

    def expire(self, key: str, ttl: int) -> bool:
        self.expirations[key] = ttl
        return True

    def set(self, key: str, value: str, **_: object) -> bool:
        self.values[key] = value
        return True

    def exists(self, key: str) -> int:
        return int(key in self.values)

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def ttl(self, key: str) -> int:
        return self.expirations.get(key, -1)


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []
        self.failure: Exception | None = None

    def enqueue(self, run_id: object, research_depth: object) -> str:
        self.calls.append((run_id, research_depth))
        if self.failure is not None:
            raise self.failure
        return "task-test-id"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite://",
        cors_allowed_origins=["http://localhost:3000"],
        firebase_session_cookie_name="elara_session",
    )


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


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
    session_factory: sessionmaker[Session],
    owner: User,
    settings: Settings,
    fake_redis: FakeRedis,
    dispatcher: RecordingDispatcher,
) -> Generator[TestClient, None, None]:
    app = create_app(settings)

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
    app.dependency_overrides[get_authenticated_session] = override_authenticated
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_request_redis_client] = lambda: fake_redis
    app.dependency_overrides[get_verification_dispatcher] = lambda: dispatcher
    with TestClient(app, base_url="https://api.example.test") as test_client:
        yield test_client
