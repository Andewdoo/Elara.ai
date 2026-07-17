# Step 25C Hosted-Demo Validation Evidence

Date: 2026-07-14

Status: **Blocked before Firebase authentication and the live Full Mode case.**

This record follows the current side-project scope in `project-context/DEMO_SCOPE.md`. It is not a production-release audit.

## Scope and prerequisites checked

- The current browser-control session is available but has no open tab or authenticated Firebase session.
- The current runner has no supplied stable Vercel URL, CloudFront API URL, or expected non-local release revision with which to begin the Step 25C gate.
- The latest related sanitized deployment evidence (`STAGING_VALIDATION_25B_EVIDENCE.md`, 2026-07-13) records that the private runtime was healthy at immutable revision `1a9a1f97750c0b5081e2de71436e428473eb00ea`, but public HTTPS validation had not completed. The AWS-only CloudFront HTTPS path remained the required next entry condition.

## Sanitized result

| Required Step 25C proof | Result | Reason |
| --- | --- | --- |
| Stable Vercel frontend and CloudFront API URLs | Not available | No configured non-secret public origins were supplied to this runner. |
| Approved Firebase demo-account sign-in and valid API session | Not attempted | There is no open signed-in browser session or approved account authentication material in this task context. |
| Approved public or synthetic claim through Celery, synthesis, citation audit, and durable `COMPLETED` report | Not attempted | It depends on the HTTPS origin and authenticated session gates above. |
| Browser refresh or SSE reconnect with PostgreSQL report reload | Not attempted | No completed hosted run exists in this validation session. |
| API/worker revision match and non-exposure of private ports/credentials | Not revalidated | The historical 25B record reports a matching private-runtime revision and non-public services, but this cannot prove the browser-facing path. |

## Remaining demo limitation and handoff

The hosted demo is **not yet operational**. Resume exactly once an authorized operator provides the stable Vercel and CloudFront URLs, starts the EC2 demo host if it is stopped, confirms the selected API and worker revision, and signs in to the approved Firebase demo account in the in-app browser. Then run one reviewed public or synthetic claim, retain only sanitized status/revision/URL evidence, refresh or reconnect SSE to prove PostgreSQL reload, and stop the EC2 host after the demo if it is no longer needed.

The normal start/stop procedure remains `project-context/operations/DEPLOYMENT.md`: start the single EC2 host, wait for health, use the configured Vercel-to-CloudFront HTTPS path, and stop the host between demos when appropriate. Do not expose private service ports or server credentials while completing the handoff.

## 2026-07-14 authorized continuation

Status: **Blocked before CloudFront-output lookup and host start.**

- One read-only AWS identity check was attempted through the approved external-access path; it did not establish an AWS identity. Raw AWS output, account identifiers, and credential material were not printed or recorded.
- Without an authorized AWS identity, this runner cannot retrieve the non-secret CloudFormation `CloudFrontDomainName`, start or inspect the single EC2 host, or run the required public HTTPS smoke. No infrastructure, Vercel, Firebase, provider, database, or application configuration was changed.

Required handoff: make the existing approved AWS credential or role-assumption path available to this session, or supply the already-verified non-secret Vercel URL, CloudFront URL, and expected revision from an authorized operator. After that, sign in to the approved Firebase account in the browser before the authenticated demo case begins.

## 2026-07-14 authenticated-session diagnosis and repair

Status: **Blocked pending deployment of the tested repair; hosted demo not operational.**

### Sanitized evidence

- Stable frontend: `https://elara-ai-web.vercel.app/verify`.
- Browser-facing API: `https://d2dbv8xhityejq.cloudfront.net`; its `/health` response was healthy at deployed revision `1a9a1f97750c0b5081e2de71436e428473eb00ea`.
- The single EC2 host `i-0448ad7f332067fd5` was running. Its Compose services (API, worker, PostgreSQL/pgvector, Redis, private object storage, and Caddy) were running; the host uses the existing CloudFront-to-Caddy HTTPS/HTTP boundary.
- Firebase Authentication itself succeeded in the browser: password sign-in, account lookup, and token exchange each returned HTTP 200. The configured Vercel hostname is an authorized Firebase domain, and the public browser key permits the required Firebase identity APIs.
- The subsequent `POST /v1/auth/session` returned HTTP 500. The following `DELETE /v1/auth/session` returned HTTP 204 and is only the frontend rollback, not a Firebase failure.
- Sanitized API logs attribute the 500 to SQLAlchemy mapper initialization: `User.verification_runs` had two possible foreign-key paths because `verification_runs.user_id` and `verification_runs.publication_reviewed_by` both reference `users`.
- Commit `aacc9c8` explicitly binds the ownership relationship to `VerificationRun.user_id` on both relationship ends. Focused auth/session tests passed: `2 passed`.

