# M11 external tester protocol

M11's external-test gate is intentionally separate from development regression and from the independently authored held-out benchmark. The goal is to discover repeated usability, provenance, recovery and setup failures using real tester tasks, not to manufacture a score.

## Participants

Recruit **3–5 people who did not implement M11**. Record only the participant label needed for the study (for example `T01`); do not commit private contact details. Each tester should use at least one task they genuinely care about and may use their own permitted files/media.

## Required journeys

Each tester should complete, where applicable:

1. ask a research question and inspect at least two citations;
2. open one precise locator (page region, table cell or media timestamp when their task provides one);
3. inspect a comparison/visual artifact and trace one value or edge back to evidence;
4. export an answer and, when available, a visualization CSV;
5. reload a stable run/evidence deep link;
6. use the core path with keyboard navigation at least once;
7. report any unclear partial/degraded state rather than retrying until it disappears.

At least one controlled engineering session must also demonstrate a worker/browser/media failure or restart and the resulting recovery/partial-state behavior.

## Failure log

Create one record per meaningful observation. Do not record secrets or private source content.

```json
{
  "tester_id": "T01",
  "task_id": "task-1",
  "environment": "browser/os + ARES profile",
  "journey": "citation inspection",
  "severity": "blocker|major|minor|observation",
  "expected": "what the tester reasonably expected",
  "observed": "what happened",
  "reproducible": true,
  "evidence": "sanitized screenshot/log/run id if permitted",
  "resolution": "open|fixed|accepted limitation",
  "issue_ref": "optional repository issue/PR"
}
```

## Release rule

Repeated blocker/major failures are fixed or explicitly accepted with a documented limitation before promotion. A tester count alone is not a pass. Preserve the sanitized failure log and the exact release candidate tested.
