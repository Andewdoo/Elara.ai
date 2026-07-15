# Sub-Agent Optimization Prompts

Use sub-agent optimization prompts.md to assign the implementation in `sub-agent optimization.md` as small, sequential coding tasks. Each prompt is intentionally bounded so a sub-agent can make one coherent change, run focused checks, and hand off evidence without overlapping another agent's files.

## Controller protocol

Run the prompts in order. Do not run prompts that edit the same worker files concurrently. A later prompt may start only after the prior prompt's changes and test results have been reviewed.

For every sub-agent:

1. Work in `C:\Users\aliua\Elara.ai`.
2. Read the root `AGENTS.md` and the closest nested `AGENTS.md` for every file changed.
3. Query the existing Graphify graph first with a precise question and a 1,000-token budget. Run `reflect --if-stale`, use only exact graph-vocabulary tokens, and read the lessons before traversal.
4. Use the `elara-task-context` skill. Load only the assigned section of `project-context/sub-agent optimization.md`, `4.4 LangGraph Nodes`, and the directly relevant guidance section. Do not read the full main implementation plan or project PDFs.
5. Follow `project-context/DEMO_SCOPE.md`. This is an owner-controlled, low-traffic demo, not a production SaaS launch.
6. Keep the selected stack. Do not add providers, frameworks, queues, databases, or infrastructure services.
7. Keep DeepSeek and all provider/auth/database/Redis/storage credentials server-side. Do not add OpenAI APIs or environment variables.
8. Preserve PostgreSQL durable truth, Redis as transient transport, secure retrieval, deterministic scoring, exact evidence provenance, and durable citation audit before `COMPLETED`.
9. Preserve the user's dirty worktree. Inspect `git status --short` before editing and do not revert unrelated changes.
10. Use `apply_patch` for edits. Reuse installed dependencies and existing patterns.
11. Run the narrowest relevant tests first. Do not reinstall dependencies, rebuild all containers, or run repository-wide release gates unless a focused failure justifies expansion.
12. After source or project-guidance changes, run `.\.graphify-venv\Scripts\graphify.exe update .` from the repository root.
13. Never log, persist, or paste raw prompts, raw provider output, credentials, private source content, Firebase tokens, or private chain of thought.
14. If an environment or external service blocks progress, report the blocker once with the failed command/evidence and stop. Do not repeatedly retry.
15. Report changed files, focused verification, graph update status, remaining risk, and the exact next prompt number.

External mutation rule: prompts 1-10 authorize local code and test changes only. Prompt 11 may deploy or run a hosted claim only when the user has explicitly authorized that external action and the required credentials/session are already available. Otherwise it must stop with a deployment handoff checklist.

## Shared implementation decisions

All sub-agents must preserve these decisions unless focused evidence proves one is incompatible:

- Keep existing durable/downstream schemas where practical; add separate model-facing draft schemas and normalize them into current state types.
- Generate database-like identifiers deterministically in Python. Models may select only from explicit allowed identifiers.
- Derive redundant fields in Python instead of asking the model to repeat them.
- Validate exact task coverage with pure deterministic validators returning stable codes.
- Permit at most one structured-response regeneration and at most one stage-specific semantic correction.
- Deterministic contract failures are terminal for that run and are not blanket Celery-retryable.
- Provider timeouts, rate limits, and temporary unavailability retain the existing bounded retry policy.
- Keep the completion gate strict: durable report artifacts plus exact citation audit, then and only then `COMPLETED`.

## Prompt 1 — Characterize the planner failure

```text
You are implementing Prompt 1 of the Elara sub-agent optimization plan.

Goal:
Freeze the current INVALID_RESEARCH_PLAN behavior with focused, provider-free tests before changing production logic.

Read only:
- root and apps/worker AGENTS.md;
- project-context/DEMO_SCOPE.md;
- the incident, planner row, and Step 1 sections of project-context/sub-agent optimization.md;
- the 4.4 Planner slice from project-context/IMPLEMENTATION_PLAN.md;
- directly relevant planner schemas, prompt, workflow guard, and existing worker tests.

Required work:
1. Add table-driven planner fixtures that are Pydantic-valid but independently trigger: duplicate objective refs, unknown claim ref, missing/extra claim coverage, query limit, duplicate normalized query, missing primary path, missing contradiction path, missing attribution path, missing exact quote, unknown objective ref, and query/objective intent mismatch.
2. Add one valid control fixture.
3. Add a synthetic hosted-run-shaped case proving INVALID_RESEARCH_PLAN prevents ready_for_completion and persists a nonretryable durable failure through the verification task boundary.
4. Do not use real provider credentials or hosted run data.
5. Do not change production behavior in this prompt except a minimal test seam if strictly necessary and justified.

Verification:
- run the smallest relevant tests in apps/worker/tests/test_workflow.py, test_agent_schemas.py, and test_verification_task.py;
- report which current predicates are reproducible and any predicate that cannot be isolated.

Stop after the characterization tests pass. Hand off to Prompt 2.
```

