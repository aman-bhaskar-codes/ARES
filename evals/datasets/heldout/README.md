# Held-out evaluation boundary

This directory is intentionally not populated by the implementation agent.

The checked-in `evals/datasets/*.json` files are **development regression fixtures**. They are useful for preventing known routing, retrieval, support-classification, and indirect-injection regressions, but they are not an independent benchmark because the same development process can inspect and tune against them.

For a credible held-out evaluation:

1. Have a human reviewer or separate data-creation process build cases that were not used to tune ARES.
2. Freeze the cases before running comparative experiments.
3. Record dataset provenance, inclusion/exclusion criteria, annotation rules, and disagreements.
4. Keep provider/model/version, retrieval configuration, date, and quota/budget constant when comparing systems.
5. Report denominators and confidence intervals; do not collapse citation resolution, support, retrieval, latency, and cost into one opaque score.

Do not copy the development fixtures into this directory and call them held out.
