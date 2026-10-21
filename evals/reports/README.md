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

The 2026-10-07 local smoke checks exercised public research questions through Gemini and Ollama, model selection, citation-link resolution, chat deletion and the optional diagnostics view. Some attempts were partial because of provider quota limits. These were operational examples, not calibrated faithfulness or research-quality measurements; their screenshots and raw run reports are generated artifacts and are no longer tracked.
