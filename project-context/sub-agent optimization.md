# Sub-Agent Optimization Implementation Plan

Status: proposed remediation plan for the Full Mode hosted-demo workflow

Scope: worker agent contracts, deterministic workflow guards, focused tests, and the minimum hosted-demo validation

Deployment posture: owner-controlled, low-traffic side-project demo as defined by `DEMO_SCOPE.md`

## 1. Goal

Make every Elara worker agent produce output that can be accepted, normalized, persisted, and audited deterministically, with special priority on the planning failure:

> Research planning returned invalid claim or objective references.

The fix must preserve the existing Elara stack and boundaries:

- Next.js, TypeScript, FastAPI, SQLAlchemy/Alembic, PostgreSQL/pgvector, Redis, Celery, LangGraph, DeepSeek, Firebase Authentication, Brave Search, and private S3-compatible storage remain in place.
- DeepSeek stays behind the server-side `DeepSeekClient`; no browser model calls, OpenAI APIs, or new model provider are introduced.
- PostgreSQL remains durable truth and Redis remains transient.
- URL policy, retrieval limits, calculations, scoring, final label gates, citation presence, and completion remain deterministic.
- A report cannot become `COMPLETED` until its report artifacts and exact citation-audit rows are durable.
- Retrieved content remains untrusted evidence and never becomes workflow instructions.
- The work targets one reliable hosted demo, not high availability or public-launch readiness.

## 2. Incident statement and certainty

The hosted Full Mode run passed Firebase/FastAPI authentication, durable run creation, SSE connection, and Celery startup, then stopped in the planner with `INVALID_RESEARCH_PLAN`.

The exact violated predicate is not currently knowable from durable evidence because `apps/worker/graph/workflow.py` collapses ten planner checks into one Boolean and records one generic public message. The failure therefore proves that at least one planner invariant failed, but it does not prove which one.

The current planner rejects any response with:

1. duplicate `objective_ref` values;
2. an objective referencing an unknown `claim_ref`;
3. incomplete or extra claim coverage;
4. too many queries for the selected research depth;
5. duplicate normalized query text;
6. no primary and contradiction paths for every fact-checkable claim;
7. no attribution query when attribution is required;
8. no query containing the exact short quotation when required;
9. a query referencing an unknown objective; or
10. a query `intent` that differs from its objective `intent`.

The highest-confidence contract defect is that the model owns `objective_ref`, `claim_ref`, and a redundant query `intent`, while Python treats them as relational keys and requires exact equality. `PlanningOutput` checks only that query objective references exist. The v1 planner prompt asks for coverage but does not explicitly require verbatim supplied identifiers, complete one-to-one claim coverage, or query/objective intent equality. A structurally valid DeepSeek response can therefore fail the workflow's stronger semantic contract.

## 3. Current agent and deterministic-stage risk review

