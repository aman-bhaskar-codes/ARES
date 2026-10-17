# ARES search workspace UX refresh — 17 October 2026

Implemented in the existing React application. This change uses Perplexity's familiar search-first hierarchy as a reference while retaining ARES branding, routes, authorization, and research contracts. No external Figma/Lovable project, push, or deployment was created.

| Before | After |
|---|---|
| Sources, model, depth, tools, and duplicate feature cards compete for attention | One question box, visible depth/model, expandable Sources/Tools, editable starter prompts |
| Letter logo, mixed emoji/tool icons, inconsistent color variables | Compass identity and favicon, Lucide icons, canonical neutral/teal tokens in both themes |
| History mixed with secondary workspace actions | New search / Library, scrollable threads, Memory / Settings; direct delete remains |
| Large answer card and repeated configuration badges | Flat reading column, compact metadata, explicit source/diagnostic/activity views |
| Always-visible source filters and full passage walls | Search first, expandable filters, short previews opening full evidence |
| Failed admission clears a question; copy offers no feedback | Failed questions retain their draft; copy success/failure is announced |
| Phone controls wrap unpredictably, hidden navigation stays keyboard reachable | Deliberate two-row toolbar, inert hidden navigation, focus containment, Escape and focus restoration |

`DESIGN.md` records visual decisions; `UX-CONTRACT.md` records ownership and behavior. Runtime token ownership remains `apps/web/src/styles/tokens.css`. Primary icon actions use 44px targets; inline citations retain their compact reading treatment. The Sources badge counts distinct source IDs, while the sources page separately counts passages.

## Verification

- Fresh frontend TypeScript check, all 25 Vitest tests (7 files), and production build passed. `git diff --check` passed. Existing optional chart chunk warning remains (~547 kB); main entry is ~174 kB.
- DESIGN.md official lint: zero errors; four token-reference warnings (runtime CSS remains canonical).
- Real browser checks against the existing API: home and saved chat restoration; source/tool disclosure exclusivity; source and tool state updates; Escape dismissal; editable starter prompt; missing-document validation retains draft and opens Library; source-search empty state and clear-filter recovery; opening and closing full evidence; copy reports success; diagnostics absent from the answer view.
- Desktop checks at 1440px and 1280px, phone at 390px: no horizontal page overflow. Phone navigation focuses Close on entry, Shift+Tab wraps to Settings, Escape restores the menu trigger. Light and dark palettes were inspected. Original dark preference restored after checks; viewport override reset.
- The browser's element inspector intercepted later clicks in the first tab; theme/copy checks were completed in an independent tab. No app workaround or security bypass was added.
- Existing viewer gates are retained; no viewer-account browser session or destructive chat deletion was exercised. No new model generation was run for this frontend-only change; this is not a fresh model-quality certification.

Screenshots: `/tmp/ares-ux-2026-10-17/desktop-dark.png`, `desktop-light.png`, and `answer-dark.png`. The temporary local API and frontend were stopped after verification, respecting the earlier request to turn services off.

## Upload placement follow-up

- Sidebar branding is now uppercase ARES.
- A + immediately before Search opens a native multiple-file picker in both main and follow-up composers. The existing server-capability accept policy is shared by the composer; read-only/busy/uploading states disable it. Ready direct text/PDF uploads are selected as document sources.
- Library now displays only uploaded file rows and their selection/status/actions. Removed its upload/drop zone, microphone controls, capability warnings, duplicate processing section, indexing diagnostics, and hashes. Assets and their extracted documents are joined into one row; incomplete uploads remain visible.
- Added three library regression tests for asset/document deduplication, standalone uploads, and retry/processing preservation. Fresh verification: 28 frontend tests, typecheck, production build, and whitespace check passed.
- Browser verification used the actual + file picker to upload a synthetic text file. Library showed it exactly once and the composer selected Documents (1). The follow-up composer also showed its + button. The synthetic upload was removed through the API after verification. Screenshot: `/tmp/ares-upload-ux/upload-library.png`.
- The API was already running at the start of this follow-up and was left untouched. Only the temporary frontend started for these checks was stopped.
