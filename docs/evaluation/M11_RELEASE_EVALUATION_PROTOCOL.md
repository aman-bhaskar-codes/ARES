# M11 / V2 release evaluation protocol

M11 adds release proof, not a claim that development fixtures are an independent benchmark. The external evaluation set must be authored independently from implementation/tuning and frozen before comparative runs.

## Required evaluation slices

Target at least 100 research questions across web, academic, software, document/table, audio and short-video tasks. Include conflict, insufficient-evidence, date-window, numeric/unit, multilingual, malformed-media and authorization-sensitive cases. Report each slice separately when sample size allows.

Compare the same frozen tasks under:

1. V1/M06-compatible baseline;
2. V2 text-only/local retrieval;
3. V2 local multimodal;
4. optional V2 Gemini-assisted mode.

Record ablations for local embeddings, reranking (only if enabled) and semantic checking. Keep provider/model versions, source snapshot/date range, budgets and hardware fixed within a comparison.

## Human annotation contract

At least one reviewer who did not tune the implementation must label claim support and locator validity. Disputed cases are retained with adjudication notes rather than silently removed. LLM judging may triage but is never the sole ground truth for its own generated outputs.

For every externally checkable answer claim record: expected support state, supporting segment IDs, contrary segment IDs, numeric/unit correctness where applicable, locator validity, and whether abstention was required.

## Core metrics

- citation resolution rate;
- human-labeled support precision/recall;
- numeric accuracy and incompatible-unit rejection;
- locator validity/alignment;
- required-facet coverage;
- contradiction precision/recall;
- OCR/ASR error by slice;
- unsupported-answer retention/abstention;
- queue time, TTFE, model time, TTFA and final answer time;
- cold/warm resource usage and failure counts.

Do not use first spinner paint as a research-latency metric.

## Visualization checks

Every displayed/exported chart point and numeric table value must resolve to the authorized persisted evidence claimed in lineage. Malicious/oversized specs must be rejected, graph bounds must hold, CSV formula prefixes must be escaped, and the text/table fallback must retain the same information.

## Browser/accessibility matrix

Run the core deep-link journey with Chromium, Firefox and WebKit; keyboard-only navigation; screen-reader basics; 320 px viewport; 200% zoom; reduced motion; light/dark themes; and a replay containing 200+ activity events. `scripts/e2e_m11.py` is a bounded browser smoke, not a substitute for manual screen-reader review.

## Stop conditions

Do not promote V2 while a reproducible cross-tenant leak, unchecked visible assertion path, unbounded media/browser execution, visualization without provenance, destructive migration loss or unintended billable fallback remains.
