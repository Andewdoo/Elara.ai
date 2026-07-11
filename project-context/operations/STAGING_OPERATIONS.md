# Step 25A Private Internal AWS Operations Runbook

This runbook prepares the repository for private internal AWS validation. It does not deploy, request secrets, or define placeholder credentials. It does not approve a first-shippable milestone or public-production launch.

## External Prerequisites

- GitHub `staging` environment has `STAGING_API_BASE_URL` and `STAGING_WEB_APP_URL`.
- API and worker hosts set `ENVIRONMENT=staging` and the same non-secret `ELARA_RELEASE_REVISION` value, normally the Git commit SHA.
- Server-side configuration contains real Firebase Admin, DeepSeek, Brave, PostgreSQL/pgvector, Redis, private object-storage, and Sentry credentials. Do not copy values into git, CI logs, tickets, screenshots, or chat.
- The Full Mode database, Redis instance, and object bucket are separate from Lite Supabase data.
- Private object buckets enforce public-access block, non-public bucket policy status, default encryption, and lifecycle rules approved by governance.
- Backup tooling, restore targets, rollback permissions, alert routing, and on-call ownership exist in the external infrastructure provider.

## Smoke Gates

The deployment-gates workflow runs `scripts/smoke_gate.py` for internal staging. The gate fails closed when required URLs are missing, non-HTTPS, malformed, unreachable, or when `/health` does not return `{"status": "ok"}`. The web smoke check is credential-free and only verifies that the configured Vercel app origin responds without exposing secrets.

`/health` returns a non-secret environment and revision. During Phase 25B, compare the API `revision` to the worker/container revision reported by the host or release dashboard before running live cases.

## Controlled Migration Job

- Build and test one immutable Git revision.
- Verify `alembic heads` reports exactly one head.
- Back up the target database before migration.
- Run `alembic upgrade head` once as a controlled release job, separate from API and worker request traffic.
- Record the migration revision, start/end timestamps, operator, and sanitized job logs.
- If downgrade is needed, review generated downgrade SQL before execution. Prefer application rollback before destructive migration rollback.

## Backup and Restore

- Take an encrypted PostgreSQL backup immediately before migration rehearsal.
- Restore the backup into an isolated target, never over the live staging database.
- Verify pgvector extension availability, latest Alembic revision, row counts for core durable tables, and representative report/citation/source snapshot integrity.
- Confirm object-storage evidence snapshots referenced by completed reports remain available.

## Rollback

- Application rollback: route traffic back to the last approved API, worker, and web revision with no schema downgrade when the schema is forward-compatible.
- Migration rollback: only after human review of downgrade SQL, confirmation that completed reports and source snapshots remain reproducible, and backup/restore rehearsal has passed.
- Worker rollback: drain or stop workers, confirm queue ownership and visibility timeout behavior, then start workers from the selected compatible revision.

## Redis, Queues, and Dead Jobs

- Redis is transient. Restart Redis during staging and verify SSE reconnect and final report reload recover from PostgreSQL truth.
- Inspect `verification.quick`, `verification.standard`, and `verification.deep` queue depth before and after each live case.
- Confirm retries are bounded and idempotent, dead jobs are visible to the host or broker tooling, and terminal PostgreSQL state is not rewound by redelivery.
- Confirm retention cleanup runs as a controlled worker task and does not delete evidence snapshots referenced by completed reports.

## Signed Downloads and Bucket Permissions

- Create a JSON export for an authorized owner and verify only a short-lived signed URL is returned on authorized read.
- Confirm cross-user export reads return 404.
- Confirm bucket public-access block, policy status, and default encryption checks pass at API startup.
- Confirm rows store object keys, not permanent public URLs.

## Deferred: Credential Rotation

- Credential-rotation rehearsal is deferred for private internal deployment. Rotate immediately if any credential appears in a browser bundle, SSE URL, signed URL artifact, log, trace, or CI output.
- A future first-shippable or public-production release must rotate one credential per provider category and verify old credentials stop working.

## Deferred: Formal Alerts

Use `infrastructure/alerts.step25a.json` as a future checklist. Private internal deployment only requires that API, worker, provider, and citation-audit failures are visible in host logs or Sentry. Provider-specific thresholds, routes, and delivery evidence remain required for a future first-shippable or public-production release.

## Controlled Live Cases

Use `infrastructure/controlled-live-cases.step25a.json` during Phase 25B. Private internal deployment requires one approved public or synthetic claim case. The full set of claim, article URL, article text, quote, paraphrase, and uploaded-document cases remains required for a future first-shippable or public-production release. Stop on the first infrastructure blocker rather than repeatedly redeploying or retrying provider calls.
