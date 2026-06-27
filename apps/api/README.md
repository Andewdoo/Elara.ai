# Elara API

## Database migrations

From `apps/api`, apply the PostgreSQL schema with:

```powershell
python -m alembic upgrade head
```

`PASSAGE_EMBEDDING_DIMENSION` controls the `source_passages.embedding` vector dimension
when the initial migration is first applied. Set it before migrating and keep it aligned
with the approved embedding model. Existing databases require a new migration to change it.

FastAPI backend for Elara.ai.

This service is the authorization boundary for Firebase-authenticated users, durable verification run creation, report reads, SSE progress, protected snapshot/export access, and Celery job enqueueing.

## Local checks

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Ordinary protected routes require `Authorization: Bearer <Firebase ID token>`. The short-lived, Secure, HttpOnly Firebase session cookie is reserved for credentialed SSE; tokens are never accepted in URLs.

`users.usage_limits` currently recognizes `allowed_research_depths` (a list of `QUICK`, `STANDARD`, and/or `DEEP`) and `max_active_runs` (a non-negative integer). Missing keys impose no limit until plan policy is configured.

The session cookie defaults to `SameSite=Lax`. Set the server-side `FIREBASE_SESSION_SAME_SITE=none` only when the web and API origins are genuinely cross-site; the cookie remains Secure and HttpOnly.
