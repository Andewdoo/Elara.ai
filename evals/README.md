# Elara Evaluations

`harness.py` contains deterministic offline graders for verdict and attribution
accuracy, evidence precision/recall, citation entailment, extraction fidelity,
passage recall, URL relevance, numerical accuracy, primary-source recall,
duplicate/source clustering, confidence calibration and Brier score, latency,
cost, and unsupported statements. Fixtures must contain only synthetic or approved public
benchmark content, never private uploads or retrieved report text.

Run `python -m evals.harness evals/cases/smoke.json --smoke` from the repository root.
