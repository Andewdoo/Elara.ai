# Lite Step 15 Hosting Status

> Historical hosting record. Elara is now explicitly scoped as a personal, low-traffic side-project demo. References below to Vercel Production mean Vercel's stable environment name, not a production-SaaS posture.

Date: 2026-07-11

Scope: host the additive Lite v1 public demo on a Lite-only Supabase project and
Vercel without replacing the Full Mode FastAPI, Redis, Celery,
PostgreSQL/pgvector, S3-compatible storage, Firebase Authentication, Brave
Search, DeepSeek, LangGraph, or Step 25B staging evidence.

## Current Result

The hosted Lite public demo is not approved as live for the Step 15 criteria.

Observed working pieces:

- Vercel account access is available for `andrew-liu-projects`.
- Vercel project `elara-ai-web` exists.
- Vercel project root is linked locally from `apps/web`.
- A fresh Vercel Preview deployment built successfully and is ready:
  `https://elara-ai-nkykj0x3n-andrew-liu-projects.vercel.app`.
- Vercel Preview and Production environment names include the Lite browser
  variables, server-side Supabase variables, Lite settings, and server-side
  `DEEPSEEK_*` values.
- The rotated `NEXT_PUBLIC_SUPABASE_ANON_KEY` and server-only
  `SUPABASE_SERVICE_ROLE_KEY` values were updated in both Vercel environments
  before the fresh Preview deploy.
- Supabase management authentication succeeds and identifies one active,
  Lite-only project: `Elara Lite` (`peujyhcmxyhomfdhwebk`).
- Service-role REST checks confirm all required Lite tables are accessible:
  `lite_documents`, `lite_chunks`, `lite_runs`, `lite_run_citations`,
  `lite_feedback`, and `lite_eval_cases`.
- `match_lite_chunks` executes for the service role. Anonymous access to
  `lite_chunks` and that RPC is denied with HTTP 401, while the public document
  metadata endpoint remains readable.
- The approved corpus is present (4 documents and 5 chunks), and a bounded
  `match_lite_chunks` probe returned a result.
- Production `https://elara-ai-web.vercel.app/` opens the Lite evidence-library
  workspace first.
- Production `https://elara-ai-web.vercel.app/verify` remains reachable for Full
  Mode.
- Recent Vercel logs for the smoke requests show no secret values.
- Generated browser static bundles did not contain the local Supabase
  service-role key or DeepSeek API key values.

Blocking issues:

- The fresh Vercel Preview's `/api/lite/answer` endpoint is protected by Vercel
  Authentication. All five required public smoke prompts returned HTTP 401 before
  reaching the application. The route itself has no HTTP 401 response path, so
  this is deployment protection rather than a Lite API or Supabase failure.
- Until the Preview API can be reached with an approved bypass or is made
  available for the intended public smoke target, support, contradiction,
  quote/paraphrase, numerical-context, and insufficient-evidence cases cannot
  be app-executed. Citation behavior and DeepSeek execution therefore remain
  unverified for this Preview, and the Preview-to-Production promotion gate is
  closed.

## Remaining Commands

Allow the intended smoke client to reach the Preview API. Use an approved Vercel
deployment-protection bypass or disable Preview protection only for the intended
public smoke target; do not promote an untested Preview.

Once the Preview smoke suite passes, inspect the new Vercel environment values
and deploy the exact tested revision to Production. Browser-visible values must
stay limited to `NEXT_PUBLIC_*`; privileged Supabase and DeepSeek values must
stay server-side:

```powershell
cd apps/web
vercel env ls
vercel env add NEXT_PUBLIC_ELARA_MODE preview
vercel env add NEXT_PUBLIC_ELARA_MODE production
vercel env add NEXT_PUBLIC_SUPABASE_URL preview
vercel env add NEXT_PUBLIC_SUPABASE_URL production
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY preview
vercel env add NEXT_PUBLIC_SUPABASE_ANON_KEY production
vercel env add SUPABASE_URL preview
vercel env add SUPABASE_URL production
vercel env add SUPABASE_SERVICE_ROLE_KEY preview
vercel env add SUPABASE_SERVICE_ROLE_KEY production
vercel env add SUPABASE_LITE_SCHEMA preview
vercel env add SUPABASE_LITE_SCHEMA production
vercel env add LITE_DEMO_ENABLED preview
vercel env add LITE_DEMO_ENABLED production
vercel env add LITE_CORPUS_VERSION preview
vercel env add LITE_CORPUS_VERSION production
vercel env add DEEPSEEK_API_KEY preview
vercel env add DEEPSEEK_API_KEY production
vercel env add DEEPSEEK_BASE_URL preview
vercel env add DEEPSEEK_BASE_URL production
vercel env add DEEPSEEK_CHAT_MODEL preview
vercel env add DEEPSEEK_CHAT_MODEL production
vercel env add DEEPSEEK_REASONING_MODEL preview
vercel env add DEEPSEEK_REASONING_MODEL production
```

After valid Supabase server-side credentials are available locally, ingest the
approved seed corpus:

```powershell
npm --workspace @elara/web run lite:ingest -- --input fixtures/lite-corpus/seed-corpus.json
```

Use fixture embeddings only when the demo environment explicitly approves them:

```powershell
npm --workspace @elara/web run lite:ingest -- --input fixtures/lite-corpus/seed-corpus.json --embedding-mode fixture
```

Deploy Preview first:

```powershell
cd apps/web
vercel deploy
```

If Preview deployments are protected, either disable protection for the intended
public smoke target or provide the approved Vercel bypass mechanism for the test
client. Do not promote from an untested protected Preview.

Smoke test the Preview URL with representative support, contradiction,
quote/paraphrase, numerical-context, and insufficient-evidence prompts:

```powershell
$PreviewUrl = "https://replace-with-preview-url"
$cases = @(
  @{ name = "support"; input = "Did the council approve $12.4 million for electric bus grants in fiscal year 2025?"; hint = "question" },
  @{ name = "contradiction"; input = "The city approved $14.2 million for electric bus grants in 2025."; hint = "claim" },
  @{ name = "quote_paraphrase"; input = "Chair Rivera said the pilot will serve three neighborhood clinics during its first quarter."; hint = "paraphrase" },
  @{ name = "numerical_context"; input = "How much more did the city approve for electric bus grants in fiscal year 2025 compared with the prior year?"; hint = "question" },
  @{ name = "insufficient_evidence"; input = "Did the downtown library increase staffing levels in 2024?"; hint = "question" }
)
foreach ($case in $cases) {
  $body = @{
    corpus_version = "lite-corpus-v1"
    input = $case.input
    input_type_hint = $case.hint
    client_trace_id = "step15-$($case.name)"
  } | ConvertTo-Json -Compress
  Invoke-RestMethod -Method Post -Uri "$PreviewUrl/api/lite/answer" -ContentType "application/json" -Body $body
}
```

Verify before promotion:

- `/` opens the Lite evidence-library workspace first.
- `/verify` remains reachable.
- Every successful answer cites stored chunk ids and source labels.
- Weak support returns `insufficient_evidence`.
- No Supabase service-role key, DeepSeek key, or other server secret appears in
  browser output, screenshots, logs, or static client bundles.

Promote only after Preview smoke checks pass:

```powershell
vercel promote https://replace-with-preview-url
```

Do not build or populate `lite_cached_responses` in this step.
