# Elara.ai

## Evidence-first automated verification

**Role:** Sole contributor - product strategy, UX, architecture, implementation, testing, deployment, and documentation  
**Timeline:** June 2026 - August 2026  
**Status:** Feature-complete and owner-validated for the personal hosted-demo scope  
**Project type:** Personal, owner-controlled, low-traffic demonstration  
**Live demo:** https://elara-ai-web.vercel.app/

Elara.ai is an evidence-management and automated-verification platform that evaluates a submitted claim, quotation, article, or source document against timestamped evidence. It preserves the sources, exact passages, snapshots, calculations, methodology versions, and provenance needed to reproduce a report.

Elara does not attempt to identify an absolute or permanent truth. It is not a lie detector and does not assign permanent credibility scores to people, organizations, or publications. Its output is an evidence assessment for one submitted item at a specific retrieval time.

## Executive summary

The central engineering question behind Elara was: how can an AI-assisted research system use language models without allowing the model to become the final authority?

Elara answers that question by separating language understanding from deterministic control. DeepSeek performs structured language tasks such as claim decomposition, research planning, semantic evidence classification, report synthesis, and citation-entailment assistance. Deterministic Python services own URL safety, canonicalization, source deduplication, scoring formulas, Decimal arithmetic, dependency multipliers, label thresholds, citation-presence checks, and the final completion gate.

A report cannot be published merely because a model produced fluent text. Elara requires durable evidence artifacts and a successful citation audit before a verification run can transition to `COMPLETED`.

## The problem

Automated research systems face several linked problems:

- A fluent answer can hide weak or missing evidence.
- Multiple articles can appear independent while repeating the same original report.
- Quotations, statistics, attributions, and contextual claims require different validation methods.
- Internet content is untrusted and can contain prompt injection, hostile redirects, oversized responses, or unsafe network targets.
- A model-generated number is not a reproducible numerical audit.
- Missing evidence must remain different from evidence of falsehood.
- Users need to inspect exact passages and understand why a report reached its conclusion.

The product goal was therefore not to build another answer generator. It was to build a controlled evidence workflow that makes every important conclusion inspectable and reproducible.

## Who Elara is for

Elara is designed for evidence-sensitive research work where the reader needs to inspect how a conclusion was reached. Representative users include independent researchers, journalists, analysts, policy reviewers, and technical evaluators reviewing a specific claim or document. It is not intended to replace editorial judgment, subject-matter expertise, or human fact-checking.

The core job to be done is:

> Given one claim, quotation, article, or document, assemble the strongest accessible evidence on both sides and return an assessment that can be traced from verdict to source snapshot.

The project defined success through five observable behaviors:

- every material conclusion resolves to an atomic claim and accepted evidence;
- every factual report sentence resolves to an exact stored passage;
- missing or inaccessible evidence remains distinct from contradiction;
- scoring and numerical work can be reproduced without asking a model to repeat its reasoning;
- incomplete evidence or citation coverage prevents publication rather than producing a polished but unsafe answer.

## The solution

Elara accepts the exact submitted claim and creates a durable verification run. A Celery worker executes a controlled LangGraph workflow that decomposes the input into atomic claims, plans neutral and contradiction-oriented research, retrieves public evidence securely, extracts traceable passages, analyzes source dependencies, classifies evidence, calculates scores, audits numbers, synthesizes a report, and verifies every factual sentence against its cited passage.

The final report presents:

- an evidence-bounded verdict;
- atomic claims with individual support, confidence, importance, and context;
- supporting and contradicting evidence side by side;
- exact source passages and retrieval metadata;
- source-dependency and provenance relationships;
- deterministic calculations and numerical audits;
- limitations, inaccessible sources, and unresolved questions;
- the evidence-reviewed timestamp;
- methodology and version information.

## How Elara works end to end

