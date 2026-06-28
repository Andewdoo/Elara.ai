# Elara Worker

Celery and LangGraph worker for evidence retrieval, extraction, provenance, deterministic scoring, numerical audits, report synthesis, and citation audits.

Model calls belong behind the server-side `DeepSeekClient` wrapper. Retrieved content is untrusted evidence and must never alter workflow policy, credentials, scoring formulas, or final verdict logic.

The Step 5 worker registers `verification.verify_run`, uses a per-run Redis lock,
loads the authoritative run from PostgreSQL, checks both durable and transient
cancellation flags, and mirrors public events to PostgreSQL plus the Redis Stream
`elara:run:{run_id}:events`. It performs bounded retries only for explicitly mapped
transient provider and fetch errors. The task currently stops at the validated
handoff; the controlled LangGraph stages are introduced in Step 8 and must use the
same cancellation check before each expensive operation.
