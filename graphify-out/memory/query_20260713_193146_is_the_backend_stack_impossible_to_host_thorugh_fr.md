---
type: "query"
date: "2026-07-13T19:31:46.624593+00:00"
question: "is the backend stack impossible to host thorugh free tier?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["Redis", "ObjectStorage", "Settings"]
---

# Q: is the backend stack impossible to host thorugh free tier?

## Answer

Expanded from graph vocabulary: api, aws, backend, deployment, host, hosting, instance, postgres, redis, stack, storage, worker. The Elara Full Mode stack can run temporarily on the post-July-2025 AWS Free Plan because m7i-flex.large and gp3 are eligible for credit-funded use. It is not permanently free: credits or the six-month period end, and an always-on public beta must move to a paid plan. The stack also runs PostgreSQL, Redis, object storage, API, Celery worker, and Caddy on one host.

## Outcome

- Signal: useful

## Source Nodes

- Redis
- ObjectStorage
- Settings