1. **Input and validation:** The user submits a claim and selects Quick, Standard, or Deep research breadth. Zod validates the browser form and FastAPI remains the final validation authority.
2. **Authentication and authorization:** Firebase Authentication provides user identity. FastAPI verifies the Firebase token or protected session and authorizes every run-scoped resource.
3. **Durable run creation:** FastAPI creates the PostgreSQL run and initial public event before enqueuing asynchronous work.
4. **Queueing and progress:** Celery executes the verification. Redis provides transient locks, queues, and progress streams while PostgreSQL remains authoritative.
5. **Intake:** The worker normalizes the input and identifies entities, speakers, dates, metrics, ambiguities, opinions, predictions, and fact-checkable statements.
6. **Decomposition:** Complex statements become weighted atomic claims while original text spans are preserved.
7. **Research planning:** Elara generates primary-source, supporting, contradicting, contextual, attribution, and definition-oriented queries without assuming the claim is true.
8. **Discovery:** Brave Search results are canonicalized, deduplicated, ranked, and selected with source diversity and independent coverage in mind.
9. **Secure retrieval:** The fetcher accepts only approved HTTP and HTTPS targets, blocks private and reserved networks, revalidates redirects and DNS, enforces response limits, and never forwards user credentials.
10. **Extraction:** Elara uses httpx and Trafilatura first, Beautiful Soup as a fallback, Playwright only when necessary, and PyMuPDF for page-aware PDF extraction.
11. **Passages and provenance:** Extracted text is segmented into traceable passages. The system records source snapshots and detects citations, syndication, repeated quotations, shared statistics, and likely derivation.
12. **Evidence classification:** DeepSeek evaluates the semantic relationship between a passage and an atomic claim. Deterministic rejection gates discard low-relevance, low-certainty, mismatched, or unlocatable evidence.
13. **Deterministic scoring:** Python calculates evidence quality, supporting and contradicting weights, source independence, confidence, quote fidelity, context completeness, and article-level results.
14. **Numerical audit:** Python `Decimal` validates percentages, ratios, totals, units, denominators, comparisons, and reporting periods. Calculation inputs and results are stored durably.
15. **Synthesis:** DeepSeek drafts a report using approved evidence only and must include credible contradiction, limitations, unresolved material, and the evidence timestamp.
16. **Citation audit:** Every factual sentence is checked for citation presence and passage support. Unsupported sentences trigger bounded revision or safe failure.
17. **Publication and presentation:** Only a durable, citation-audited report can become complete. The browser receives public progress over SSE and renders the report workspace from versioned API records.

## Representative end-to-end walkthrough

The portfolio screenshots use a privacy-safe representative dataset rather than a live private run. Its URLs use `example.org`, and the case exists to demonstrate the report contract and interface without exposing a user's account or retrieved evidence.

The submitted item states that a proposed transit budget increases total funding, adds more frequent weekend rail service on core lines, and relies primarily on sales-tax revenue.

1. **Decomposition:** Elara separates the submission into three atomic claims: total funding increased, core-line weekend service will run at least every 20 minutes, and sales-tax revenue is the primary funding source.
2. **Evidence collection:** The representative record stores an official budget passage from page 14, a funding passage from page 22, and an independent regional-board record from agenda item 7.
3. **Classification:** The budget strongly supports the funding and service claims. The board record introduces a material limitation: the proposed sales-tax measure remained pending final approval at the evidence cutoff.
4. **Deterministic calculation:** The first two claims receive strong support. For the funding claim, stored supporting and contradicting weights are 66 and 34, producing 66 percent evidence support.
5. **Synthesis:** The report uses the bounded verdict `Supported with limitations` instead of hiding the unresolved approval status.
6. **Citation audit:** Four representative factual sentences are connected to exact stored passages and marked citation-verified before the preview run is shown as `COMPLETED`.

The resulting trace is inspectable in both directions:

```text
verdict -> atomic claim -> calculation -> evidence item -> exact passage -> source snapshot
```

This walkthrough demonstrates the product contract and UI behavior. It is not presented as an independently reviewed accuracy benchmark or as evidence about a real transit authority.

## Worked deterministic scoring example

Elara calculates evidence scores outside the language model. For each accepted evidence item:

```text
quality q_i = 0.25R + 0.20D + 0.20A + 0.15T + 0.10F + 0.10X
adjusted weight w_i = q_i * dependency multiplier
support P = sum(max(stance_i, 0) * w_i)
contradiction N = sum(max(-stance_i, 0) * w_i)
evidence support = 100 * P / (P + N)
```

In the representative funding claim, `P = 66` and `N = 34`, so evidence support is `66%`. That number does not by itself force an unqualified positive label. The pending approval record, context completeness, confidence gates, and essential-claim rules remain visible, which is why the report uses `Supported with limitations`.

Dependency analysis also prevents duplicated reporting from inflating support. A high-quality primary record can retain a multiplier of `1.0`; a derivative item receives a lower multiplier before it contributes to `P` or `N`.

## System architecture

### Frontend