## Prompt 2 — Add pure contract validators and stable diagnostics

```text
You are implementing Prompt 2 of the Elara sub-agent optimization plan.

Goal:
Replace the planner's combined Boolean with a pure validator that returns stable, sanitized violation codes.

Read only the Step 2 section of project-context/sub-agent optimization.md plus the planner workflow/schema files and tests characterized in Prompt 1.

Required work:
1. Add apps/worker/agents/validation.py unless an existing module is a clearly better local pattern.
2. Define an immutable AgentContractViolation with a stable code, safe field name, and primitive counts/identifiers only.
3. Implement validate_research_plan(state, output) returning every violation in deterministic order.
4. Use the exact PLAN_* taxonomy from the plan. Keep legacy duplicate/unknown reference checks because persisted or test input may still use the old schema.
5. Change planner failure events to include primary_violation, violation_count, repair_attempted=false, and a bounded stable-code summary. Do not include query text, claim text, provider output, or Pydantic error bodies.
6. Keep INVALID_RESEARCH_PLAN as the top-level compatibility code until Prompt 5 adds repair-exhaustion behavior.
7. Keep all validation pure and independently testable.

Verification:
- run the new validator tests and focused workflow/verification-task tests;
- prove multi-violation ordering is stable;
- prove logs/events contain no raw claim or query text.

Stop after the validator replaces the combined Boolean and all focused tests pass. Hand off to Prompt 3.
```

## Prompt 3 — Normalize planner drafts with deterministic references

```text
You are implementing Prompt 3 of the Elara sub-agent optimization plan.

Goal:
Prevent DeepSeek from generating objective foreign keys or redundant query intents while preserving existing persisted PlanningOutput contracts.

Read only the Step 3 section of project-context/sub-agent optimization.md, the current planning schemas/workflow, discovery pipeline consumers, persistence mappings, and directly relevant tests.

Required work:
1. Add model-facing PlanningDraftOutput, PlanningDraftObjectiveOutput, and PlanningDraftQueryOutput.
2. Nest draft queries under objectives. A draft query must not have objective_ref or intent.
3. Keep draft claim_ref as a selection from allowed_claim_refs and reject unknown values.
4. Implement a pure normalize_research_plan function that:
   - canonicalizes objective identity inputs;
   - creates an objective_ref using an obj- prefix and truncated SHA-256 digest plus deterministic collision handling;
   - derives query objective_ref and intent from the parent objective;
   - returns the existing PlanningOutput type;
   - produces the same output for the same draft and claim order.
5. Call DeepSeek with the draft schema, normalize in Python, then run the Prompt 2 validator.
6. Preserve discovery, search-query persistence, workflow state, and API contracts.
7. Do not introduce a database migration unless code inspection proves the existing persisted reference length/format cannot hold the deterministic value. If a migration is truly required, stop and report before creating it.

Verification:
- schema tests prove the model cannot supply objective_ref or query intent;
- normalization tests cover stability, collision handling, inherited intent, unknown claim, duplicate query, and complete coverage;
- discovery and workflow tests prove downstream compatibility;
- repeated normalization is idempotent.

Stop after provider-free focused tests pass. Hand off to Prompt 4.
```

## Prompt 4 — Align planner-v2 prompt and payload

```text
You are implementing Prompt 4 of the Elara sub-agent optimization plan.

Goal:
Make the planner instructions, JSON schema, payload, and deterministic validator describe one executable contract.

Read only the Step 4 section of project-context/sub-agent optimization.md, planning.py, the planner call site, prompt-version persistence, and focused tests.

Required work:
1. Bump the planner prompt version to planner-v2.
2. Send a JSON payload with claims, allowed_claim_refs, research_depth, max_query_count, required_intents_by_claim, requires_attribution_check, and exact_quote only when applicable.
3. Explicitly require primary and contradiction paths for every fact-checkable claim.
4. Explicitly require identifiers to be copied only from allowed_claim_refs.
5. Explain that query intent is inherited from its containing objective and is not returned separately.
6. State duplicate-query normalization and exact-short-quote requirements.
7. Keep the content-as-untrusted-evidence boundary and prohibit truth decisions, scoring, browsing, credentials, and private reasoning.
8. Ensure planner-v2 is recorded in model metadata and durable prompt_versions.

Verification:
- focused prompt/payload tests inspect the outbound structured call without invoking DeepSeek;
- a fake model response using the draft schema normalizes and passes the validator;
- existing prompt-version persistence tests are updated intentionally.

Stop after focused tests pass. Hand off to Prompt 5.
```

