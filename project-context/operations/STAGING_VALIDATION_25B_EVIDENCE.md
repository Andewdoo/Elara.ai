# Step 25B Staging Validation Evidence

> Historical evidence note. The former public-beta/staging release program is superseded by `project-context/DEMO_SCOPE.md`. Keep the facts below as an audit trail, but do not treat former first-shippable or public-production gates as blockers to the current side-project demo.

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

## 2026-07-13 Validation Attempt

Status: Blocked before the credential-free HTTPS smoke gate.

### Sanitized Entry Evidence

- The Step 25B prompt, implementation-plan section, and public-beta operations runbooks were reviewed without loading the full implementation plan or project PDFs.
- The local Codex process was checked only for required staging configuration names; no values were printed, copied, or modified. The API and web origins, release revision, and required server-side provider configuration names were unavailable in this process.
- A single read-only AWS identity access check was attempted to reach the configured AWS secret-store/deployment context. The AWS CLI was not available on this workstation, so no AWS API request, secret retrieval, deployment action, or configuration modification occurred.

### Infrastructure Blocker

The validation runner has no authorized, installed AWS access path to the already-provisioned public-beta environment or its configured secret store, and no injected non-secret staging origins. Consequently, the required credential-free HTTPS smoke gate cannot be run. Per the Step 25B procedure, validation stops here; do not retry deployment or proceed to provider, migration, backup, rollback, Redis/SSE, queue, storage, Sentry, or live-case checks from this runner.

### Required Handoff Prerequisites

- Run Phase 25B from an authorized AWS/SSM session or an approved runner with read-only deployment access and the existing secret-store injection path.
- Supply `API_BASE_URL`, `WEB_APP_URL`, and the expected non-local release revision to the smoke gate without exposing secret values.
- Preserve the existing public-beta constraints: private encrypted object storage; non-public database, Redis, object storage, and worker; and no secret values in logs, artifacts, traces, or this evidence record.

### Deferred Release Requirements

Multi-AZ availability, production-environment separation, formal alert routing, credential-rotation rehearsal, migration-rollback rehearsal, and every-MVP-input live-case coverage remain deferred. These prevent first-shippable-milestone approval and public-production approval.

## 2026-07-13 Authorized-Session Follow-up

Status: Blocked before AWS/SSM environment access.

### Sanitized Evidence

- The organization-approved AWS CLI and Session Manager Plugin were installed with machine scope. Their executables were verified locally; no project dependency was installed or changed.
- A single read-only `sts get-caller-identity` check was attempted with all raw output redacted. It did not establish an AWS principal, so the runner has no verified authorization for the existing public-beta environment.

### Infrastructure Blocker

Although the AWS and SSM clients are installed, no authorized AWS identity is available to this session. Do not attempt SSM, secret-store access, host discovery, smoke checks, or infrastructure operations until the approved AWS credential/role-assumption path is available. No secret value was read, printed, copied, or modified.

## 2026-07-13 AWS Console and SSM Validation Attempt

Status: Blocked before the credential-free HTTPS smoke gate.

### Sanitized Evidence

- The already-provisioned public-beta CloudFormation runtime stack was present and in a completed state. Its single-host runtime instance was running and passed all EC2 status checks.
- The host's SSM agent was online and connected. One browser-based Session Manager session was opened using the instance's configured role and then terminated after the entry check.
- The first smoke-gate entry command verified that the documented application checkout path is absent on the host. Command chaining stopped before loading the private environment file, so no secret value was read, printed, copied, or modified.

### Infrastructure Blocker

The deployed public-beta host does not contain the application checkout at `/opt/elara/app`, despite the public-beta deployment procedure requiring that location for the private environment injection and controlled migration/smoke workflow. Therefore the configured non-secret API and web origins and expected revision cannot be loaded for the required credential-free smoke gate. Per Phase 25B, stop validation here; do not redeploy, retry alternate application paths, or run provider, database, Redis/SSE, queue, object-storage, Sentry, or live-case validation until the deployment path mismatch is resolved through the approved release procedure.

## 2026-07-13 Approved Checkout-Restoration Attempt

Status: Blocked before checkout restoration and HTTPS smoke validation.

### Sanitized Evidence

- The completed public-beta stack parameters identified one immutable Git revision and the configured repository URL. No secret values were viewed or recorded.
- The SSM interactive user does not own `/opt`; a single non-interactive elevation check confirmed the approved bootstrap-level elevation path is available.
- The root-level clone command reached GitHub but required an interactive username for the configured repository. No username, password, personal access token, deploy key, or other GitHub credential was entered, transmitted, read, or copied. The SSM session was terminated and the checkout did not complete.

### Infrastructure Blocker

