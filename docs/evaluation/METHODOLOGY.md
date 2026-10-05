# ARES evaluation methodology

ARES treats evaluation as a set of separate, inspectable measurements. It does **not** collapse research quality into one opaque score.

## Dataset classes

### Development regression fixtures

The checked-in JSON files under `evals/datasets/` are small synthetic fixtures written to catch known regressions in:

- task/source routing;
- claim-to-evidence support classification;
- retrieval ordering;
- indirect prompt-injection observability.

They are visible to the implementation and therefore are **not** an independent benchmark. Their purpose is CI regression protection.

### Held-out evaluation

A credible held-out set must be created independently from the implementation/tuning loop and frozen before comparison. See `evals/datasets/heldout/README.md`. ARES supports running the same harness over another dataset directory with `--dataset-dir` and a provenance label with `--dataset-kind`.

## Metrics

### Routing

- accuracy;
- macro-F1 over task classes;
- confidence Brier score;
- Wilson 95% interval for classification accuracy (reported as uncertainty context, not a gate).

Routing is a bounded decision problem. A routing metric does not imply answer quality.

### Claim support

- accuracy and macro-F1 over `supported`, `partially_supported`, `conflicting`, `insufficient_evidence`;
- unsupported-claim retention rate: among fixtures expected to be insufficient, the fraction incorrectly allowed to survive;
- retained-claim precision: among claims the verifier would retain, the fraction that are expected to have some evidentiary support;
- conflict recall.

These fixtures evaluate the verifier contract, not the language model's full real-world factuality.

### Retrieval

- Precision@K;
- Recall@K;
- reciprocal rank;
- nDCG@K;
- per-metric standard deviation across retrieval cases.

Retrieval experiments must record mode (`lexical`, `semantic`, `hybrid`), embedding model/version/dimensions when used, and K. Comparisons should keep the corpus and query set fixed.

### Security observability

- true-positive rate;
- false-positive rate;
- precision;
- accuracy;
- Wilson 95% intervals for TPR, FPR and overall accuracy.

The remote-content scanner is an observability control only. A low-risk score never makes retrieved content trusted and a high-risk score never grants or revokes tool authority.

### Per-run diagnostics

`GET /api/v1/runs/{run_id}/quality` reports descriptive run facts:

- citation-resolution rate;
- fraction of finalized claims with at least one persisted citation;
- fraction of finalized claims classified fully supported;
- claim/evidence/source counts;
- distinct source groups after canonical/content/domain grouping;
- support-state distribution;
- source/provider distribution;
- suspicious remote-content event count;
- deduplicated-source count;
- stage timing totals;
- queue wait and end-to-end run elapsed time when event timestamps are available;
- remaining evidence-gap count.

`distinct_source_group_count` is intentionally **not** named `independent_source_count`: identifiers, hashes, and domains cannot prove editorial independence.

## Current development gates

The CI development gate currently requires:

- routing macro-F1 >= 0.80;
- claim macro-F1 >= 0.60;
- unsupported-claim retention <= 0.10;
- conflict recall >= 0.70;
- mean retrieval Recall@5 >= 0.80;
- mean reciprocal rank >= 0.75;
- security-fixture TPR >= 0.80;
- security-fixture FPR <= 0.25.

Thresholds are regression tripwires, not claims that these values are sufficient for production.

## Comparing deterministic policy and Jev

Jev is metered and never activated by strict-free mode automatically. To run the same decision fixtures against Jev, use an explicitly authorized environment:

```bash
export JEV_API_KEY='...'
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite routing \
  --decision-provider jev \
  --no-gate \
  --report evals/reports/jev-routing.json
```

Use the same frozen fixtures/provider model and report both results. Do not select the winner by inspecting only favorable cases.

## Retrieval ablations

Offline lexical regression:

```bash
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite retrieval --retrieval-mode lexical
```

Explicit live semantic/hybrid experiment:

```bash
export GEMINI_API_KEY='...'
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite retrieval \
  --retrieval-mode hybrid \
  --embedding-provider gemini \
  --no-gate \
  --report evals/reports/hybrid-live.json
```

Live-provider runs are experiments, not CI requirements, because they consume provider quota and can change independently of the repository.

## Reporting rules

Every published ARES evaluation should include:

1. dataset provenance and size;
2. exact date/time window if the task is time-sensitive;
3. provider/model versions;
4. retrieval and budget settings;
5. denominator for every metric;
6. failures and excluded cases;
7. uncertainty or confidence intervals for sufficiently large samples;
8. whether the set is development, held-out, or external;
9. latency/cost/quota context separately from answer-quality metrics.

Do not publish the checked-in development-fixture scores as evidence that ARES is better than another research product.