| Stage or role | Intended responsibility | Current risk | Required direction |
|---|---|---|---|
| Intake agent | Normalize and classify the submitted target | `expected_input_kind` is checked after the call but is not included as an explicit allowed value in the model payload; drift becomes terminal `INPUT_TYPE_MISMATCH` | Send the expected kind as immutable task context and normalize only fields the model should own |
| Decomposition agent | Produce atomic claims and parent relationships | The model creates `claim_ref`, `parent_claim_ref`, and `original_text_span`; the prompt does not specify deterministic reference construction or exact-substring rules | Use an index-based draft schema and generate stable claim references in Python; validate exact spans and parent graph separately |
| Planner agent | Produce objectives and queries | Confirmed prompt/schema/guard mismatch; generic diagnostics; no bounded semantic repair | Use deterministic objective references, remove redundant query intent, return stable violation codes, and permit one corrective replan |
| Discovery/source selection | Search Brave, canonicalize, rank, deduplicate | Zero search results with no provider error can yield an empty state that later stops generically | Emit an explicit typed `NO_DISCOVERY_RESULTS` failure after the bounded search policy is exhausted |
| Secure retrieval | Fetch selected public sources safely | The URL/network boundary is strong; inaccessible sources can still leave no usable evidence | Preserve security controls and emit an explicit typed no-accessible-source outcome without weakening URL policy |
| Extraction | Produce auditable source text and metadata | A broad `except Exception` in `research/pipeline.py` converts programming, state, and storage invariant errors into an inaccessible source | Catch only source/parser failures; propagate invariant and programming failures with sanitized typed codes |
| Segmentation/embedding | Produce passages and optional vectors | Lexical fallback exists, but an empty passage result can cause a route stop and generic completion rejection | Preserve pgvector and fallback; emit `NO_USABLE_PASSAGES` with counts and retrieval mode |
| Provenance/dependency analysis | Group derivative evidence and compute dependency structure | Model-independent, but bad or orphan endpoints can poison later weights | Validate every dependency endpoint, duplicate edge, and multiplier before stage completion |
| Evidence-classification agent | Classify selected claim/passage tasks | The schema allows an empty list and the workflow checks only duplicate/unknown returned pairs, not missing required pairs | Build a bounded deterministic task list and require exactly one classification for every task |
| Deterministic scoring | Calculate evidence weights and claim/report scores | Correctly deterministic; risk is incomplete evidence or provenance entering the service | Add explicit preconditions and reject incomplete inputs without model fallback |
| Numerical audit | Validate Decimal arithmetic and units | Correctly deterministic; risk is missing candidate provenance or partial calculation sets | Require calculation/candidate linkage and precise audit failure codes |
| Synthesis agent | Draft the evidence-grounded report | `limitations`, `inaccessible_source_notes`, and `evidence_gaps` are free-form strings outside `_sentences()` and therefore outside citation audit | Generate system-known notes deterministically; represent any model-authored factual note as an auditable cited sentence |
| Citation-audit agent | Check every sentence/passage pair | Exact-set guard is strong, but it depends on `_sentences()` covering every factual field and has no shared structured-output repair | Expand auditable sentence coverage and use the bounded structured-response repair |
| Citation revision agent | Revise unsupported sentences and re-audit | Already bounded, but it shares synthesis schemas and model-owned sentence references | Preserve the revision limit; use stable sentence references and exact-set revalidation |
| Workflow extension wrapper | Run discovery through numerical audit | Catches all exceptions as `WORKFLOW_EXTENSION_FAILED` and exposes only a coarse `failure_kind` | Introduce typed stage exceptions and retain unexpected exceptions as internal worker errors |
| LangGraph transitions | Decide whether the next node runs | `evidence_ready` and `synthesis_ready` can stop on empty state without appending a specific error | Convert missing prerequisites into a stage failure before routing; transitions should not silently terminate |
| Celery completion handoff | Persist completed artifacts or fail safely | Strong durable completion gate; a silent route stop becomes generic `COMPLETION_GATE_REJECTED` | Keep the gate and eliminate silent stops upstream; do not relax completion conditions |

## 4. Target contract pattern

Every language stage should use the same four-boundary pattern:

1. **Deterministic task construction**: Python selects the exact inputs, allowed references, limits, and required coverage.
2. **Model-facing draft output**: DeepSeek supplies only language judgments and text it is qualified to produce. It does not invent database-like identifiers or duplicate deterministic fields.
3. **Deterministic normalization and validation**: Python assigns stable references, derives redundant fields, checks exact coverage, and returns a list of stable violation codes.
4. **Bounded correction or safe failure**: one schema repair may regenerate malformed structured output; one stage-specific semantic correction may fix contract violations. Exhaustion produces a precise durable failure, never a partially published report.

Keep the existing persisted `PlanningOutput`, `AtomicClaimOutput`, evidence records, and downstream workflow state where practical. Add separate model-facing draft schemas and normalize them into the existing types. This contains migration risk and preserves persistence/API contracts.

## 5. Stable failure taxonomy

Add stable, non-sensitive codes. Public events may expose the code and counts, but not raw prompts, raw model output, source text, credentials, or private reasoning.

Planner violation codes:

- `PLAN_DUPLICATE_OBJECTIVE_REF` only for legacy/persisted input validation;
- `PLAN_UNKNOWN_CLAIM_REF`;
- `PLAN_MISSING_CLAIM_COVERAGE`;
- `PLAN_EXTRA_CLAIM_COVERAGE`;
- `PLAN_QUERY_LIMIT_EXCEEDED`;
- `PLAN_DUPLICATE_QUERY`;
- `PLAN_PRIMARY_PATH_MISSING`;
- `PLAN_CONTRADICTION_PATH_MISSING`;
- `PLAN_ATTRIBUTION_PATH_MISSING`;
- `PLAN_EXACT_QUOTE_PATH_MISSING`;
- `PLAN_UNKNOWN_OBJECTIVE_REF` only for legacy/persisted input validation; and
- `PLAN_INTENT_MISMATCH` only for legacy/persisted input validation.

