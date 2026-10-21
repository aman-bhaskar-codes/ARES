# Held-out evaluation boundary

`scifact/` contains a frozen sample of 100 externally authored, evidence-labeled SciFact development records. The source archive checksum, exact selection, original labels, licensing and attribution are in `scifact/manifest.json`. These records were not used to tune ARES during this hardening pass. They are publicly available, so they cannot establish model pretraining contamination freedom.

```bash
PYTHONPATH=backend/src uv run --project backend python evals/run_suite.py \
  --suite claims --dataset-dir evals/datasets/heldout/scifact \
  --dataset-kind scifact_external_holdout --repeats 3 --no-gate
PYTHONPATH=backend/src uv run --project backend python evals/run_suite.py \
  --suite retrieval --dataset-dir evals/datasets/heldout/scifact \
  --dataset-kind scifact_external_holdout --repeats 3 --no-gate
```

The `--no-gate` flag reports threshold failures without hiding them or using them to block unrelated engineering checks. Scientific support performance is currently poor; see `docs/evaluation/HARDENING_RESULTS.md`. The normal development regression suite remains threshold-gated in CI.

The retrieval sample has annotated relevant abstracts plus 12 bounded distractors per query. It measures candidate ranking, not full-corpus retrieval and not a BEIR score. The holdout is academic only and does **not** satisfy the existing M11 multimodal release gate. Keep that gate's independent cross-modality dataset requirement separate.

Do not tune on this frozen sample and continue calling it held out. New model/provider comparisons need a fresh split, fixed budgets, annotation calibration and contamination documentation.