## Prompt 5 — Implement bounded structured and semantic repair

```text
You are implementing Prompt 5 of the Elara sub-agent optimization plan.

Goal:
Recover once from malformed structured output and once from a semantic planner-contract violation without creating an unbounded retry loop or exposing raw content.

Read only the Step 5 section of project-context/sub-agent optimization.md, DeepSeekClient, workflow _call/planner behavior, Celery retry mapping, telemetry helpers, and focused tests.

Required work:
1. Add an opt-in one-attempt structured-response regeneration in DeepSeekClient for invalid JSON or Pydantic schema output.
2. Reuse trusted messages and schema. Send only a sanitized failure instruction; do not persist or log the invalid response or detailed validation values.
3. Preserve timeout, low-temperature, model-role, DEEPSEEK_* configuration, and redacted provider telemetry.
4. Distinguish STRUCTURED_RESPONSE_INVALID from STRUCTURED_RESPONSE_REPAIR_EXHAUSTED in safe metadata/events.
5. Add one planner semantic corrective replan using allowed references and stable PLAN_* codes only.
6. Re-normalize and revalidate from scratch. A second semantic failure becomes nonretryable AGENT_CONTRACT_REPAIR_EXHAUSTED with safe counts.
7. Confirm deterministic contract errors do not trigger Celery provider retries. Existing transient provider/fetch retries must remain unchanged.
8. Record attempt counts without storing raw model output.

Verification:
- invalid JSON then valid;
- schema-invalid then valid;
- two schema-invalid responses terminal;
- semantically invalid then valid plan;
- two semantically invalid plans terminal;
- timeout/rate-limit behavior unchanged;
- captured logs/events contain no marker text placed only in the raw invalid response.

Stop after DeepSeek client, workflow, and verification-task tests pass. Hand off to Prompt 6.
```

## Prompt 6 — Harden intake and decomposition contracts

```text
You are implementing Prompt 6 of the Elara sub-agent optimization plan.

Goal:
Apply deterministic task context and identifier normalization to intake and decomposition.

Read only the Step 6 section of project-context/sub-agent optimization.md; the Intake and Decomposition slices of 4.4; current intake/decomposition prompts, schemas, workflow code, persistence consumers, and tests.

Required intake work:
1. Bump to intake-v2.
2. Send submitted_input and expected_input_kind as separate structured fields.
3. Tell the model the expected kind is immutable task context.
4. Keep URL scheme/host/credential checks deterministic and unchanged.

Required decomposition work:
1. Bump to decomposition-v2.
2. Add a draft schema with ordered claims and optional parent_claim_index, not claim_ref/parent_claim_ref.
3. Generate stable claim_ref values from deterministic order and canonical content digest, within existing length/pattern limits.
4. Convert validated parent indexes into generated parent references.
5. Validate claim count, normalized duplicates, parent bounds, cycles, importance/weight, and exact original_text_span membership.
6. Normalize into existing AtomicClaimOutput/DecompositionOutput for persistence and planner compatibility.

Verification:
- expected input kind is present in the fake-model payload;
- matching kind passes and drift fails precisely;
- stable claim IDs and parent conversion are idempotent;
- bad parent, cycle, duplicate, bad span, and limit cases fail with stable codes;
- planner tests still consume normalized claims.

Stop after focused tests pass. Hand off to Prompt 7.
```

## Prompt 7 — Require exact evidence-classification task coverage