The frontend is built with Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui-style components, React Hook Form, and Zod. TanStack Query owns server state such as runs, reports, evidence, graphs, history, and exports. Zustand is limited to transient interface state such as selected claims, filters, drawer state, and panel layout.

React Flow powers the source-dependency graph. Recharts visualizes score roles, evidence balance, confidence components, research coverage, and numerical audit records. The browser never recomputes final scores.

### Backend API

FastAPI is the privileged boundary. It performs authentication, authorization, validation, usage limits, durable run creation, report and source access, upload validation, export creation, Celery enqueueing, and Server-Sent Events.

Pydantic provides typed contracts. SQLAlchemy and Alembic manage the PostgreSQL data model and migrations. Protected snapshots and exports use short-lived, owner-scoped access.

### Verification worker

Celery runs the asynchronous workflow. LangGraph organizes the controlled stages. All DeepSeek calls are routed through a server-side `DeepSeekClient` with structured Pydantic outputs, bounded timeouts, redacted operational errors, version metadata, and token-use tracking.

The worker checks cancellation before expensive work, records typed recoverable failures, uses per-run locks, and applies bounded retries only to explicitly transient failures.

### Retrieval and extraction

Brave Search supplies discovery. httpx performs controlled network access. Trafilatura and Beautiful Soup extract ordinary pages, Playwright is a restricted fallback for important client-rendered sources, and PyMuPDF extracts PDFs with page positions. Exact source bytes and content hashes support reproducibility.

### Persistence

PostgreSQL with pgvector stores durable application truth: verification runs, atomic claims, search queries, sources, immutable snapshots, passages, evidence items, provenance relationships, calculations, events, reports, citations, methodology versions, feedback, and exports.

Redis is intentionally transient. It supports Celery queues, per-run locks, caching, rate limits, and progress streams. Private S3-compatible storage holds uploads, permitted snapshots, and exports.

### Deployment

Elara was completed as a low-cost personal demo. The frontend runs on Vercel. The Full Mode backend stack uses a single AWS EC2 host, private S3 storage, a browser-facing HTTPS API, and server-side credentials. The topology intentionally excludes Kubernetes, autoscaling, multi-AZ infrastructure, and formal public-service operations.

## Technology stack

### Languages

- TypeScript and TSX
- Python 3.12+
- SQL
- HTML and CSS
- YAML for CI and infrastructure configuration

### Frontend tools

- Next.js App Router
- React
- Tailwind CSS
- React Hook Form
- Zod
- TanStack Query
- Zustand
- React Flow
- Recharts
- Lucide React
- Firebase Web SDK

### Backend and worker tools

- FastAPI
- Pydantic and Pydantic Settings
- SQLAlchemy and Alembic
- Uvicorn
- Celery
- Redis
- LangGraph
- DeepSeek API
- Brave Search
- httpx
- Trafilatura
- Beautiful Soup
- Playwright
- PyMuPDF
- Python Decimal

### Data, infrastructure, and operations

- PostgreSQL
- pgvector
- Redis
- private S3-compatible object storage
- Docker and Docker Compose
- Vercel
- AWS EC2 and S3
- GitHub Actions
- Sentry
- LangSmith-compatible tracing

## Security and trust boundaries

Security was part of the architecture rather than an afterthought.

- The browser never receives DeepSeek, Brave, PostgreSQL, Redis, object-storage, Firebase Admin, Sentry auth, or tracing credentials.
- Retrieved content is treated as untrusted evidence and cannot alter workflow policy.
- URL checks block localhost, private addresses, reserved ranges, link-local ranges, cloud metadata targets, unsupported ports, and unsafe redirect destinations.
- Redirects are bounded and revalidated.
- Response size, content type, and request duration are limited.
- Uploaded files are bounded, signature-checked, stored outside executable paths, and never executed.
- Every run, source, snapshot, citation, export, share, and feedback route is owner- or recipient-authorized.
- Logs avoid tokens, passwords, private uploads, raw prompts, and provider response bodies.
- PostgreSQL records are authoritative even when Redis data expires.
- Reports fail closed when evidence, structured output, or citation requirements are incomplete.

## Testing and verification

The repository contains 462 named tests across 71 test files:

- 120 API tests across 25 files;
- 238 worker tests across 21 files;
- 97 frontend tests across 22 files;
- 6 evaluation tests across 2 files;
- 1 deterministic full-stack acceptance test.

