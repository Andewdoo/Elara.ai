# Elara Infrastructure

Deployment, container, environment, and CI/CD configuration for Elara.ai.

The authoritative deployment and operations guidance is in [project-context/operations](../project-context/operations/). See [PRIVATE_AWS_DEPLOYMENT.md](../project-context/operations/PRIVATE_AWS_DEPLOYMENT.md) for the current private internal AWS runbook. [DEPLOYMENT.md](../project-context/operations/DEPLOYMENT.md) remains the stricter future public-production runbook.

## Deployment and observability

- Connect Vercel directly to GitHub with `apps/web` as the project root. Preview and production deployment uses that integration; no Vercel token or project id belongs here.
- Deploy FastAPI and Celery as separate GitHub-connected services and run Alembic as a controlled release step.
- Use distinct Sentry projects and DSNs for web, API, and worker. `SENTRY_AUTH_TOKEN` is needed only by the web build for source-map upload.
- Keep LangSmith variables on the worker. Traces contain stable ids and aggregate metadata, never prompts, source passages, uploads, or credentials.
- Configure the GitHub `staging` environment with the private internal API and web URLs. The deployment-gates workflow fails closed when either required smoke URL is missing or non-HTTPS.
