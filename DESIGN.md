---
version: alpha
colors:
  background: "#fcfcf9"
  surface: "#ffffff"
  sidebar: "#f2f2ef"
  ink: "#252727"
  muted: "#656c6c"
  primary: "#167781"
  line: "#dedfda"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    lineHeight: 1.6
  heading:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    lineHeight: 1.2
rounded:
  control: "10px"
  composer: "22px"
spacing:
  unit: "4px"
components:
  composer:
    rounded: "22px"
    backgroundColor: "surface"
    textColor: "ink"
  navigation:
    backgroundColor: "sidebar"
    textColor: "muted"
  sendButton:
    backgroundColor: "primary"
    textColor: "surface"
---
# ARES design system

## Overview
ARES is a source-grounded research tool for people who want to ask, read, and follow citations. Familiar search-first placement takes inspiration from Perplexity while retaining the ARES name and an original compass mark. The signature is the quiet teal compass: direction through sources, with the answer taking the most space.

## Colors
`apps/web/src/styles/tokens.css` owns runtime values. This document mirrors the accepted light palette above; `colors.primary` maps to runtime `--accent`. Dark mode uses neutral charcoal (#191a1a background, #202222 sidebar), pale text (#eceeed), and teal (#7ccbd0). Never use green to imply that unassessed AI claims are verified. Color is paired with labels and selected-state semantics.

## Typography
Use the system sans stack for titles, controls, and reading. Home title is 38px desktop / 30px phone; question headings scale 26–34px. Answer body remains 16px with generous line spacing. Avoid uppercase implementation terminology in primary navigation.

## Layout
Desktop: 240px sidebar, 64px header, centered 800px reading column. Home has one question box and three optional starter prompts. Sources and tools are secondary disclosures within the composer; model selection and search depth stay visible. Sidebar displays ARES in capitals and groups new search and Library above history, memory/settings below it. A + immediately before Search opens the file picker in both question composers; Library contains only uploaded files, with one row per upload. Phones use a dismissible navigation overlay and wrapping composer controls.

## Elevation & Depth
Reading is flat. Only composer, floating menus, and drawers receive subtle elevation. Avoid nested cards and duplicate feature promotions.

## Shapes
Composer radius 22px; controls 10px; sources and status use compact pills. Shared icons use Lucide, consistent 18px stroke icons with visible labels; primary icon-only actions have accessible names and 44px targets. Inline citation chips retain their compact 27px reading treatment.

## Components
Composer owns question entry, source scope, tools, depth, model, and submit/stop. ModelPicker is the shared model control: a compact icon-and-name pill opens an upward menu with provider icons, Cloud/Local labels, availability, and a checkmark. It uses the existing surface, line, accent and elevation tokens in both themes; it never relies on an operating-system popup. WorkspaceShell owns navigation, history, theme/account, drawers and export. ResearchViewNav owns answer/source/compare/diagnostics/activity navigation. Advanced diagnostics open only on request. Answer keeps citation and uncertainty information visible without repeating tool configuration.

## Do's and Don'ts
Keep actions close to their content. Preserve direct chat deletion and existing server authorization. Do not invent tools, voice controls, upgrade buttons, or destinations. Do not duplicate tool cards on home. Preserve typed questions on failed submission; separate pending from long-running research. Respect reduced motion, keyboard focus, and both themes.


## Memory workspace
Memory uses an app-owned centered modal (980px maximum), not the narrow settings drawer. A stable header, three section tabs, one scrollable content area, and a utility footer for history/facts create a clear hierarchy. Preferences use their own save bar without a second stacked footer. History entries use readable summaries and expandable bullet findings; facts distinguish statement, recorded confidence, status, and source context. Preferences group research style, source preferences, and personal guidance into separate sections with a persistent save bar. All colors use existing runtime tokens (`--ink`, `--muted`, `--accent`, `--surface`, `--line`); no separate Memory palette. Phones retain the same section order and stack fields without horizontal overflow.
