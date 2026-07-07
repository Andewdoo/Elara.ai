# Step 25A Staging Operations Runbook

This runbook prepares the repository for the real staging validation phase. It does not deploy, request secrets, or define placeholder production credentials.

## External Prerequisites

- GitHub `staging` and `production` environments have required reviewers.
- GitHub environment variables are set: `STAGING_API_BASE_URL`, `STAGING_WEB_APP_URL`, `PRODUCTION_API_BASE_URL`, and `PRODUCTION_WEB_APP_URL`.
- API and worker hosts set `ENVIRONMENT=staging` or `ENVIRONMENT=production` and the same non-secret `ELARA_RELEASE_REVISION` value, normally the Git commit SHA.
- Secret managers contain real Firebase Admin, DeepSeek, Brave, PostgreSQL/pgvector, Redis, private object-storage, Sentry, and optional tracing credentials. Do not copy those values into git, CI logs, tickets, screenshots, or chat.
- Staging and production use isolated PostgreSQL databases, Redis instances, object buckets, Firebase projects or tenants, Sentry environments, and provider credentials.
- Private object buckets enforce public-access block, non-public bucket policy status, default encryption, and lifecycle rules approved by governance.
- Backup tooling, restore targets, rollback permissions, alert routing, and on-call ownership exist in the external infrastructure provider.

## Smoke Gates

The deployment-gates workflow runs `scripts/smoke_gate.py` for staging and production. The gate fails closed when required URLs are missing, non-HTTPS, malformed, unreachable, or when `/health` does not return `{"status": "ok"}`. The web smoke check is credential-free and only verifies that the public app origin responds without exposing secrets.

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

## Credential Rotation

- Rotate one staging credential per provider category during Phase 25B: Firebase Admin, DeepSeek, Brave, PostgreSQL, Redis, object storage, Sentry, and tracing if enabled.
- Verify old credentials stop working after rotation and no client bundle, URL, log, trace, or artifact contains the rotated value.
- Rotate immediately if any credential appears in a browser bundle, SSE URL, signed URL artifact, log, trace, or CI output.

## Alerts

Use `infrastructure/alerts.step25a.json` as the alert definition checklist. Required alert coverage includes API failures, queue depth, run duration, provider failures, extraction failure, low evidence yield, citation-audit failure, cost, and security events. Phase 25B must attach provider-specific thresholds, routes, and delivery evidence without committing secrets.

## Controlled Live Cases

Use `infrastructure/controlled-live-cases.step25a.json` during Phase 25B. Run one approved public or synthetic case for each MVP input type: claim, article URL, article text, quote, paraphrase, and uploaded document. Stop on the first infrastructure blocker rather than repeatedly redeploying or retrying provider calls.
