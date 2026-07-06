# Elara Evaluations

`harness.py` contains deterministic offline graders for verdict macro-F1,
attribution accuracy, evidence precision/recall, passage and primary-source
recall, citation entailment, extraction fidelity, numerical accuracy, source
clustering, unsupported statements, Brier score, latency, and cost.

## Dataset lifecycle

`datasets/v0.1.0/` defines separate development/calibration, locked-validation,
adversarial-security, and regression candidate sets. `case.schema.json` defines
the case record shape and `schema.py` enforces the Step 22A review gate. Case
records preserve atomic claims and importance, source and passage expectations,
support and contradiction, attribution, labels and calculations, citation
entailment, dependencies, ambiguities, and inaccessible-source expectations.

Every annotation in `v0.1.0` is a draft marked `pending_human_approval`.
`thresholds.step22a.json` deliberately contains null thresholds with the same
status. These files are framework candidates, not an approved benchmark, and
the reserved locked-validation candidates must not be used for tuning or called
locked until Step 22B review.

Fixtures must contain only synthetic or approved public benchmark content,
never private uploads or retrieved report text. Run the evaluation-only checks
from the repository root:

```text
pytest evals/tests
python -m evals.harness evals/cases/smoke.json --smoke
```
