# M11 demo recording script

This document is a recording checklist, **not** a pre-recorded claim. Record against a real configured M11 release candidate or the clearly labelled keyless fixture profile. Never present fixture output as live research.

## 90-second evidence-inspection demo

Target workflow: compare a paper/table/media source, inspect a disagreement, open original evidence, and export a reproducible visual dataset.

1. **0–12 s — Ask.** Show the ARES workspace and submit the prepared comparison question. Keep the profile label visible (`Recorded demo` or live profile).
2. **12–25 s — Answer.** Show finalized claim blocks and a visible conflicting/partial state. Do not hide gaps.
3. **25–42 s — Inspect evidence.** Open one citation and show the original page/table/timestamp locator. For media, seek to the cited interval; for PDF/table, show the highlighted region/cell.
4. **42–58 s — Compare.** Open the comparison workspace. Select one matrix cell or graph relation and return to its evidence.
5. **58–73 s — Sourced numeric view.** Show a chart only when its values were validated from structured numeric evidence. Open the data-table alternative and trace one row/point to its source.
6. **73–84 s — Export.** Download the server-generated CSV and show the evidence/source lineage columns, without exposing private content beyond the prepared fixture.
7. **84–90 s — Limits.** Show the source-publication timeline label/partial-state notice and state that ARES preserves uncertainty rather than inventing missing dates or values.

## Engineering walkthrough

The longer walkthrough should include architecture boundaries, migration `0012`, RLS/authorization, deterministic visualization generation, lazy frontend modules, worker restart/failure recovery, a provider/browser/media degradation path, SBOM/release checksum, and one known limitation. Include exact environment/profile and release archive SHA-256 in the video description.

## Recording evidence to retain

- release archive SHA-256;
- ARES version/schema and configured profile;
- fixture/license manifest or permitted user-owned input list;
- date of recording;
- whether any provider calls were live;
- known limitation demonstrated;
- final public/private recording location after the user explicitly chooses publication.