```text
You are implementing Prompt 7 of the Elara sub-agent optimization plan.

Goal:
Ensure the classification model returns one result for every bounded deterministic claim/passage task and cannot silently return an empty or partial list.

Read only the Step 7 section of project-context/sub-agent optimization.md; Evidence Classification and Passage Segmentation slices of 4.4; passage retrieval/ranking code; classification prompt/schema/workflow; scoring consumers; and focused tests.

Required work:
1. Build a bounded classification task list in Python from ranked claim/passage candidates. Reuse existing ranking and depth limits; do not create an unbounded Cartesian product.
2. Give every task a deterministic task_ref and immutable claim_ref/passage_id.
3. Bump the prompt to evidence-classification-v2 and send only declared tasks plus the evidence text needed for those tasks.
4. Make the model return task_ref and language judgments, then normalize into existing EvidenceClassificationItemOutput records.
5. Validate exact set equality: every expected task exactly once, no missing, duplicate, unknown, or extra task.
6. An empty response when tasks exist must fail CLASSIFICATION_COVERAGE_MISMATCH.
7. Preserve deterministic relevance, extraction certainty, entity, time, quote/number, and neutral-no-evidence rejection gates. Model rejection recommendations remain advisory.

Verification:
- exact coverage success;
- missing, duplicate, unknown, extra, and empty outputs;
- bounded task-count behavior by research depth;
- deterministic rejection reasons and scoring inputs unchanged;
- no raw passage content in events/logs.

Stop after focused classification, passage retrieval, workflow, and scoring-boundary tests pass. Hand off to Prompt 8.
```

## Prompt 8 — Make every factual report field citation-auditable

```text
You are implementing Prompt 8 of the Elara sub-agent optimization plan.

Goal:
Close the synthesis gap in which free-form limitations, inaccessible-source notes, or evidence gaps can carry factual model claims outside citation audit.

Read only the Step 8 section of project-context/sub-agent optimization.md; Synthesis and Citation Audit slices of 4.4; synthesis/citation prompts and schemas; workflow synthesis, audit, revision, and persistence code; and focused tests.

Required work:
1. Add one canonical iter_auditable_sentences helper and use it everywhere sentence counts or sentence/passage pairs are computed.
2. Keep every model-authored factual assertion in CitedReportSentenceOutput or an equivalent cited type included by the helper.
3. Construct inaccessible-source notes deterministically from snapshot status and sanitized reason.
4. Construct system-known evidence gaps/limitations deterministically, or make model-authored factual variants cited and auditable.
5. Bump synthesis/citation prompt versions to v2 only where the contract changed.
6. Preserve approved-passage checks, strongest-contradiction requirement, exact citation pair equality, bounded citation revision, required evidence timestamp, and no-publication-before-audit.
7. Generate or validate stable sentence references; no duplicate sentence_ref may enter audit or persistence.

Verification:
- a factual limitation/gap cannot bypass the audit helper;
- deterministic inaccessible notes need no fabricated citation;
- missing, extra, duplicate, unknown, and rejected citation pairs fail;
- partial/not-entailed citations revise and re-audit within the existing bound;
- ready_for_completion remains false until the final exact audit passes.

Stop after focused synthesis, citation, workflow, and persistence tests pass. Hand off to Prompt 9.
```

## Prompt 9 — Type deterministic extension failures and eliminate silent stops

```text
You are implementing Prompt 9 of the Elara sub-agent optimization plan.

Goal:
Give discovery, retrieval, extraction, segmentation, provenance, scoring, and numerical audit precise outcomes instead of generic WORKFLOW_EXTENSION_FAILED or silent completion-gate rejection.

Read only the Step 9 section of project-context/sub-agent optimization.md and the directly relevant 4.4 stage slices. Inspect each extension implementation and its focused tests; do not broaden into unrelated infrastructure.

Required work:
1. Add a typed extension exception carrying stable code, public message, retryable flag, and safe primitive details.
2. Emit NO_DISCOVERY_RESULTS after the existing bounded Brave search policy returns no candidates without a provider error. Do not add a second provider.
3. Emit NO_ACCESSIBLE_SOURCES, NO_EXTRACTED_SOURCES, and NO_USABLE_PASSAGES at their responsible boundaries.
4. Narrow research/pipeline.py broad exception handling to documented parser/source-byte failures. Programming, storage-integrity, missing-state, and hash invariant failures must propagate as typed/internal failures, not inaccessible evidence.
5. Validate provenance endpoints, duplicate edges, and allowed dependency multipliers before completing provenance.
6. Add explicit scoring and numerical-audit preconditions without changing deterministic formulas.
7. Preserve typed extension codes in the workflow wrapper. Unexpected exceptions must reach sanitized WORKER_ERROR monitoring.
8. Ensure graph transitions do not silently stop on a missing prerequisite. The responsible stage must append a precise error first.
9. Preserve SSRF, DNS, redirect, port, content-type, size, timeout, credential, and private-storage boundaries.

Verification:
- zero search results, all inaccessible, no extraction, no passages;
- expected parser failure versus injected invariant/programming error;
- invalid provenance endpoint/multiplier;
- missing scoring/numerical inputs;
- transition tests prove no normal empty path becomes COMPLETION_GATE_REJECTED;
- retrieval security regression tests remain green.

Stop after the narrow extension, transition, verification-task, and security tests pass. Hand off to Prompt 10.
```