The approved public-beta host bootstrap cannot clone the configured repository non-interactively because it has no approved server-side GitHub read credential or artifact source. Resolve this through the release procedure by providing a least-privilege, server-side-only source-access mechanism (for example, an approved GitHub App/deploy credential or immutable private build artifact) that is retrieved without exposing its value. Do not make the repository public, paste a credential into a terminal, chat, CI log, browser field, or application configuration, or retry the clone until that mechanism is approved and configured.

## 2026-07-13 Read-Only Source Credential Setup

Status: Source credential configured; checkout and smoke validation remain blocked.

### Sanitized Evidence

- A new dedicated AWS Secrets Manager secret was created for the private half of an Ed25519 source deploy key. Its value was generated inside AWS CloudShell and was never displayed, copied, or placed in the application secret.
- GitHub received the public half as one repository-specific deploy key with read-only access. Write access was not requested.
- The public-beta instance role received one inline policy permitting only `secretsmanager:GetSecretValue` on that dedicated source-key secret. The local CloudFormation definition was updated to express the same least-privilege access and transient-key bootstrap behavior; the running stack was not updated or redeployed during this phase.
- A controlled SSH checkout attempt used the dedicated secret transiently. It did not complete within the allowed wait, was cancelled without a second clone attempt, and temporary source-key files were then verified absent from the host's temporary directory.

### Infrastructure Blocker

The one controlled SSH clone did not reach an immutable-checkout completion state through the SSM session. The immediate cause is not yet evidenced, and no network retry or alternate transport was run. Do not continue to application startup, smoke, migration, backup, Redis/SSE, queue, storage, provider, Sentry, or live-case validation. A future approved remediation must first diagnose the host-to-GitHub source transport with bounded, sanitized diagnostics and apply the updated CloudFormation definition so the instance-role policy and bootstrap procedure are durable rather than manual drift.

## 2026-07-13 Bounded Source-Transport Diagnosis

Status: Blocked before checkout restoration and the credential-free HTTPS smoke gate.

### Sanitized Evidence

- One newly opened SSM session ran a bounded, non-interactive GitHub SSH authentication diagnostic using the dedicated secret only as a transient file in `/run`. The command used a connection timeout and classified its output without recording the SSH response or any credential material.
- The diagnostic reached GitHub, accepted the GitHub host identity after the interactive terminal presented its host-key confirmation, and returned `SOURCE_TRANSPORT=AUTH_FAIL`.
- No clone retry, alternate source transport, application restore, deployment, migration, backup, Redis/SSE, queue, object-storage, provider, Sentry, or live-case operation was performed after that first authenticated-transport failure.
- Temporary deploy-key files in `/run` were removed and their absence was verified (`TEMP_SOURCE_KEY_CLEANUP=PASS`). The SSM session was then terminated.

### Infrastructure Blocker

GitHub rejected the configured read-only deploy key during the one bounded host-to-GitHub SSH authentication attempt. The evidence does not establish whether the stored private key, repository deploy-key association, or key-policy configuration is mismatched. Do not retry authentication or proceed with Step 25B until an approved operator repairs that source credential and verifies the active CloudFormation stack has the durable source-bootstrap parameters and least-privilege role policy.

## 2026-07-13 Source Credential and Durable Bootstrap Remediation

Status: Source credential verified and durable CloudFormation source bootstrap applied. Phase 25B was not resumed in this remediation.

### Sanitized Evidence

- The dedicated AWS Secrets Manager private key derived to the same SHA-256 public-key fingerprint as the single read-only GitHub repository deploy key. No private-key material was displayed, copied, or written outside a transient restricted file.
- One bounded non-interactive SSH authentication check against GitHub used the dedicated key with `IdentitiesOnly`, host-key verification, and a connection timeout. The association authenticated successfully, and its transient key directory was removed.
- The local public-beta CloudFormation template passed `validate-template` before deployment. A reviewed change set limited the update to the instance role, host user data, and the dependent Elastic IP association.
- The change set was executed against `elara-public-beta-runtime` in `us-east-1`, and the stack reached `UPDATE_COMPLETE`.
- The active stack now stores the SSH repository URL and the dedicated source deploy-key secret name as parameters. The instance role's inline policy grants `secretsmanager:GetSecretValue` only to the application secret and dedicated source-key secret patterns.
- The temporary CloudShell template file was removed. No application secret, private key, token, signed URL, provider response, prompt, source passage, or private upload was printed or recorded.

### Remaining Validation Boundary

This remediation proves the source credential association and makes the least-privilege source bootstrap durable in CloudFormation. It does not prove that the existing host reran user data, restored `/opt/elara/app`, completed bootstrap, or passes the credential-free HTTPS smoke gate. Verify those entry conditions in a separate approved Phase 25B continuation before running migrations, backups, rollback, Redis/SSE, queue, storage, provider, Sentry, or live-case validation.

