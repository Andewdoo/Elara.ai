# Elara Infrastructure

Deployment, container, environment, and CI/CD configuration for the Elara.ai side-project demo.

The authoritative scope is [DEMO_SCOPE.md](../project-context/DEMO_SCOPE.md). Use [DEPLOYMENT.md](../project-context/operations/DEPLOYMENT.md) for the current AWS/Vercel demo runbook. `PUBLIC_BETA_AWS_DEPLOYMENT.md` and Step 25 staging files are retained for compatibility and historical evidence; they are not production-launch requirements.

## Deployment and observability

- Connect Vercel directly to GitHub with `apps/web` as the project root. Vercel's environment named Production is the stable demo URL; that product label does not mean Elara is a production SaaS.
- Run FastAPI, Celery, PostgreSQL/pgvector, and Redis on the existing single AWS EC2 demo host. Run Alembic before starting an incompatible revision.
- Use distinct Sentry projects and DSNs for web, API, and worker. `SENTRY_AUTH_TOKEN` is needed only by the web build for source-map upload.
- Keep LangSmith variables on the worker. Traces contain stable ids and aggregate metadata, never prompts, source passages, uploads, or credentials.
- For the final demo, run the smoke script directly with the HTTPS API and Vercel URLs. A separate GitHub staging environment is optional.
