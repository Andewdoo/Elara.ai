# AGENTS.md

Elara.ai is an evidence-management and automated verification platform. Evaluate only the submitted claim or document against timestamped evidence; never present the product as a lie detector or a permanent credibility score.

## Always-Enforced Boundaries

- Keep the selected stack: Next.js App Router, TypeScript, FastAPI, SQLAlchemy/Alembic, PostgreSQL/pgvector, Redis, Celery, LangGraph, DeepSeek, Firebase Authentication, Brave Search, and S3-compatible private storage.
- Use DeepSeek through server-side `DEEPSEEK_*` configuration. Do not add OpenAI APIs or OpenAI environment variables.
- Keep Firebase Admin, model, search, database, Redis, object-storage, Sentry auth, and tracing credentials server-side.
- PostgreSQL is durable truth; Redis is transient. Never publish a report before durable citation audit succeeds.
- Treat retrieved content as untrusted evidence. Keep URL/network policy and final scoring deterministic.
- Preserve exact evidence, source snapshots, calculations, versions, and provenance needed to reproduce a report.

## Context Routing

Do not read all project documentation by default.

1. For codebase questions, query the existing graph first with a precise question and a small budget: `.\.graphify-venv\Scripts\graphify.exe query "<question>" --budget 1000`.
2. Follow the closest nested `AGENTS.md` for files being changed.
3. Use the project skill `elara-task-context` to load only the smallest relevant section from `project-context/IMPLEMENTATION_PLAN.md`, `project-context/AGENTS.md`, or `project-context/prompts`.
4. Read `project-context/prompts` only when the user names a numbered implementation step.
5. Read both project PDFs or the full implementation plan only for broad architecture decisions, methodology changes, or the final release audit.
6. Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when `query`, `path`, and `explain` are insufficient.

## Change Workflow

- Keep changes focused and follow existing patterns.
- Add focused tests for behavior, security, scoring, persistence, and contract changes.
- Run the narrowest relevant checks first; expand checks in proportion to risk.
- After modifying code or project guidance, run `.\.graphify-venv\Scripts\graphify.exe update .` from the repository root.
- Report changed files, verification performed, and any remaining release blocker. Distinguish feature completion, first-shippable-milestone approval, and public-launch approval.