The inspected repository also contains 263 Python, TypeScript, TSX, and MJS source files, approximately 43,653 lines across those files, and 76 commits in the June-August 2026 development history.

Testing covers:

- Firebase authentication and API authorization;
- cross-user and recipient-share boundaries;
- SSRF, redirect, DNS, and response-size controls;
- upload type, signature, size, and ownership validation;
- Celery enqueueing, retry behavior, locks, cancellation, redelivery, and idempotency;
- SSE reconnect and terminal-status behavior;
- DeepSeek schema validation, malformed responses, redacted errors, and timeouts;
- claim decomposition and research-plan normalization;
- adaptive search policy and query provenance;
- extraction, passage retrieval, source ranking, and inaccessible-source handling;
- source provenance and dependency multipliers;
- deterministic scoring formulas and Decimal numerical audits;
- citation-audit rejection and fail-closed completion;
- report, graph, history, feedback, export, and deletion behavior;
- Alembic migration integrity;
- deterministic provider-free full-stack acceptance.

GitHub Actions adds secret scanning, npm and Python dependency audits, Trivy vulnerability and misconfiguration scanning, linting, type checks, frontend builds, API and worker suites, evaluation smoke tests, container builds, migration checks, full-stack acceptance, and targeted security regressions.

### Validation record and evidence boundary

Elara uses three different kinds of verification and does not treat them as interchangeable:

| Layer | What is established | Boundary |
|---|---|---|
| Repository gates | 462 named tests, deterministic full-stack acceptance, builds, migrations, security regressions, and container checks | Primarily deterministic, synthetic, and provider-free evidence |
| Hosted-demo validation | The sole contributor confirmed the owner-controlled path from Firebase sign-in through queueing, Celery execution, durable completion, citation-audited report retrieval, and refresh | Manual owner validation, not an independent external audit |
| Methodology evaluation | Offline graders and draft dataset splits exist for verdict, evidence, citation, extraction, attribution, clustering, calibration, latency, and cost | Candidate annotations remain pending human approval and are not an approved benchmark |

The hosted-demo success bar is intentionally narrow: the browser-facing services must be reachable over HTTPS, an approved tester must be able to sign in, one approved public or synthetic claim must complete through Celery, progress must recover after an SSE reconnect, the completed report must remain durable after refresh, and private credentials and service ports must remain unexposed.

No shareable hosted run ID or third-party validation certificate is claimed in this case study. The validation statement is therefore limited to owner-confirmed demo readiness plus the reproducible repository gates above.

## Measured engineering outcomes

The project retained useful diagnostic measurements and implemented the latency remediation, but it does not contain a completed controlled post-change performance benchmark. The case study therefore separates the measured baseline, the implemented configuration, acceptance targets, and verified behavior.

| Area | Measured baseline | Implemented configuration | Post-fix evidence and claim boundary |
|---|---|---|---|
| Citation-audit reliability | One Standard run failed after 8 minutes 51 seconds despite HTTP 200 because typed output conversion failed | Failure subtypes, privacy-safe diagnostics, bounded sequential replay, optional pair splitting, exact coverage checks, and fail-closed persistence | Recovery behavior is tested; no fleet-wide failure-rate reduction is claimed |
| Stage latency | One run spent 218.9 seconds in model-backed classification and 193.1 seconds in citation auditing; scoring took 0.09 seconds and numerical audit 0.06 seconds | Classification batches were tuned from 4 to 2 to 1 task; citation batches from 4 to 2 pairs; concurrency is capped at 2 and schema attempts at 2 per batch | The repository does not record a completed three-run post-fix median. The controlled-live acceptance targets are below 90 seconds for classification and below 60 seconds for citation audit; these are targets, not achieved measurements |
| Search request envelope | Previous maxima were 24, 60, and 120 queries for Quick, Standard, and Deep | First-phase targets became 8, 18, and 36, with a deterministic second phase only when coverage is inadequate | This is a 66.7%, 70%, and 70% first-phase policy reduction, not guaranteed realized cost savings |

### Resolved engineering failure modes