## 2026-07-13 Authorized Phase 25B Continuation

Status: Blocked at the credential-free public HTTPS smoke gate after successful runtime recovery.

### Sanitized Infrastructure and Runtime Evidence

- The active host contains the immutable application checkout and its detached revision matches the stack `GitRef` (`1a9a1f97750c0b5081e2de71436e428473eb00ea`). The API and worker images report the same revision.
- The private environment file remained mode `0600`. Required API settings passed without displaying or modifying any secret value. Only web-only public Firebase names were absent from the host file; they are not API startup requirements.
- The CloudFormation bootstrap now supplies `API_DOMAIN`, the stack `EvidenceBucketName`, and `--env-file .env.private` explicitly to Compose. This prevents secret-file interpolation drift and binds API and worker to the stack-owned evidence bucket without modifying the secret payload.
- Docker Compose `v5.3.1` and Buildx `v0.34.1` are pinned as CloudFormation parameters with official SHA-256 checksums. Downloads are verified before atomic installation. The repaired host passed the image-build gate and API settings gate.
- PostgreSQL, Redis, object storage, and object-storage initialization passed their dependency checks. A command-transport issue in an earlier SSM wrapper was detected before migration execution; the wrapper was replaced with a restricted script-file transport and was not counted as evidence.
- The pre-migration PostgreSQL backup `step25b-pre-migration-20260713T182043Z.dump` was created with mode `0600`, size `858` bytes, and SHA-256 `e953e1a665296a0b2cc9af936cdf8c5ec7c3bc4572c4fbdada561f3661cbc53c`. Its attached 100 GiB EBS volume reports encryption enabled.
- The controlled Alembic migration completed at the single repository head `20260706_0004`. A later independent check confirmed the database current revision equals that head.
- API startup initially failed closed on two storage-policy defects: the application bucket name did not match the stack `EvidenceBucketName`, and the bucket had no verifiable policy. CloudFormation now supplies the stack bucket name and manages a non-public TLS-only bucket policy.
- The instance role's least-privilege encryption-read permission was corrected from the invalid `s3:GetBucketEncryption` action name to `s3:GetEncryptionConfiguration`. No broader S3 permission was granted.
- The evidence bucket reports all four public-access-block controls enabled, policy status `IsPublic=false`, and default `AES256` encryption. API startup storage-policy checks pass.
- The final local service gate passed: API health returned `status=ok` with the exact immutable revision; API and worker revisions match; both containers use the stack evidence bucket; the worker and proxy are running; and `/var/lib/elara-bootstrap-complete` is present.
- The active stack reached `UPDATE_COMPLETE` after each reviewed change set. The final IAM-only change modified the instance role without host replacement.

### Infrastructure Blocker

The required credential-free HTTPS smoke gate failed before any authenticated request because `https://api.elara.io/health` could not be resolved (`reason=dns_name_not_found`). A bounded Route 53 ownership check found no `elara.io` hosted zone in the authorized AWS account, so there is no in-scope DNS record that can be repaired from this stack without additional domain-provider authority. The Vercel web origin was identified but the gate stops on the API origin failure.

Per Step 25B's fail-closed rule, this is not first-shippable-milestone approval and not public-launch approval.

### Not Attempted After Blocker

- Public API and Vercel smoke completion.
- Application rollback rehearsal.
- Firebase sign-in and session-cookie validation.
- Redis restart, SSE reconnect/replay, retry, and dead-job validation.
- Celery queue execution and worker-failure recovery.
- Private signed export and cross-user denial validation.
- Brave, DeepSeek, Sentry, and redacted tracing validation.
- Approved public/synthetic live claim and durable citation-audited report generation.

## 2026-07-13 Side-Project Scope Update

Status: Backend runtime healthy; browser-reachable HTTPS remains the immediate demo blocker.

- A Route 53 hosted zone for `elara.io` and an `api` A record now exist in the current AWS account.
- Public `.io` delegation still points to the former nameservers, so the new Route 53 record is not authoritative on the public internet and `api.elara.io` still does not resolve.
- The owner does not want to use the external registrar. The preferred AWS-only demo path is therefore a CloudFront distribution using its default `*.cloudfront.net` HTTPS hostname in front of an explicit EC2 HTTP origin listener.
- The former application rollback, Redis restart/SSE recovery, queue recovery, exhaustive provider/tracing, signed-export denial, and formal release-audit list is now optional follow-up work under `project-context/DEMO_SCOPE.md`.
- The immediate success target is Firebase sign-in plus one approved claim reaching a durable citation-audited report through Vercel and the AWS HTTPS API.
