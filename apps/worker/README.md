# Elara Worker

Celery and LangGraph worker for evidence retrieval, extraction, provenance, deterministic scoring, numerical audits, report synthesis, and citation audits.

Model calls belong behind the server-side `DeepSeekClient` wrapper. Retrieved content is untrusted evidence and must never alter workflow policy, credentials, scoring formulas, or final verdict logic.