| Problem found | Fix applied | Verification retained |
|---|---|---|
| Production transport tests stopped at release-revision validation instead of reaching the insecure Redis, Celery, or S3 setting they claimed to test | Created a valid production baseline and overrode only the transport under test | The intended validators are reached, while missing and placeholder release revisions remain independently covered |
| Alembic migration discovery depended on the caller's working directory | Resolved migration and API import paths from `apps/api/alembic.ini` | Single-head and upgrade checks pass from both repository-root and API contexts |
| Active legal hold returned a storage-style `503` instead of a deterministic conflict | Normalized UTC-aware times and evaluated the hold before state mutation or object cleanup | Active hold returns `409`; report, exports, snapshots, and citations remain untouched; expired holds follow the normal workflow |
| Legacy `visibility="public"` was treated by a stale test as cross-user authorization | Kept access owner- or recipient-specific with explicit scope, expiry, and revocation | Unshared, expired, revoked, or wrong-scope access returns a non-disclosing `404` |
| Local MinIO assumptions did not match private AWS S3 endpoint and addressing behavior | Separated endpoint, secure transport, internal service discovery, and path-style configuration | Regional AWS S3 is covered with HTTPS and forced path style disabled |
| A retryable retrieval timeout escaped the typed retry boundary and became a generic worker failure | Converted only retryable `FetchError` values to the safe typed fetch-failure path used by bounded Celery retry behavior | The focused retrieval and task regression suite passed 37 tests; a successful hosted end-to-end run after this repair remains unproven |

The important outcome is architectural and operational: expensive model and provider work is now measurable at its real boundary; deterministic scoring remains fast and reproducible; failures reach the intended security, governance, authorization, migration, storage, and retry boundaries; and incomplete evidence still cannot produce a completed report.

## Major engineering challenges

### 1. Structured AI responses failed after HTTP success

A diagnosed Standard run failed after 8 minutes and 51 seconds even though DeepSeek returned HTTP 200. The failure occurred because a citation-audit response could not be converted into the required typed structure.

The original error category combined several distinct problems: invalid HTTP-body JSON, a malformed choices envelope, missing message content, invalid content JSON, usage-metadata validation, and output-schema failure. This made operational diagnosis too coarse.

The remediation introduced privacy-safe failure subtypes, separated transient provider-body failures from deterministic schema-contract failures, and added a bounded local recovery ladder. A failed two-pair citation batch can be replayed sequentially and, when appropriate, split into one-pair calls. Partial audit results are not persisted. Exact coverage and the deterministic citation guard must still succeed.

**Lesson:** A successful HTTP request is not the same as a valid, safe, or complete AI result.

### 2. Model latency was incorrectly perceived as scoring latency

One measured run spent 218.9 seconds in model-backed evidence classification and 193.1 seconds in citation auditing. Deterministic scoring took 0.09 seconds and the numerical audit took 0.06 seconds.

The previous UI grouped classification, scoring, and numerical work under one label, making the arithmetic appear slow. Elara introduced smaller structured contracts, bounded batch execution, limited concurrency, deterministic result merging, exact coverage checks, and clearer progress substages.

**Lesson:** Instrument stage boundaries before optimizing; the visible symptom may point at the wrong subsystem.

### 3. Search cost had to be reduced without weakening evidence coverage

The original planner could execute up to 24, 60, or 120 Brave queries for Quick, Standard, and Deep research. A simple successful report did not always need that request volume.

The final adaptive strategy uses first-phase targets of 8, 18, and 36 queries. Python first reserves mandatory primary and contradiction paths for every fact-checkable claim, plus required attribution coverage. A deterministic discovery-quality gate opens a bounded second phase only when candidate count, domain diversity, or required coverage remains insufficient.

Planned, executed, reserved, cached, and skipped queries remain durable for auditability.

**Lesson:** Provider-cost optimization should change when requests occur, not silently reduce required research coverage.

### 4. Quality gates sometimes tested the wrong failure boundary

Several API tests intended to prove rejection of insecure production transports stopped earlier on an unrelated release-revision validator. The system still failed closed, but the tests did not exercise the boundary named in their descriptions.

The fixtures were corrected to start from a valid secure baseline and override only the transport under test. Related quality work made Alembic migration discovery independent of the caller's working directory, normalized legal-hold time comparisons to return a deterministic conflict before mutation, and aligned visibility tests with recipient-specific authorization.

**Lesson:** A passing fail-closed test is insufficient if it fails for the wrong reason.

### 5. Deployment exposed storage and container differences

Moving from local MinIO assumptions to private AWS S3 required explicit endpoint behavior, secure transport checks, and separation between internal service discovery and path-style storage configuration. Container work also surfaced runtime file-permission and dependency-security issues.

The deployment was simplified around a single owner-controlled EC2 host, Vercel frontend, HTTPS API, private S3 bucket, hardened containers, and reproducible CI gates.