Shared contract codes:

- `STRUCTURED_RESPONSE_INVALID`;
- `STRUCTURED_RESPONSE_REPAIR_EXHAUSTED`;
- `AGENT_CONTRACT_REPAIR_EXHAUSTED`;
- `NO_DISCOVERY_RESULTS`;
- `NO_ACCESSIBLE_SOURCES`;
- `NO_EXTRACTED_SOURCES`;
- `NO_USABLE_PASSAGES`;
- `CLASSIFICATION_COVERAGE_MISMATCH`;
- `PROVENANCE_GRAPH_INVALID`;
- `SCORING_INPUTS_INCOMPLETE`;
- `NUMERICAL_AUDIT_INCOMPLETE`;
- `REPORT_FIELD_NOT_AUDITABLE`; and
- `CITATION_AUDIT_COVERAGE_MISMATCH`.

The durable/public error details should stay compatible with the existing primitive-value detail map. Record fields such as `primary_violation`, `violation_count`, `repair_attempted`, `expected_count`, and `received_count`. If all codes are needed, store a bounded, comma-separated list of stable codes, not model text.

## 6. Implementation steps

### Step 1 — Freeze the failure with focused regression tests

Likely files:

- `apps/worker/tests/test_workflow.py`
- `apps/worker/tests/test_agent_schemas.py`
- `apps/worker/tests/test_verification_task.py`

Actions:

1. Add a deterministic planner response that is valid Pydantic JSON but fails each current semantic predicate independently.
2. Assert the current generic failure only in a characterization test; new tests should target the future precise validator.
3. Add a hosted-run-shaped unit fixture using a public/synthetic claim, with no provider secrets or raw hosted data.
4. Confirm a failure persists its code and cannot pass `ready_for_completion`.
5. Confirm retry/redelivery does not duplicate agent events or durable artifacts.

Exit criteria:

- Every current planner predicate has a named failing test.
- The known live failure class can be reproduced without real DeepSeek or Brave credentials.

### Step 2 — Extract pure contract validators

Likely files:

- new `apps/worker/agents/validation.py`
- `apps/worker/graph/workflow.py`
- `apps/worker/tests/test_agent_contract_validation.py`

Actions:

1. Define a small `AgentContractViolation` Pydantic model or frozen dataclass with `code`, `field`, and safe counts/identifiers.
2. Move planner Boolean checks into `validate_research_plan(state, output) -> tuple[AgentContractViolation, ...]`.
3. Keep validation pure: no network, database, Redis, clock, or model access.
4. Return all violations in deterministic sorted order, while selecting the first stable code for the public failure.
5. Add corresponding validators for decomposition graph integrity, classification task coverage, synthesis auditability, and citation exact-set coverage as later steps land.

Exit criteria:

- The same invalid plan always returns the same ordered violation codes.
- `workflow.py` no longer hides planner predicates inside a single Boolean.

### Step 3 — Remove model-owned planner foreign keys

Likely files:

- `apps/worker/agents/schemas.py`
- `apps/worker/graph/workflow.py`
- `apps/worker/tests/test_agent_schemas.py`
- `apps/worker/tests/test_workflow.py`

Actions:

1. Add model-facing `PlanningDraftObjectiveOutput` and `PlanningDraftQueryOutput` types.
2. Nest draft queries under their objective. Draft queries must not contain `objective_ref` or a second `intent`.
3. Keep `claim_ref` in the draft only as a selector from `allowed_claim_refs`; reject any other value.
4. Generate `objective_ref` in Python from canonical objective content, for example `obj-` plus a truncated SHA-256 digest of `claim_ref`, intent, target, and deterministic ordinal. Detect collisions.
5. Derive each persisted query's `objective_ref` and `intent` from its parent objective.
6. Normalize the draft into the existing `PlanningOutput`, preserving downstream database and workflow contracts.
7. Validate complete claim coverage, depth limits, required intent paths, duplicate normalized queries, attribution, and exact quotation rules after normalization.

Exit criteria:

