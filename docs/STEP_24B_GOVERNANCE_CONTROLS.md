# Step 24B Governance Controls

## Implemented and enforced

- Any persisted atomic claim classified as an allegation holds the citation-audited run in `review_required`; only an authenticated `reviewer` or `admin` can approve, reject, or require revision. Redelivery cannot bypass a durable decision.
- Reports are private by default. Sharing uses an account-bound grant with an explicit `report`, `report_sources`, or `report_sources_exports` scope, a maximum seven-day expiry, and durable revocation. The legacy `public` visibility value grants no access.
- Correction and appeal decisions are reviewer-only, use a constrained transition set, and append immutable decision records. Accepted decisions require a public notice flag and may link a revised run.
- Deletion is soft, auditable, idempotent, and blocked by active legal/audit holds. It revokes legacy sharing and deletes exports before hiding the report.
- Unclaimed uploads have an expiry. Orphan snapshot cleanup excludes every referenced snapshot and repeats the completed-report guard immediately before deletion. Completed-report snapshots are never retention candidates.
- PDF extraction enforces page, expanded-text, object, table, and wall-clock budgets. Celery applies soft and hard task limits.
- Production/staging startup fails closed unless object storage blocks public access, reports a non-public bucket policy, and has the configured default server-side encryption. Uploads and snapshots request encryption and private cache controls.
- Telemetry removes exception values, messages, breadcrumbs, URLs, request bodies, cookies, prompts, uploads, evidence content, and credential-shaped values. Browser monitoring records only a generic failure plus an opaque framework digest.
- CI gates committed-secret scanning, JavaScript and Python dependency audits, and Trivy vulnerability/secret/misconfiguration scanning. Dependabot proposes bounded dependency updates.
- Worker admission has a default active-run ceiling, and upload, retry, feedback, export, and signed-URL issuance use fail-closed per-user action limits in staging/production. Forwarded client headers are ignored by the production API command until a trusted-proxy policy is approved.

## Awaiting human approval

The controls above intentionally use conservative fail-closed defaults. Public-launch approval still requires documented decisions for:

- the final definition and severity tiers of “high impact,” reviewer authority/quorum, escalation SLA, override rules, and disclosure wording;
- retention periods by artifact, jurisdiction, legal/audit hold ownership, deletion grace periods, and the user-facing meaning of deletion;
- allowable sharing audiences, whether exact evidence may be shared, default expiry/download rights, and already-issued signed-URL revocation semantics;
- correction/appeal standing, evidence requirements, SLAs, adjudicator independence, appeal levels, notifications, and correction visibility;
- tier quotas, burst/storage budgets, operator overrides, and the trusted-proxy allowlist/multi-hop policy;
- storage residency, KMS/operator access, audit logging, disaster recovery, approved container digests, and dependency exception/upgrade policy.

These unresolved decisions are public-launch blockers; they do not weaken the enforced private-by-default and publication-hold behavior.