**Lesson:** A low-traffic demo still benefits from explicit secret ownership, durable evidence storage, and deterministic deployment checks.

## What makes Elara portfolio-worthy

Elara's strongest differentiator is not the number of technologies in the stack. It is the system design around evidence integrity:

- model-assisted interpretation with deterministic final control;
- durable, reproducible evidence and citation records;
- atomic-claim analysis rather than one vague document score;
- supporting and contradicting evidence shown together;
- provenance analysis that discounts repeated reporting;
- secure retrieval of hostile internet content;
- exact-passage citation inspection;
- deterministic numerical and scoring audits;
- explicit insufficient-evidence and limitation behavior;
- fail-closed report publication;
- test coverage across UI, API, worker, security, evaluation, migrations, and full-stack behavior.

## Current limitations and non-goals

- **No independent quality benchmark yet:** the evaluation harness exists, but the candidate annotations and thresholds remain pending human approval.
- **Representative screenshots are not live evidence:** the transit example is privacy-safe preview data using placeholder domains.
- **Public evidence can be incomplete:** paywalls, robots restrictions, deleted pages, inaccessible PDFs, and unsupported formats can limit coverage; Elara surfaces those gaps rather than inferring around them.
- **Provider behavior varies:** Brave availability, DeepSeek latency, website changes, and network conditions affect run time. The demo does not claim a latency service-level objective.
- **The hosted topology favors simplicity:** one EC2 host means manual recovery and no high-availability guarantee. This is intentional for an owner-controlled personal demo.
- **The system is not independently audited or production hardened:** security controls are tested, but the project does not claim public-launch certification or enterprise operations.
- **Assessments are time-bounded:** new evidence, corrections, changed pages, or better sources can change a result.
- **Elara is not a truth or credibility engine:** it evaluates one submitted item against evidence available at a recorded time.

## Personal contribution

Elara is a personal project with one contributor. I defined the product boundary, selected the architecture, designed the evidence and provenance model, built the Next.js interface, implemented the FastAPI boundary and SQLAlchemy data model, developed the Celery and LangGraph workflow, integrated DeepSeek and Brave Search, implemented secure retrieval and deterministic scoring, wrote the test and evaluation infrastructure, configured CI and the hosted demo, diagnosed measured failures, and produced the documentation and portfolio package.

The frameworks and external services listed in the technology stack provide infrastructure and capabilities; product decisions, integration work, implementation, verification, deployment, and project ownership were mine.

## Outcome

By August 2026, Elara was feature-complete and owner-validated for its personal hosted-demo scope. The finished project includes a responsive Next.js verification and report interface, authenticated FastAPI boundary, durable PostgreSQL data model, asynchronous Celery/LangGraph workflow, DeepSeek language integration, Brave-powered discovery, secure retrieval and extraction, provenance analysis, deterministic scoring and numerical audits, citation-gated report completion, reusable demo reports, and a low-cost Vercel plus AWS deployment.

The project demonstrates full-stack engineering, AI-system design, distributed workflow control, evidence modeling, security boundaries, deterministic evaluation, testing strategy, observability, and deployment tradeoff reasoning in one coherent product.

## Interview talking points

1. Why Elara is an evidence platform rather than a truth engine.
2. How DeepSeek responsibilities are separated from deterministic Python controls.
3. Why PostgreSQL is authoritative and Redis is transient.
4. How a report becomes eligible for `COMPLETED`.
5. How source dependence prevents repeated reporting from looking independent.
6. How the URL guard reduces SSRF and redirect risk.
7. How the citation-audit incident changed error taxonomy and recovery.
8. How measured latency led to batching and better UI stage labels.
9. How adaptive Brave Search preserves mandatory coverage while reducing ordinary request volume.
10. Why the deployment intentionally favors a simple personal-demo topology over enterprise infrastructure.

## Short portfolio-card version

Elara.ai is an evidence-management and automated-verification platform that evaluates claims against timestamped sources. Built by one contributor from June through August 2026, it combines a Next.js report workspace, FastAPI authorization boundary, PostgreSQL evidence model, asynchronous Celery/LangGraph workflow, DeepSeek-assisted research, secure web retrieval, deterministic scoring, provenance analysis, and fail-closed citation auditing. The project is feature-complete and owner-validated for a low-traffic personal demo deployed using Vercel plus AWS; independent methodology calibration remains future work.
