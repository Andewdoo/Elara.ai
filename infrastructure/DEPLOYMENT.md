# Production deployment runbook

Elara uses GitHub-connected deployments. Vercel owns the Next.js deployment; a
GitHub-connected container host owns separate FastAPI and Celery services. Firebase
Hosting, Firestore, Firebase Storage, Firebase Functions, public object buckets, and
browser-side provider/database calls are not part of this topology.

## Vercel frontend

1. Import the GitHub repository and set the project root to `apps/web`.
2. Configure `NEXT_PUBLIC_API_BASE_URL` and the four public Firebase Web values for
   Preview and Production. Do not add Firebase Admin, DeepSeek, Brave, database,
   Redis, object-storage, Sentry auth-token, or LangSmith secrets to Vercel.
3. In Firebase Authentication, add every exact Vercel/custom hostname that can host
   sign-in UI to **Authentication > Settings > Authorized domains**. Preview domains
   should be intentionally allowlisted or use a stable preview domain; do not add a
   wildcard. Authorized domains are not API authorization - FastAPI still verifies
   every token and applies PostgreSQL ownership checks.

## API and worker host

Create two services from the same GitHub revision:

- API: build `infrastructure/docker/api.Dockerfile`; expose HTTPS through the host.
- Worker: build `infrastructure/docker/worker.Dockerfile`; do not expose a public port.

Set `ENVIRONMENT=production`, an HTTPS `WEB_APP_URL`, and comma-separated exact HTTPS
`CORS_ALLOWED_ORIGINS`. Configure Firebase Admin, DeepSeek and Brave keys, PostgreSQL,
Redis, private S3-compatible storage, API/worker Sentry values, and worker-only
LangSmith-compatible tracing in the host secret manager. Never put tokens in SSE
URLs. The API session cookie is Secure, HttpOnly, host-only, short-lived, and named
with `__Host-`; use `SameSite=None` only when the frontend and API are genuinely
cross-site. Use TLS for PostgreSQL, Redis/Celery, and both S3 endpoints. Configure the
host to trust forwarded headers only from its own proxy so IP admission limits use the
real peer address.

Buckets remain private. Database rows store object keys, never permanent public URLs.
Authorized export reads receive signed download URLs lasting 60-900 seconds.
Set private-bucket lifecycle rules for abandoned uploads and snapshots according to
the approved retention policy; never delete an evidence snapshot still referenced by
a completed report.

## Release and migration gate

1. Build and test the exact Git commit, including security regressions and container builds.
2. Back up the production database and verify `alembic heads` reports exactly one head.
3. Run `alembic upgrade head` as a one-off release job with no web traffic routed to it.
4. Verify the migration job completed, then deploy API and worker from the same commit.
5. Check `/health`, authentication, queue admission, one SSE reconnect, worker progress,
   and a private signed export. Roll back application traffic before using a migration
   downgrade; review destructive downgrade SQL manually.

Use isolated Preview/staging/production databases, Redis instances, buckets, Firebase
projects or tenants, Sentry environments, and credentials. Rotate a credential if it
ever appears in a client bundle, URL, log, trace, or CI artifact.
