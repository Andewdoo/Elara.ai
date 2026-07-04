# Elara Infrastructure

Deployment, container, environment, and CI/CD configuration for Elara.ai.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the production release, Firebase authorized-domain,
cookie, secret ownership, migration, and smoke-check runbook.

## Deployment and observability

- Connect Vercel directly to GitHub with `apps/web` as the project root. Preview and production deployment uses that integration; no Vercel token or project id belongs here.
- Deploy FastAPI and Celery as separate GitHub-connected services and run Alembic as a controlled release step.
- Use distinct Sentry projects and DSNs for web, API, and worker. `SENTRY_AUTH_TOKEN` is needed only by the web build for source-map upload.
- Keep LangSmith variables on the worker. Traces contain stable ids and aggregate metadata, never prompts, source passages, uploads, or credentials.
- Configure GitHub `staging` and `production` environments with required reviewers for the deployment-gates workflow.
- Set the optional `STAGING_API_BASE_URL` and `PRODUCTION_API_BASE_URL` environment variables to enable post-gate health checks against deployed API URLs.
