# Hardening evaluation results — 2026-10-14

The hardening pass freezes 112 development claim cases and 50 graded retrieval scenarios. One hundred new claim cases are explicitly synthetic invariants on fictional systems, designed to protect numeric, partial-support, conflict and missing-evidence behavior. Forty new retrieval scenarios are synthetic topical references. Their perfect regression scores are not evidence of scientific generalization.

Three deterministic repeats of the development suites passed the offline CI gates. Claim macro F1 and annotation-based citation precision were 1.0; retrieval recall@5 and graded nDCG@5 were 1.0. Run-level standard deviation was 0.0, as expected for deterministic inputs and algorithms.

## Independent SciFact sample

A frozen sample of 100 externally annotated SciFact dev records was selected before scoring and was not used to change the checker. Three deterministic repeats gave:

| Measure | Mean | Run std |
|---|---:|---:|
| Exact ARES support-label accuracy | 0.260 | 0.000 |
| Four-label macro F1 | 0.152 | 0.000 |
| Annotation-based citation precision | 0.673 | 0.000 |
| Annotation-based citation recall | 0.282 | 0.000 |
| Unsupported claim retention rate | 0.438 | 0.000 |
| Bounded-candidate retrieval recall@5 | 0.993 | 0.000 |
| Bounded-candidate graded nDCG@5 | 0.975 | 0.000 |

The scientific support suite **fails** the existing quality thresholds. It is reported separately and non-blockingly; the CI development regression thresholds were not lowered. The dominant weakness is semantic support assessment by lexical/numeric heuristics. A calibrated NLI/semantic checker with independent annotations is required before claiming scientific faithfulness. This pass does not train model weights or claim to solve that research problem.

Citation precision here compares per-passage heuristic support predictions to annotated evidence sentences. It is stronger than checking whether a citation ID resolves, but it is **not** a generated-answer evaluation. Retrieval ranks a small known candidate set, not the complete scientific corpus. Public dev examples may also appear in model training; independent authoring does not imply contamination-free model evaluation.

Raw repeated-run reports are generated artifacts, intentionally excluded from Git. The runner reports run means/std and also per-query variability. Preserve code revision, source archive checksum, selection and model configuration with any external publication.
