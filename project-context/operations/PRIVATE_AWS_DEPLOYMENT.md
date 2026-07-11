# Private Internal AWS Deployment

This runbook deploys Full Mode for the owner and a small, explicitly invited group. It is not a public-production launch guide and does not approve the first-shippable or public-production release bars.

## Scope and non-negotiable boundaries

- Keep Vercel as the Next.js host. `/verify` calls the AWS API; Lite Supabase data remains Lite-only.
- One AWS EC2 host may run the API, worker, PostgreSQL/pgvector, Redis, and the Compose S3-compatible service. Prefer a private AWS S3 bucket instead of the local object-store container when practical.
- Keep Firebase Admin, database, Redis, S3, Brave, DeepSeek, Sentry, and tracing credentials server-side. Keep the evidence bucket private, and keep Firebase authentication and FastAPI ownership checks enabled.
- Use HTTPS, a non-local `ELARA_RELEASE_REVISION`, and exact `WEB_APP_URL`/`CORS_ALLOWED_ORIGINS`. Do not publish permanent object URLs.

## 1. Create the AWS basics

1. Enable MFA for the AWS account and create a normal administrative user or role for setup; do not use the root account for deployment.
2. Create one EC2 instance with an attached EBS volume. Choose a size with enough memory for PostgreSQL, Redis, FastAPI, Celery, and the worker's Chromium-based extraction fallback.
3. Create an EC2 security group that allows SSH only from the owner's IP address and HTTPS from the invited users. Do not expose PostgreSQL, Redis, MinIO, or the Celery worker port.
4. Attach an instance role that can read only the required secrets and, if using AWS S3, access only the private Elara evidence bucket.
5. Point a domain or subdomain at the instance and provision a TLS certificate. The smoke gate requires an HTTPS API origin.

## 2. Prepare the host

1. Install Docker Engine and the Docker Compose plugin.
2. Clone this repository on the instance. Create a host-only `.env.private` from `.env.example`; never commit or copy it to a browser environment.
3. Set `ENVIRONMENT=staging`, a commit SHA in `ELARA_RELEASE_REVISION`, the exact Vercel origin in both `WEB_APP_URL` and `CORS_ALLOWED_ORIGINS`, and real server-side provider credentials.
4. For the Compose-managed database and Redis, use service hostnames rather than `localhost` in the API and worker URLs. Give `FETCH_STORAGE_DIR` a persistent path outside the application checkout.
5. If using AWS S3, set `S3_ENDPOINT_URL` and `S3_PUBLIC_ENDPOINT_URL` to the regional S3 endpoint, set `S3_FORCE_PATH_STYLE=false`, choose a non-public encrypted bucket, and provide credentials only through the instance role or server-side secrets.
6. Place Caddy or Nginx in front of FastAPI. Terminate TLS there and proxy only to the API container on port 8000.

## 3. Start and connect the services

1. Build and start the existing services:

   ```bash
   docker compose --profile app up -d --build
   ```

2. Verify API and worker images came from the same repository commit. Run Alembic as a one-off controlled task before routing traffic to an incompatible revision.
3. Configure Vercel `NEXT_PUBLIC_API_BASE_URL` with the HTTPS AWS API origin.
4. Add the exact Vercel hostname to Firebase Authentication's Authorized Domains. Keep Firebase Admin configuration on the AWS host only.
5. Configure GitHub environment `staging` variables: `STAGING_API_BASE_URL` and `STAGING_WEB_APP_URL`. Do not create a production environment for this private-deployment gate.

## 4. Minimum validation before inviting users

1. Run `python scripts/smoke_gate.py --environment staging --require-https` with the two staging URL variables present.
2. Confirm `/health` returns `status=ok` and the expected revision.
3. Sign in through Firebase, submit one approved public or synthetic claim, and confirm it reaches a citation-audited durable report.
4. Restart Redis once and confirm SSE reconnect reloads final state from PostgreSQL.
5. Create one authorized export, confirm it is a short-lived signed URL, and confirm a second user cannot read it.
6. Take one PostgreSQL backup. Test the documented application rollback path by returning API and worker to the previous compatible image; do not run a migration downgrade for this internal bar.
7. Record only sanitized evidence in `STAGING_VALIDATION_25B_EVIDENCE.md`; never include secret values, tokens, signed URLs, private uploads, prompts, or source passages.

## Deferred work

Multi-AZ availability, a separate production environment, formal on-call alert delivery, credential-rotation rehearsal, migration rollback rehearsal, and full MVP-input live-case coverage are intentionally deferred. They must remain visible as blockers to the first-shippable and public-production release bars.
