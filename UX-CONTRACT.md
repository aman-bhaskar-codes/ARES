# ARES interaction contract

Visual identity: [DESIGN.md](DESIGN.md). English-first interface; browser date formatting is retained.

| Capability | Canonical owner | Behavior / verification |
|---|---|---|
| Question form | research/Composer.tsx | Enter submits; Shift+Enter adds a line; IME composition never submits. Trim empty questions. Pending admission disables repeat submission. Failed admission retains the draft. |
| Uploads / Library | Composer + uploadPolicy + WorkspacePanel | + beside Search opens a multiple-file picker; accepted types follow server capabilities. Ready direct uploads become selected document sources. Library lists uploads once, joining assets to derived documents and retaining processing/failed uploads. |
| Sources and tools | Composer + SourceScopeControls | Native disclosures, keyboard operable, Escape/outside click closes. At least one source required. Tool state uses aria-pressed. Read-only viewers cannot change settings. |
| Model selection | research/ModelPicker.tsx | Authored menu shared by home and follow-up composers. Catalog controls availability; unavailable choices are disabled. Arrow/Home/End navigation, Enter selection, Escape/outside dismissal, focus restoration; Cloud/Local labels remain visible. |
| History / CRUD | WorkspaceShell + API client | New search returns home and resets sources to Web with no selected documents; history restores the run and its source scope. Direct delete retains current authorized API behavior and reports errors. |
| Memory | workspace/MemoryPanel.tsx + memory.css | App-owned native dialog with focus containment/return, Arrow/Home/End tabs, visible loading/errors/retry and view-only controls. Search ignores stale responses after clear/tab changes. Status filtering preserves unsaved preferences. Deletion, organization and discarding edits require app-owned confirmation; Save has pending/error/success states. Export covers loaded recent entries, not an unlimited history. |
| Drawer | WorkspaceShell + workspace/evidence panels | Library and citation inspection use existing drawers and close controls. Mobile navigation dismisses via close, Escape, or scrim. |
| Async / feedback | React Query + useRunStream | Loading history is distinguished from empty history; error offers retry. Failed admission displays global alert and preserves draft. Stop cancels the current run. No success claim on HTTP failure. |
| Navigation | ResearchViewNav | Answer is default; sources, comparison, diagnostics and activity are explicit views. No diagnostics panel automatically inserted in an answer. |
| Scrollbar / focus | global base.css | Visible theme-aware scrollbar, visible keyboard focus, reduced motion. No horizontal page overflow at 390px or 1440px. |
| Account / export | WorkspaceShell | Account menu exposes workspace/role; Escape and outside click dismiss. Export disabled until a completed/partial run and for viewers. |

Verification: frontend typecheck, Vitest, production build; real browser desktop/mobile checks of home, settings disclosures, theme, history/answer navigation and read-only-safe controls. These UI checks do not certify model answer quality.
