---
type: "query"
date: "2026-07-15T01:36:31.250735+00:00"
question: "why did the worker fail during planning with invalid claim or objective references"
contributor: "graphify"
outcome: "useful"
source_nodes: ["Planner", "4.4 LangGraph Nodes"]
---

# Q: why did the worker fail during planning with invalid claim or objective references

## Answer

Expanded from graph vocab: [planner, planning, claim, objective, references, validation, workflow, state, error, failure, run, deepseek]. The Planner output passed its schema but failed one or more deterministic cross-reference or coverage checks in workflow.py: duplicate or unknown claim/objective refs, incomplete objective coverage, over-limit or duplicate queries, missing primary/contradiction paths, required attribution or exact quote, or mismatched query intent. The public message is generic, and the failed state does not retain the raw model plan, so the exact failed predicate cannot be reconstructed from the hosted run.

## Outcome

- Signal: useful

## Source Nodes

- Planner
- 4.4 LangGraph Nodes