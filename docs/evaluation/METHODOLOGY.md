# Evaluation methodology

Evaluate discovery/retrieval and answer support separately. Preserve the code revision, dataset provenance and split, provider/model version, configured budgets, timestamp and failures with every published result.

The keyless suite runs deterministic routing/claim checks and lexical retrieval on repository fixtures. Report recall@k, precision@k, reciprocal rank and nDCG for retrieval. Claim-support classification and citation attribution are separate: a resolved link is not evidence of entailment. A judge/NLI score needs a manually labeled calibration set, disagreement analysis and an explicit abstention policy before it can be presented as faithfulness.

Synthetic/adversarial fixtures are useful for invariants and regressions. They must be labeled as such and must not be presented as a public benchmark or independently annotated research dataset. Hold out source/topic groups, not just paraphrases of the same template. Record any overlap or limitations.

Repeat evaluations and report mean and standard deviation. Deterministic offline runs normally have zero variance; that does not establish model stability. Live provider comparisons should use multiple seeds/runs, fixed input evidence, matched budgets and separate latency/cost/failure statistics.

CI thresholds are regression guards, not statistical claims. Keep generated reports outside Git and publish selected artifacts with releases or research materials. PostgreSQL, browser and live-model checks should be reported separately from keyless tests.

The shipped SciFact sample and current measured limits are described in [HARDENING_RESULTS.md](HARDENING_RESULTS.md). Per-passage heuristic predictions are scored against externally annotated support edges; this is not a substitute for generated-answer evaluation.
