# Step 25B Staging Validation Evidence

Date: 2026-07-07

Status: Blocked before live-provider validation.

## Scope

This evidence note covers the attempted Phase 25B entry checks for the already-provisioned staging environment. It records only sanitized operational facts. It does not contain secret values, bearer tokens, signed URLs, provider responses, private prompts, source passages, uploaded documents, or credential material.

## Sanitized Evidence

- Root and relevant nested `AGENTS.md` guidance were followed.
- Graphify was queried first for Step 25B staging validation with a 1000-token budget.
- The Step 25 prompt and matching Step 25 implementation-plan section were loaded without reading the full implementation plan or project PDFs.
- Directly relevant project guidance was loaded for system boundaries, persistence, API behavior, testing priorities, and completion closure.
- Required staging environment variable names were checked from the current process environment. Values were not printed, copied, or modified.
- The required staging environment variable name check was rerun on 2026-07-06 from the Codex process environment. Values were not printed, copied, or modified.
- `ELARA_RELEASE_REVISION` was checked before continuing Phase 25B. Sanitized result: present=true, local=false, length=40. The value was not printed.
- Present required names: `API_BASE_URL`, `WEB_APP_URL`, `CORS_ALLOWED_ORIGINS`, `ENVIRONMENT`, `ELARA_RELEASE_REVISION`, `FIREBASE_PROJECT_ID`, `FIREBASE_CLIENT_EMAIL`, `FIREBASE_PRIVATE_KEY`, `NEXT_PUBLIC_FIREBASE_API_KEY`, `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`, `NEXT_PUBLIC_FIREBASE_PROJECT_ID`, `NEXT_PUBLIC_FIREBASE_APP_ID`, `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `S3_ENDPOINT_URL`, `S3_PUBLIC_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `S3_REGION`, `SEARCH_PROVIDER`, `SEARCH_API_KEY`, `SEARCH_BASE_URL`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_CHAT_MODEL`, `DEEPSEEK_REASONING_MODEL`, `SENTRY_DSN_API`, `SENTRY_DSN_WORKER`, `SENTRY_ORG`, `SENTRY_PROJECT_WEB`, `SENTRY_PROJECT_API`, `SENTRY_PROJECT_WORKER`, `SENTRY_AUTH_TOKEN`, `SENTRY_TRACES_SAMPLE_RATE`, `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, and `LANGSMITH_ENDPOINT`.
- Missing required names: none.
- The API settings gate was run through the repository API environment with sanitized Pydantic errors only.
- The API settings gate was rerun on 2026-07-06 through the repository API virtual environment with sanitized Pydantic errors only.
- A repository config mismatch was found before live validation: project runbooks and `.env.example` use `ELARA_RELEASE_REVISION`, while the API settings field did not read that documented variable name. The settings mapping was corrected to read `ELARA_RELEASE_REVISION` without printing the value, with `RELEASE_REVISION` retained as a fallback.
- After the mapping fix, the API settings gate advanced past the release-revision check and failed on HTTPS staging origin enforcement.
- Sanitized staging origin shape for `WEB_APP_URL`: present=true, absolute_http=true, https=false, has_credentials=false, has_path_query_fragment=false.
- On 2026-07-07, the Step 25B sanitized entry gate was rerun before continuing. `API_BASE_URL` and `WEB_APP_URL` were present, HTTPS, and origin-only. `ELARA_RELEASE_REVISION` was present, not `local`, and length 40. Values were not printed.
- The credential-free staging smoke gate was run with HTTPS enforcement and expected release revision. Values were not printed. Sandboxed execution reported an unreachable target, so the same sanitized check was rerun with outbound HTTPS access.
- The unsandboxed credential-free staging smoke gate reached staging but failed with sanitized result: `reason=http_status_failure`.

## Infrastructure Blocker

The current Step 25B blocker is the credential-free staging smoke gate returning an HTTP status failure from a configured staging origin. The failing origin value and response body were not printed or recorded.

Per Step 25B instructions, validation stopped at the first remaining infrastructure blocker instead of running live-provider checks, migrations, rollback rehearsals, queue recovery tests, credential rotation, alert delivery, or MVP live cases against a staging environment whose credential-free smoke gate is not passing.

## Not Attempted After Blocker

- Real Firebase Authentication validation.
- PostgreSQL/pgvector migration, backup, restore, rollback, and revision compatibility validation.
- Redis recovery, SSE reconnect, retries, and dead-job validation.
- Private object-storage signed download and bucket-permission validation.
- Brave and DeepSeek live-provider validation.
- Sentry and redacted tracing validation.
- Credential rotation validation.
- Alert route and delivery validation.
- Controlled live cases for claim, article URL, article text, quote, paraphrase, and uploaded document inputs.