### Deployment blocker

- The checked-out host revision remains `1a9a1f97750c0b5081e2de71436e428473eb00ea`; it could not fetch the tested commit because its configured GitHub SSH transport returned `Permission denied (publickey)`.
- This was one bounded source-transport attempt. No credential was viewed, pasted, copied, or bypassed; no second fetch, checkout, image build, restart, or database change was attempted.

### Required handoff

Repair the host's approved read-only GitHub deploy-key transport, then fetch and deploy commit `aacc9c8` through the existing `/opt/elara/app` Compose procedure. Reconfirm API and worker revisions match before repeating Firebase sign-in. Only after that passes should the approved claim, Celery synthesis/citation-audit completion, PostgreSQL reload/SSE reconnect, and browser-exposure checks be run.

## 2026-07-14 in-app-browser continuation

Status: **Blocked by the current validation environment; hosted demo remains not operational.**

### Sanitized evidence

- Stable Vercel frontend: `https://elara-ai-web.vercel.app/verify` loaded successfully in the in-app browser. The rendered page reported Firebase Web configuration ready and stated that model, search, database, Redis, object-storage, Firebase Admin, Sentry authentication, and tracing credentials are not exposed to the browser.
- No approved Firebase demo-account session was present in the supplied browser. The sign-in dialog was reachable, but no account credentials or existing authenticated session were supplied, so no authentication attempt was made.
- A single credential-free browser request to the recorded CloudFront API health URL was blocked locally by the browser client before it reached the endpoint. Per the demo-validation instruction, it was not retried.
- The local checkout contains the tested auth-mapper repair at `aacc9c89f129b29d665dc998da2fa43f7929a1db` (`fix(api): disambiguate verification run owner relationship`). This does not establish that the API and worker deployed to the EC2 host use that revision.

### Required proof still unavailable

The current session cannot prove a valid FastAPI session, an approved claim's Celery path through synthesis and durable citation audit to `COMPLETED`, PostgreSQL reload after refresh or SSE reconnect, the deployed API/worker revision match, or the externally reachable API health response. It therefore cannot mark the hosted demo operational.

### Approved next handoff

Use an environment with authorized AWS/browser network access, start the single EC2 host if necessary, and confirm the deployed API and worker both use the selected revision (including the auth-mapper repair). Sign in to the approved Firebase demo account, run one reviewed public or synthetic claim, confirm `COMPLETED` only after citation audit, refresh or reconnect SSE to reload the report from PostgreSQL, and retain only sanitized status, URL, revision, and exposure evidence. Stop the EC2 host after the demo when it is no longer needed.

## 2026-07-14 authenticated Full Mode attempt

Status: **Blocked during the real Celery workflow; hosted demo remains not operational.**

### Sanitized evidence

- The approved Firebase demo account was signed in through the stable Vercel frontend, and FastAPI accepted the authenticated verification request. This proves a valid browser-to-API session for the submitted run.
- Approved public demo case: the WHO's 11 March 2020 characterization of COVID-19 as a pandemic.
- FastAPI durably created run `544bd765-4da4-47df-9ccc-ec9215bb4af8`; the browser connected to its SSE stream and received intake and planner progress events from the actual Celery path.
- The worker then reached the durable terminal `FAILED` state with the sanitized error: `Research planning returned invalid claim or objective references.` No retry was attempted.

### Result and remaining limitation

Because the worker failed before source discovery, synthesis, and citation audit, this attempt cannot prove a durable `COMPLETED` report, PostgreSQL report reload after refresh/SSE reconnect, or the deployed API/worker revision match. The browser UI continued to state that server credentials and private-service credentials are not exposed, but that client-side statement does not replace a deployed-service exposure review.

### Required handoff

Diagnose and deploy the research-planning failure on the same selected API/worker revision, then rerun one reviewed demo case once. Do not mark the demo operational until the real worker completes synthesis and durable citation audit, the report reloads from PostgreSQL after refresh or SSE reconnect, and the API/worker revision and private-service boundaries are confirmed with sanitized evidence.