- DeepSeek cannot create an unknown objective reference or query/objective intent mismatch by construction.
- The normalized persisted plan remains compatible with discovery and existing persistence.

### Step 4 — Make the planner prompt and payload executable contracts

Likely files:

- `apps/worker/agents/planning.py`
- `apps/worker/graph/workflow.py`
- focused planner prompt/contract tests

Actions:

1. Bump the prompt identifier to `planner-v2`.
2. Send a structured user payload containing:
   - `claims`;
   - `allowed_claim_refs`;
   - `research_depth`;
   - `max_query_count`;
   - `required_intents_by_claim`;
   - `requires_attribution_check`;
   - `exact_quote`, only when applicable; and
   - an explicit statement that identifiers must be copied only from the allowed set.
3. State that every fact-checkable claim must have primary and contradiction objectives.
4. State that all queries inherit intent from the containing objective.
5. State exact normalization-sensitive rules: no duplicate queries after whitespace/case normalization and preserve the exact short quotation inside at least one attribution query.
6. Do not ask the model for truth judgments, final scores, private reasoning, browsing, or credentials.

Exit criteria:

- The prompt, JSON schema, and deterministic validator express the same constraints.
- Prompt version is recorded on durable run metadata.

### Step 5 — Add bounded structured and semantic repair

Likely files:

- `apps/worker/agents/deepseek_client.py`
- `apps/worker/graph/workflow.py`
- `apps/worker/tests/test_deepseek_client.py`
- `apps/worker/tests/test_workflow.py`

Actions:

1. Add one optional structured-response regeneration inside `DeepSeekClient` for invalid JSON or Pydantic schema output.
2. The regeneration should reuse the original trusted instructions and schema with a sanitized message such as `previous response failed schema validation`; it must not log or persist raw invalid output.
3. Preserve the same low temperature, server-side credentials, provider model selection, timeouts, and redacted telemetry.
4. Record attempt count and final safe error code in metadata/events. Do not expose raw Pydantic error values when they may contain evidence text.
5. After a structurally valid planner result fails semantic validation, permit one planner-specific corrective replan using only stable violation codes and allowed references.
6. Revalidate from scratch. A second semantic failure is terminal `AGENT_CONTRACT_REPAIR_EXHAUSTED` with `primary_violation` and counts.
7. Do not make Celery retry the whole run for deterministic contract failures. Provider timeouts/rate limits remain the only retryable model failures.

Maximum call policy for one planner stage:

- initial structured call;
- at most one schema regeneration if parsing/schema validation fails; and
- at most one semantic corrective replan if a valid response violates planner invariants.

Exit criteria:

- Repairs are bounded, observable, redacted, and deterministic after output receipt.
- Contract failures cannot trigger an unbounded provider/Celery loop.

### Step 6 — Harden intake and decomposition

Likely files:

- `apps/worker/agents/intake.py`
- `apps/worker/agents/decomposition.py`
- `apps/worker/agents/schemas.py`
- `apps/worker/graph/workflow.py`
- focused schema/workflow tests

Intake actions:

1. Bump to `intake-v2`.
2. Send `submitted_input` and `expected_input_kind` as separate payload fields.
3. Tell the model it may normalize content but must return the supplied allowed input kind.
4. Continue to validate URL scheme, host, and embedded credentials deterministically.

Decomposition actions:

1. Bump to `decomposition-v2`.
2. Introduce a model-facing draft with ordered claims and `parent_claim_index` rather than model-created claim references.
3. Generate stable `claim_ref` values in Python from deterministic order plus a content digest.
4. Translate validated parent indexes into generated parent references.
5. Require `original_text_span` to be an exact substring when present; otherwise use `null` and retain the claim text separately.
6. Preserve importance-to-weight validation, claim count limit, normalized duplicate detection, and cycle prevention.

Exit criteria:

- Intake cannot drift from the API-declared input type.
- Decomposition references and graph links are deterministic and idempotent.

### Step 7 — Enforce complete evidence-classification tasks

Likely files:

- `apps/worker/agents/evidence_classification.py`
- `apps/worker/agents/schemas.py`
- `apps/worker/graph/workflow.py`
- `apps/worker/research/passage_retrieval.py`
- focused classification tests

Actions:

