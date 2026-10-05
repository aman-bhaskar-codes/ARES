# Evaluation reports

JSON files in this directory are generated artifacts and are intentionally ignored by Git because they contain run timestamps and provider/config-specific observations.

Regenerate the offline development report with:

```bash
PYTHONPATH=backend/src python evals/run_suite.py \
  --suite all \
  --decision-provider deterministic \
  --retrieval-mode lexical \
  --report evals/reports/regression_latest.json
```

For any result you publish externally, preserve the report separately together with dataset provenance, exact code commit, provider/model versions, date, budgets and the methodology in `docs/evaluation/METHODOLOGY.md`.