## 2026-07-16 Prompt 11 authorized attempt

Status: **Blocked by the approved AWS access gate; hosted demo remains not operational.**

### Sanitized evidence

- The user explicitly authorized Prompt 11 deployment and hosted testing.
- The in-app browser visibly showed the approved Firebase demo account signed in at the stable Vercel frontend `https://elara-ai-web.vercel.app/verify`. No email or account identifier is recorded. FastAPI session validity was not revalidated because the AWS gate blocked first.
- The existing recorded CloudFront API URL is `https://d2dbv8xhityejq.cloudfront.net`; it was not revalidated in this attempt.
- Exact target revision: `258cd78be4abd16732807f47e8c4ee5992b2be30`. Its verified direct rollback parent is `deb5b92c96fdea89b487011ae166c8e5dfd2422f`; the parent-to-target diff contains no migration.
- One approved AWS CLI identity/access check returned sanitized `ACCESS=FAIL`. Per Prompt 11, it was not retried. No secrets or raw AWS identity data were printed.

### Results not established

The AWS gate failed before CloudFormation outputs or EC2 state could be inspected. Therefore EC2 running/stopped state, SSM access, CloudFront health/revision, API/worker revision match, claim enqueue, Celery chain, synthesis, citation audit, durable `COMPLETED`, refresh/SSE reload, browser credential inspection, and public/private port verification were not attempted or revalidated. These are untested results, not observed system failures.

No Vercel, AWS, Firebase, EC2, database, provider, or hosted-demo mutation occurred.

### Remaining handoff

Restore the existing approved AWS credential or role path to this session, confirm the EC2 state and start it if needed, deploy the API and worker together at `258cd78be4abd16732807f47e8c4ee5992b2be30`, then resume once with the already signed-in browser and one approved public or synthetic claim. The existing EC2 start/stop procedure remains `project-context/operations/DEPLOYMENT.md`.

## 2026-07-16 credential repair and delegated deployment attempt

Status: **Blocked by an AWS profile execution-environment mismatch; hosted demo remains not operational.**

- AWS CLI initially had no configured profiles; the sanitized diagnosis was `MISSING_CREDENTIALS`.
- Official browser-based `aws login --profile elara-demo` completed, and the main Codex session's sanitized STS access check returned `ACCESS=PASS`. No account ID, ARN, credential type or value, login URL, state token, or raw output is recorded.
- The signed-in Elara Firebase browser tab remained available.
- A sequential delegated deployment task was assigned with explicit profile `elara-demo` and region `us-east-1`. Its own sanitized AWS access gate returned `ACCESS=FAIL`, so it stopped immediately under Prompt 11 without calling CloudFormation, EC2, SSM, Compose, or health checks.
- The main session could use the approved profile, but the delegated runner could not consume it. This is an execution-environment access mismatch, not evidence of an Elara application failure.
- No AWS, Vercel, host, database, Firebase, provider, or local deployment mutation occurred. Creating and signing in to the local AWS profile was the only computer configuration change.

EC2 state and runtime revisions remain unverified. Begin a fresh Prompt 11 attempt only after the approved AWS profile is available to the deployment execution context; do not retry within this attempt.

## 2026-07-16 fresh escalated Prompt 11 attempt

Status: **Blocked by the first remote host revision probe; hosted demo remains not operational.**

- Requiring external execution with the explicit `elara-demo` profile resolved the prior execution-context AWS access issue.
- Sanitized gates passed: AWS access, CloudFormation lookup, EC2 status checks, and SSM connectivity. The existing EC2 host was running. Stable CloudFront API URL: `https://d2dbv8xhityejq.cloudfront.net`.
- The first SSM host revision probe reached the host but ended `Failed` with a nonzero result and stderr. Its safe classification is `OTHER_REMOTE_ERROR`; no cause is inferred. No raw error, command payload, identifier, environment value, credential, or private data is recorded.
- Per Prompt 11, no second host command, retry, deployment, or bypass was attempted. Deployment mutation: **NO**.

Target revision `258cd78be4abd16732807f47e8c4ee5992b2be30`, API/worker revision match, local/public health, FastAPI session, claim enqueue, Celery chain, synthesis, citation audit, durable `COMPLETED`, refresh/SSE reload, browser credential privacy, and private-port boundaries remain unverified in this attempt. EC2 final state: **running**.

