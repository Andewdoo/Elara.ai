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
