# Side-Project Demo Deployment Runbook

This is the current Full Mode deployment guide. Elara is a personal, low-traffic side project for demos, not a production SaaS. Follow [DEMO_SCOPE.md](../DEMO_SCOPE.md).

## Topology

- Vercel hosts the Next.js app from `apps/web`.
- One AWS EC2 host runs the FastAPI API, Celery worker, PostgreSQL/pgvector, Redis, and supporting containers.
- The existing private AWS S3 bucket stores evidence objects.
- Only the browser-facing HTTPS API is public. PostgreSQL, Redis, object storage, and the worker stay non-public.

This topology intentionally has one host and one environment. Do not add high availability, multi-AZ services, autoscaling, managed database/Redis, Kubernetes, WAF, formal on-call, or a staging-to-production promotion program for the demo.

## Current AWS runtime

The CloudFormation stack is `elara-public-beta-runtime` in `us-east-1`. The legacy stack name does not change the current side-project scope. Obtain current values from CloudFormation outputs rather than copying addresses into instructions.

The host may be stopped between demos to save credits. Start it early enough for PostgreSQL, Redis, API, worker, and the proxy to become healthy.

## HTTPS API address

Prefer an AWS-managed path:

1. Use `api.elara.io` only when the public domain is actually delegated to the current Route 53 hosted zone.
2. If registrar delegation is unavailable and the user does not want to use the registrar, put an AWS CloudFront distribution in front of the EC2 HTTP origin and use its default `*.cloudfront.net` HTTPS hostname for the demo.

Do not wait on a custom-domain transfer merely to demonstrate the side project. Whichever hostname is used must be placed in `NEXT_PUBLIC_API_BASE_URL`, `WEB_APP_URL`, exact CORS origins, Firebase authorized domains where applicable, and the smoke command.

For the CloudFront fallback:

- use the EC2 public DNS name as a custom origin and serve an explicit HTTP-only origin listener from Caddy; CloudFront supplies viewer HTTPS through its default certificate;
- set Viewer Protocol Policy to redirect HTTP to HTTPS;
- allow all API methods (`GET`, `HEAD`, `OPTIONS`, `PUT`, `POST`, `PATCH`, and `DELETE`);
- disable caching for API responses;
- forward the authorization header, origin header, cookies, and query strings needed by FastAPI, Firebase sessions, CORS, and SSE;
- validate `/health`, sign-in/session cookies, POST requests, and SSE through the CloudFront hostname before pointing Vercel at it.

The CloudFormation stack exposes `CloudFrontDomainName` as the non-secret HTTPS API address. Caddy listens only on the EC2 HTTP origin port; CloudFront's default certificate supplies viewer HTTPS. Apply this template through a reviewed CloudFormation change set, wait for the distribution to deploy, and validate `https://<CloudFrontDomainName>/health` before updating Vercel. CloudFront pay-as-you-go usage may consume AWS credits; AWS Free Tier accounts cannot subscribe to the separate CloudFront flat-rate plans.

## Start or update the backend

1. Start the EC2 instance and wait for both EC2 status checks and SSM connectivity.
2. Confirm the checked-out revision and the stack `GitRef` match.
3. From the application checkout, start the existing Compose profile:

   ```bash
   docker compose --env-file .env.private --profile app up -d --build
   ```

4. If the revision includes a migration, take one quick PostgreSQL backup and run `alembic upgrade head` once before starting incompatible API/worker code.
5. Confirm API and worker report the same `ELARA_RELEASE_REVISION`.
6. Confirm the local health endpoint, worker, PostgreSQL, Redis, and object-storage initialization are healthy.

Do not print `.env.private`, provider keys, Firebase Admin values, signed URLs, prompts, private uploads, or source passages.

## Configure Vercel

1. Keep `apps/web` as the project root.
2. Set `NEXT_PUBLIC_API_BASE_URL` to the chosen AWS HTTPS hostname.
3. Configure the four public Firebase Web values in Vercel. Keep Firebase Admin, DeepSeek, Brave, database, Redis, S3, Sentry auth-token, and tracing secrets off Vercel and on the AWS host.
4. Redeploy the chosen commit to the stable Vercel URL. Vercel calls this its Production environment; that is a platform label, not a production-SaaS claim.
5. Add the exact Vercel hostname to Firebase Authentication Authorized Domains.

## Minimum demo gate

Stop adding infrastructure once all of these pass:

1. The HTTPS API `/health` response is healthy and the Vercel page loads.
2. Firebase sign-in creates a valid API session.
3. One approved public or synthetic claim is accepted and queued.
4. Celery processes it through synthesis and citation audit.
5. The completed report reloads from PostgreSQL after refresh or SSE reconnect.
6. The report shows durable citations and no internal service or credential is browser exposed.

Useful but non-blocking follow-ups include one signed-export ownership check, one Redis restart/SSE recovery check, and one database backup. Formal rollback rehearsal, queue disaster recovery, exhaustive provider telemetry, multi-AZ, and public-launch readiness are outside the current scope.

## Before each demo

- Start the EC2 host and verify the HTTPS health endpoint.
- Confirm the Vercel frontend points to the current HTTPS API hostname.
- Sign in with the demo account.
- Use one pre-approved claim that has reliable accessible sources.
- Keep a second reviewed report available as a fallback walkthrough.
- After the demo, stop the EC2 instance if the backend does not need to remain available.