An authorized operator must diagnose the sanitized SSM command failure outside this attempt, then begin a fresh Prompt 11 attempt. Do not retry within this attempt or invent the cause.

## 2026-07-16 fresh authorized Prompt 11 source-deployment attempt

Status: **Blocked by the configured host source transport before deployment; hosted demo remains not operational.**

### Approved prerequisites and sanitized deployment evidence

- The user explicitly authorized a fresh Prompt 11 deployment and hosted test and confirmed that the approved Firebase session and AWS host access were available.
- Approved AWS access, CloudFormation output lookup, both EC2 status checks, and SSM connectivity passed. The existing EC2 host was running and SSM was online.
- Stable frontend: `https://elara-ai-web.vercel.app/verify`. Stable CloudFront API: `https://d2dbv8xhityejq.cloudfront.net`.
- Exact deployment target: `258cd78be4abd16732807f47e8c4ee5992b2be30`. Paired rollback revision: `deb5b92c96fdea89b487011ae166c8e5dfd2422f`; no migration is required between them.
- The authoritative host readiness probe passed: the tracked checkout was clean at `aacc9c89f129b29d665dc998da2fa43f7929a1db`, `.env.private` was present, and the existing Compose application profile was ready.
- The target commit object was absent from the host. The single approved exact-target fetch was blocked by the configured source transport before checkout, environment, image, container, database, or service mutation. No fetch retry or guard bypass was attempted.
- Because deployment was not reached, rollback was unnecessary. The current running API/worker revisions and CloudFront `/health` revision were not revalidated and must not be inferred from the host checkout.

### Prompt 11 result matrix

| Required proof | Result | Sanitized evidence |
| --- | --- | --- |
| Firebase authentication | Not attempted | Deployment revision gate failed first. |
| FastAPI session | Not attempted | Deployment revision gate failed first. |
| Claim enqueue | Not attempted | No hosted claim was submitted. |
| Celery chain | Not attempted | No hosted claim was submitted. |
| Synthesis | Not attempted | No hosted claim was submitted. |
| Citation audit | Not attempted | No hosted claim was submitted. |
| Durable `COMPLETED` report and citations | Not attempted | No hosted claim was submitted. |
| Refresh or SSE reload from PostgreSQL | Not attempted | No completed hosted run exists for this attempt. |
| API/worker same immutable revision | **FAIL** | Target revision was not deployed; running container revisions were not reverified. |
| Browser credential privacy | Not revalidated | Browser testing did not begin. |
| Private PostgreSQL, Redis, Celery, and object-storage ports | Not revalidated | Deployment stopped before the exposure checks. |

### Remaining handoff and EC2 state

Repair the existing host's approved read-only source transport so it can fetch the exact target commit, then begin a new explicitly authorized Prompt 11 attempt. Deploy API and worker together, confirm both use `258cd78be4abd16732807f47e8c4ee5992b2be30` before submitting the approved claim, and continue through the minimum hosted-demo gate once. Do not weaken the source or revision guard.

The EC2 host was last verified **running** with both status checks passing; no stop command was issued. Use `project-context/operations/DEPLOYMENT.md` to start the host and wait for health before a demo, or stop the single host between demos when it is no longer needed.

No Vercel, AWS infrastructure, Firebase, EC2 application, database, provider, or hosted-demo mutation occurred in this attempt.

## 2026-07-16 authorized host source-transport repair attempt

Status: **Blocked before source-transport classification; hosted demo remains not operational.**

- The user explicitly authorized repair of the existing EC2 Git/deploy-key source transport and deployment of the immutable target after a safe repair.
- Approved AWS access and EC2/SSM readiness checks passed.
- One bounded SSM metadata/auth inspection was issued to classify only the configured remote transport, referenced key/config metadata, and authentication result without reading key content or printing raw host output. It ended non-successfully before a safe transport, key, or authentication classification was returned.
- This is recorded as `OTHER_REMOTE_ERROR`. No second inspection, deploy-key repair, GitHub change, fetch, checkout, Compose deployment, or credential mutation was attempted.

### Required handoff

Diagnose the sanitized SSM command-execution failure through the approved host-access path, then begin a fresh bounded source-transport repair attempt. Do not infer that a GitHub sign-in, deploy-key registration, or key replacement is required until the existing host configuration can be safely classified.

EC2 state was not changed in this attempt. No Vercel, AWS infrastructure, Firebase, EC2 application, database, provider, or hosted-demo mutation occurred.

