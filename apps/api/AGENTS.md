# API Guidance

- FastAPI is the authentication, authorization, validation, and ownership boundary.
- Verify Firebase ID tokens for normal API calls. Use short-lived `HttpOnly`, `Secure` Firebase session cookies for credentialed SSE; never put tokens in URLs.
- Commit the durable run and initial public event before enqueueing Celery work.
- Read final status, reports, sources, calculations, and authorization state from PostgreSQL. Redis progress is informative and may disappear.
- Enforce ownership or explicit share policy for every run, source, snapshot, export, feedback, and saved-report operation.
- Use Pydantic schemas, SQLAlchemy models, and Alembic migrations. Include downgrade logic when practical and preserve existing snapshots used by completed reports.
- Keep exact-origin credentialed CORS and security-header behavior intact.
- Add or update API tests for authentication, cross-user denial, persistence boundaries, route contracts, and SSE replay/reconnect behavior.

Use `elara-task-context` to load only the applicable API, schema, migration, or SSE section from the implementation plan.