1. Bump to `evidence-classification-v2`.
2. Have Python build a bounded list of required classification tasks from ranked claim/passage candidates; do not send an unbounded claim-by-passage Cartesian product.
3. Assign each task a deterministic `task_ref` and send allowed claim/passage references as immutable context.
4. Require exactly one result per task and no results for undeclared tasks.
5. Normalize task identity into the existing evidence classification records.
6. Keep relevance, extraction certainty, entity, time period, quotation/number, and neutral-no-evidence rejection gates deterministic.
7. An empty model list when tasks exist must fail `CLASSIFICATION_COVERAGE_MISMATCH`, not complete the stage.

Exit criteria:

- Missing, duplicate, unknown, and extra classification results have separate tests.
- Deterministic scoring receives a complete, bounded, validated evidence set.

### Step 8 — Close synthesis and citation-audit coverage

Likely files:

- `apps/worker/agents/synthesis.py`
- `apps/worker/agents/citation_audit.py`
- `apps/worker/agents/schemas.py`
- `apps/worker/graph/workflow.py`
- focused synthesis/citation tests

Actions:

1. Bump synthesis and citation-audit prompts to v2 when their contracts change.
2. Keep model-authored report assertions in `CitedReportSentenceOutput` fields included by a single canonical `iter_auditable_sentences()` helper.
3. Generate inaccessible-source notes from deterministic snapshot status, source reference, and sanitized failure reason.
4. Generate known evidence gaps from deterministic planning/retrieval state, or represent model-authored factual gaps as cited sentences.
5. Treat limitations the same way: non-factual policy notes may be deterministic strings; evidence assertions must be cited and audited.
6. Replace all direct `_sentences()` usage with the canonical helper in synthesis, audit, revision, persistence counts, and tests.
7. Preserve `_guard_citation_audit` exact equality between required and received `(sentence_ref, passage_id)` pairs.
8. Generate stable sentence references in Python where practical; at minimum validate uniqueness and repair once before failure.
9. Preserve the existing bounded citation revision and require re-audit before completion.

Exit criteria:

- No model-authored factual report field can bypass citation audit.
- Missing, extra, duplicate, rejected, or unknown citation pairs fail safely.

### Step 9 — Replace silent deterministic-stage stops and broad exception masking

Likely files:

- `apps/worker/research/pipeline.py`
- `apps/worker/extraction/passages.py`
- `apps/worker/provenance/dependencies.py`
- `apps/worker/scoring/service.py`
- `apps/worker/auditing/numerical.py`
- `apps/worker/graph/workflow.py`
- `apps/worker/graph/transitions.py`
- relevant focused tests

Actions:

1. Define typed extension exceptions carrying a stable code, public message, retryability, and safe primitive details.
2. Make zero-result discovery explicit after the existing bounded Brave search policy; do not add another provider.
3. Distinguish expected source/parser failures from invariant failures in extraction. Narrow the broad `except Exception` to known untrusted-source failure types.
4. Emit explicit failures for no accessible snapshots, no extracted sources, and no usable passages.
5. Validate provenance endpoints and multipliers before scoring.
6. Validate scoring and numerical-audit prerequisites before marking their stages complete.
7. Update the extension wrapper to preserve typed codes. Unexpected exceptions should reach the worker's sanitized `WORKER_ERROR` path and error monitoring, not masquerade as inaccessible evidence.
8. Ensure transition functions only route already-valid state. A missing prerequisite must be recorded by the responsible stage before a transition returns `stop`.

Exit criteria:

- No normal empty-result path ends as generic `COMPLETION_GATE_REJECTED`.
- No programming or persistence invariant error is silently converted into a source-level inaccessible status.

### Step 10 — Focused verification and hosted-demo closure

Run focused checks first:

1. agent schema and validation tests;
2. DeepSeek client tests;
3. workflow and transition tests;
4. retrieval/extraction/passage tests;
5. provenance, scoring, numerical, synthesis, and citation tests;
6. verification-task persistence/idempotency tests; and
7. the existing provider-free full-stack acceptance test.

Do not reinstall dependencies, rebuild all containers, or run repository-wide release gates unless a focused failure establishes the need.

After focused checks pass:

