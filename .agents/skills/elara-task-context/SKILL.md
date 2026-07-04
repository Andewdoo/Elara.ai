---
name: elara-task-context
description: Load the minimum authoritative Elara.ai project context needed for a coding, review, architecture, security, implementation-step, or release-readiness task. Use before changing Elara source, schemas, workflows, retrieval, scoring, frontend, infrastructure, or project guidance, especially when a task references IMPLEMENTATION_PLAN.md, project-context/AGENTS.md, or a numbered Step 1-26.
---

# Elara Task Context

Keep context narrow while preserving project constraints.

## Workflow

1. Read the root and closest nested `AGENTS.md` files. Do not preload the full project guide or implementation plan.
2. Query Graphify with the exact task and `--budget 1000`. Use `path` or `explain` for a named relationship or concept.
3. Classify the task and extract the smallest matching Markdown section with `scripts/context_slice.py`.
4. Read additional sections only when the first slice exposes a concrete dependency.
5. Read both PDFs or an entire project document only for broad architecture, methodology changes, or Step 26.
6. After changes, run focused verification and update Graphify.

## Context Map

- API/auth/SSE: plan `3.1`, `3.2`, `3.3`, `3.5`; guide `System Boundaries` or `API Expectations`.
- Database/migrations: plan `2.2` through `2.5`; guide `Persistence Expectations`.
- Worker/LangGraph/DeepSeek: plan `4.1` through `4.4`; guide `Agent Workflow` or `Deterministic vs Model Responsibilities`.
- Retrieval/extraction/security: plan `4.4` subsections, `4.5`, `6`, or `12.5`; guide `Retrieval Security Rules`.
- Scoring/numerical/citations: plan `Scoring`, `Numerical Audit`, `Citation Audit`, or `12.2`; guide `Deterministic vs Model Responsibilities`.
- Frontend/report UI: plan `5.1` through `5.7`; guide `Frontend Expectations` or `Report Language Rules`.
- Evaluation/operations/release: plan `7`, `8`, or the exact `12.x` release step; guide `Testing Priorities` or `Completion Closure Rules`.
- Numbered implementation request: extract that number from `project-context/prompts` and the matching plan heading. Do not read all 26 prompts.

## Commands

List headings before choosing a slice when wording is uncertain:

```powershell
.\.graphify-venv\Scripts\python.exe .agents\skills\elara-task-context\scripts\context_slice.py headings project-context\IMPLEMENTATION_PLAN.md
```

Extract one heading and its descendants:

```powershell
.\.graphify-venv\Scripts\python.exe .agents\skills\elara-task-context\scripts\context_slice.py heading project-context\IMPLEMENTATION_PLAN.md "3.5 Server-Sent Events"
```

Extract one numbered implementation prompt:

```powershell
.\.graphify-venv\Scripts\python.exe .agents\skills\elara-task-context\scripts\context_slice.py step project-context\prompts 18
```

If a heading query is ambiguous, refine it instead of accepting multiple large sections.