## Prompt 10 — Integrate, verify, and prepare one deployable revision

```text
You are implementing Prompt 10 of the Elara sub-agent optimization plan.

Goal:
Prove the optimized contracts work together provider-free and prepare one immutable revision for API/worker deployment. Do not deploy in this prompt.

Read only the Step 10, test matrix, rollout, and completion sections of project-context/sub-agent optimization.md plus directly relevant acceptance and runtime configuration files.

Required work:
1. Review git diff for contract consistency across schemas, prompts, validators, workflow, extensions, transitions, runtime persistence, and tests.
2. Run focused suites in this order: agent schemas/validators, DeepSeek client, workflow/transitions, retrieval/extraction/passages, provenance/scoring/numerical, synthesis/citation, verification task, and the existing provider-free full-stack acceptance test.
3. Expand testing only when a focused failure identifies a dependency. Do not run a production-release audit or reinstall/rebuild the whole environment.
4. Verify API/worker revision reporting is sourced from the same immutable commit identifier. If revision reporting is already implemented, test it; do not invent a new deployment system.
5. Verify no raw model/source content appears in contract-failure logs or public events.
6. Verify retry/redelivery idempotency and durable completion ordering.
7. Run Graphify update and inspect git status without reverting unrelated user changes.
8. Produce a deployment handoff containing exact focused commands/results, revision, changed files, rollback commit strategy, approved synthetic/public demo prerequisite, and known limitations.

Stop before any Vercel/AWS mutation. Hand off to Prompt 11.
```

## Prompt 11 — Execute the minimum Full Mode hosted demo

```text
You are implementing Prompt 11 of the Elara sub-agent optimization plan.

Authorization gate:
Proceed only if the user explicitly authorized deployment/hosted testing and the approved Firebase session and host access are available. Otherwise return the handoff checklist and stop. Do not request or print secrets.

Goal:
Deploy the same immutable revision to the existing API and Celery worker and prove one minimum Full Mode demo end to end.

Read only:
- project-context/DEMO_SCOPE.md;
- Step 10 and completion criteria from project-context/sub-agent optimization.md;
- the directly relevant deployment runbook;
- the existing Step 25c evidence record.
Do not read the full implementation plan, project PDFs, or production-release material.

Required work:
1. Confirm the API and worker are configured for the same immutable revision before submitting a claim.
2. Use the existing Vercel frontend, CloudFront HTTPS API, one EC2 host, Firebase demo account, PostgreSQL, Redis, Celery, DeepSeek, Brave, and private object storage. Do not add infrastructure.
3. Sign in with the approved Firebase demo account and confirm the FastAPI session is valid.
4. Submit one approved public or synthetic claim with no sensitive/private source data.
5. Observe sanitized progress through Celery, synthesis, citation audit, durable report/citation persistence, and COMPLETED.
6. Refresh the browser or reconnect SSE and prove the report reloads from PostgreSQL.
7. Confirm browser bundles/responses contain no server credential and private PostgreSQL, Redis, Celery, and object-storage service ports are not public.
8. Record stable Vercel URL, CloudFront API URL, revision, approved prerequisites, EC2 start/stop procedure, sanitized pass/fail evidence, and remaining demo limitations in the existing Step 25c evidence file.
9. If an external service blocks progress, record it once and stop. Do not repeatedly retry or weaken a guard.
10. Once the case passes, mark the hosted demo operational and stop. Do not run a production-release audit. The EC2 instance may be stopped between demos.

Required final report:
- PASS/FAIL for auth, session, enqueue, Celery chain, synthesis, citation audit, durable COMPLETED, refresh/SSE reload, same revision, credential privacy, and private ports;
- changed evidence file;
- exact revision;
- remaining demo limitation;
- EC2 running/stopped state.
```

## Review checklist for every handoff

- The assigned prompt, and only that prompt, was implemented.
- No technology-stack or provider change was introduced.
- DeepSeek and credentials remain server-side.
- Retrieved evidence remains untrusted.
- Model-owned IDs/redundant fields were reduced, not expanded.
- Stable deterministic validators guard every accepted model output.
- Repairs and retries are bounded.
- Scoring and final labels remain deterministic.
- Every model-authored factual sentence is in citation audit.
- PostgreSQL durable artifacts precede `COMPLETED`.
- Focused tests passed and failures are reported honestly.
- Graphify was updated after changes.
- Unrelated dirty-worktree changes were preserved.
- The next prompt and any blocker are explicit.
