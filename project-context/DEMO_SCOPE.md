# Elara Side-Project Demo Scope

This is the authoritative deployment posture for Elara.ai.

Elara is a personal, low-traffic side project built to run reliable, owner-controlled demonstrations. It is not a production SaaS, a public service, or a system expected to support significant traffic or continuous availability.

## Optimize for

- the simplest low-cost deployment that can run one convincing end-to-end demo;
- Vercel for the Next.js frontend and one AWS EC2 host for the Full Mode API, worker, PostgreSQL/pgvector, Redis, and supporting containers;
- stopping the EC2 instance between demos when appropriate;
- one hosted-demo environment rather than separate development, staging, and production infrastructure;
- manual recovery and restart procedures that are reasonable for an owner-operated side project.

Do not require high availability, multi-AZ services, autoscaling, Kubernetes, a WAF, managed PostgreSQL or Redis, formal on-call coverage, enterprise alert routing, production traffic migration, a separate staging environment, or public-launch certification unless the user explicitly changes the project scope.

## Keep these minimum demo boundaries

Low traffic does not make secret exposure or corrupt reports acceptable. Keep:

- Firebase Admin, DeepSeek, Brave, database, Redis, object-storage, Sentry auth, and tracing credentials server-side;
- PostgreSQL, Redis, object storage, and the Celery worker non-public;
- HTTPS for the browser-facing API;
- Firebase sign-in and FastAPI ownership checks for private runs and exports;
- PostgreSQL as durable truth and Redis as transient progress transport;
- deterministic scoring and durable citation audit before a report is shown as completed;
- the existing URL/network protections for untrusted retrieved content.

These are correctness and basic credential boundaries for the demo, not a claim that the deployment is production hardened.

## Hosted-demo success bar

The side project is ready to demo when:

1. the Vercel frontend and AWS API are reachable over HTTPS;
2. an approved tester can sign in with Firebase;
3. one approved public or synthetic claim is queued and processed by Celery;
4. progress survives an SSE reconnect by reloading PostgreSQL state;
5. the completed report and citation-audit records are durable;
6. the report can be opened again after refresh; and
7. server credentials and private service ports are not exposed.

A single database backup is sensible before material schema changes. Rollback rehearsals, Redis restart drills, queue-failure drills, comprehensive provider checks, cross-user denial checks, formal release audits, and a large evaluation program are optional follow-up work unless they are needed for the planned demo or the user explicitly requests them.

## Terminology

`production` may still appear where it is a technical name, such as a Vercel Production environment, an optimized Next.js production build, or the application's full runtime path. Those names do not change the deployment posture into a production SaaS launch.

Historical Step 25 public-beta and staging evidence remains historical evidence. It may explain how the current AWS host was prepared, but it no longer defines the release goal.