## 2026-07-16 fresh SSM and source-transport diagnosis attempt

Status: **Blocked before AWS/SSM execution by a missing local approved AWS profile.**

- The user explicitly authorized a fresh diagnosis of the SSM command-execution path followed by a bounded source-transport inspection.
- The execution environment's sanitized AWS CLI profile list was empty, including the required `elara-demo` profile. The main session confirmed the same empty profile list.
- No AWS request, SSM command, Git transport inspection, host repair, deployment, credential mutation, or GitHub action was attempted.

### Required handoff

Restore the existing approved `elara-demo` AWS profile or role-assumption configuration to this Codex execution environment, then complete its approved sign-in. Do not paste credentials or create replacement cloud identities. Once `aws configure list-profiles` includes `elara-demo`, begin a fresh bounded SSM command-execution diagnosis.

No Vercel, AWS infrastructure, Firebase, EC2 application, database, provider, or hosted-demo mutation occurred in this attempt.

## 2026-07-16 approved GitHub CLI and paired-deployment continuation

Status: **Blocked before the host deployment command by AWS CloudShell environment startup; hosted demo remains not operational.**

### Approved preparation and sanitized evidence

- The user completed the approved GitHub CLI authorization. The local CLI was confirmed authorized and configured as Git's HTTPS credential helper; no token, device code, account identifier, or raw credential output was recorded.
- The immutable target `258cd78be4abd16732807f47e8c4ee5992b2be30` was safely published as the new non-default release branch `codex/prompt11-258cd78`, without force-pushing or changing the repository default branch. This makes the target advertised to the repaired host deploy-key transport. The paired rollback remains `deb5b92c96fdea89b487011ae166c8e5dfd2422f`; no migration is required.
- A single paired-deployment command was prepared to fetch the advertised target, detach-checkout the exact SHA, run the existing Compose application profile, and compare `ELARA_RELEASE_REVISION` in both `api` and `worker` containers before any claim. Its safe failure states are fetch, target, checkout, Compose, or revision mismatch; it does not roll back or change database schema automatically.
- Before that command could be submitted, the approved AWS CloudShell session expired. The one reconnect reached the AWS-managed environment-start state and remained at 99% without exposing a usable terminal. The second existing terminal showed the same state. No SSM command, EC2 checkout, Compose build/restart, database mutation, Vercel mutation, or hosted claim was performed in this continuation.

### Current Prompt 11 result matrix

| Required proof | Result | Sanitized evidence |
| --- | --- | --- |
| Firebase authentication | Not revalidated | Host same-revision gate has not completed. |
| FastAPI session | Not revalidated | Host same-revision gate has not completed. |
| Claim enqueue | Not attempted | No approved hosted claim was submitted. |
| Celery chain | Not attempted | No approved hosted claim was submitted. |
| Synthesis | Not attempted | No approved hosted claim was submitted. |
| Citation audit | Not attempted | No approved hosted claim was submitted. |
| Durable `COMPLETED` report and citations | Not attempted | No approved hosted claim was submitted. |
| Refresh or SSE reload from PostgreSQL | Not attempted | No completed hosted run exists for this continuation. |
| API/worker same immutable revision | Not established | The paired host deployment command was not submitted. |
| Browser credential privacy | Not revalidated | Hosted browser validation did not begin. |
| Private PostgreSQL, Redis, Celery, and object-storage ports | Not revalidated | Host deployment and exposure checks did not begin. |

### Remaining handoff and EC2 procedure

- Stable frontend: `https://elara-ai-web.vercel.app/verify`; stable CloudFront API: `https://d2dbv8xhityejq.cloudfront.net`.
- Resume once AWS CloudShell (or the already approved AWS command path) provides a working terminal. Submit the prepared paired deploy exactly once, require API and worker revisions to equal `258cd78be4abd16732807f47e8c4ee5992b2be30`, then revalidate the Firebase/FastAPI session and submit one approved public or synthetic claim.
- The EC2 host was last verified **running**. Follow `project-context/operations/DEPLOYMENT.md`: start the single existing EC2 host before a demo and wait for health; stop that same host after the demo when it is no longer needed. No stop command was issued in this continuation.
- Remaining demo limitation: the actual Full Mode case has not yet reached Celery synthesis, durable citation audit, `COMPLETED`, or PostgreSQL-backed refresh/SSE reload.
