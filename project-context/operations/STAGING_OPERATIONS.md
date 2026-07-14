# Hosted Demo Operations

This legacy filename now describes the single AWS hosted-demo environment. Elara does not require a separate staging environment for its current side-project scope.

## Required before a demo

- The EC2 host is running, its status checks pass, and SSM is connected.
- API and worker use the same non-local revision.
- PostgreSQL, Redis, API, worker, proxy, and private object storage are healthy.
- The API has a browser-reachable HTTPS hostname.
- The Vercel app points to that hostname and the exact Vercel origin is allowed by FastAPI.
- Firebase sign-in works for the approved demo account.
- One approved claim reaches a durable citation-audited report.

## Sensible owner-operated recovery

- If progress disconnects, refresh and reload authoritative state from PostgreSQL.
- If Redis or Celery is unhealthy, restart the affected container and retry the approved demo claim once.
- If the current application revision is broken and the schema is compatible, return the checkout and API/worker images to the last known working revision.
- Before a schema-changing update, take one PostgreSQL backup. A formal restore or migration-downgrade rehearsal is not required for the demo.

## Optional checks

Run these when they help the planned presentation, not as a release ceremony:

- Redis restart and SSE reconnect;
- Celery retry and worker restart;
- signed export plus cross-user denial;
- Brave, DeepSeek, Sentry, and redacted tracing visibility;
- application rollback to the previous compatible revision.

High availability, multi-AZ recovery, formal alert delivery, credential-rotation rehearsal, migration rollback rehearsal, every-input live cases, and public-production approval are out of scope unless the user explicitly expands the project.