1. update Graphify from the repository root;
2. deploy API and Celery worker from the same immutable commit SHA;
3. verify their reported revision values match;
4. sign in with the approved Firebase demo account;
5. submit one approved public or synthetic claim;
6. verify Celery reaches synthesis and exact citation audit;
7. verify PostgreSQL contains a durable `COMPLETED` report and citation rows;
8. refresh the browser or reconnect SSE and confirm the report reloads from PostgreSQL;
9. confirm no server credential or private PostgreSQL, Redis, Celery, or object-storage port is public; and
10. record sanitized evidence, stable Vercel/CloudFront URLs, revision, prerequisites, start/stop procedure, and remaining demo limitations in the existing Step 25c evidence record.

Once this passes, mark the hosted demo operational and stop. Do not run a production-release audit. The EC2 instance may be stopped between demos.

## 7. Focused test matrix

| Area | Required cases |
|---|---|
| Planner validator | Every violation code independently; multiple violations sorted deterministically; valid plan accepted |
| Planner normalization | Stable objective IDs; collision handling; inherited query intent; complete claim coverage; idempotent repeat |
| Structured repair | Invalid JSON then valid; schema-invalid then valid; second invalid terminal; no raw output in logs/events |
| Semantic repair | Invalid initial plan then valid corrective plan; two invalid plans terminal; nonretryable Celery behavior |
| Intake | Expected kind included; matching result accepted; drift rejected precisely; URL controls unchanged |
| Decomposition | Stable claim IDs; parent index conversion; duplicate claim; cycle; bad span; depth claim limit |
| Classification | Exact task coverage; missing/extra/duplicate/unknown task; empty response; deterministic rejection reasons |
| Discovery/retrieval | Zero results; provider failure; all inaccessible; SSRF/redirect/port controls unchanged |
| Extraction/segmentation | Expected parser failure becomes inaccessible; invariant error propagates; no extracted text; no passages; lexical fallback |
| Provenance/scoring | Unknown dependency endpoint; duplicate edge; invalid multiplier; missing scoring input; deterministic formulas unchanged |
| Synthesis | Unapproved citation; contradiction omission; factual limitation/gap included in audit; deterministic inaccessible notes |
| Citation audit | Exact pair coverage; missing/extra/duplicate pair; partial/not-entailed revision; revision exhaustion; no premature completion |
| Persistence/Celery | Precise durable code; idempotent retry/redelivery; durable report and citation rows precede `COMPLETED` |
| Hosted demo | Auth, API session, enqueue, live Celery, audited completion, refresh/SSE reconnect, same revision, private services |

## 8. Rollout and rollback

Rollout order:

1. land pure validators and characterization tests;
2. land planner draft schema, normalization, prompt v2, and bounded repair;
3. harden remaining language stages one at a time;
4. harden deterministic extension failures;
5. run provider-free acceptance;
6. deploy one revision to both API and worker; and
7. execute one hosted demo claim.

Rollback must be commit-based. API and worker must roll back together to the same known revision. Do not keep an API using v2 persisted contracts with a worker using v1 contracts. Because the preferred design normalizes draft output into existing durable schemas, no database migration should be necessary for the planner fix. If implementation discovers a required schema change, use Alembic, take the sensible single demo database backup first, and document downgrade behavior.

## 9. Completion criteria

This plan is complete when:

- the planner's exact failing invariant is durably identifiable by stable code;
- model-owned relational references are removed or deterministically normalized;
- malformed JSON/schema output and semantic contract failures each have one bounded repair path;
- all language agents have explicit allowed inputs and exact coverage checks;
- every model-authored factual report sentence is citation-audited;
- deterministic stages cannot silently stop or hide invariant failures;
- scoring remains deterministic and unchanged unless a focused correctness test requires a formula fix;
- retry/redelivery remains idempotent;
- one approved hosted claim reaches durable citation-audited `COMPLETED`;
- refresh or SSE reconnect reloads the report from PostgreSQL;
- API and worker report the same revision;
- credentials and private service ports remain private; and
- the hosted demo is recorded operational without a production-release audit.

## 10. Explicit non-goals

- No technology-stack replacement.
- No OpenAI API integration or second search provider.
- No weakening of Firebase authorization, URL policy, deterministic scoring, citation audit, or durable completion.
- No raw model-output persistence for debugging.
- No unbounded model repair or blanket Celery retry.
- No high availability, multi-AZ services, autoscaling, WAF, Kubernetes, managed database/Redis requirement, separate staging/production infrastructure, formal on-call, enterprise release ceremony, or public-launch approval.
- No production-release audit after the minimum hosted demo passes.
