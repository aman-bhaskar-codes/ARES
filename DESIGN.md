---
version: alpha
colors:
  background: "#f3f6f6"
  surface: "#ffffff"
  surfaceMuted: "#f8fafa"
  ink: "#17323c"
  muted: "#6a7e86"
  line: "#dce6e8"
  accent: "#0e7180"
  accentSoft: "#e5f3f4"
  danger: "#a64137"
typography:
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
  editorial:
    fontFamily: "Georgia, serif"
rounded:
  control: "9px"
  panel: "14px"
spacing:
  compact: "8px"
  standard: "16px"
  section: "24px"
components:
  evidenceDrawer:
    width: "min(420px, 100vw)"
  focusRing:
    width: "3px"
    color: "#e2a241"
---

## Overview
ARES is a research instrument, not a marketing dashboard. The product register is restrained, evidence-first and editorial: dense enough for serious research while keeping the answer and its provenance legible. M08 extends this identity rather than redesigning it.

## Colors
Cool gray-green surfaces keep research content quiet; deep blue-green ink and teal indicate navigation/evidence actions. Amber is reserved for visible focus and evidence-region emphasis. Danger is reserved for destructive or failed states. Semantic meaning must never rely on color alone.

## Typography
Body and controls use the existing system-sans stack. Georgia is intentionally limited to research-question, answer and evidence-reading moments to distinguish primary reading from application chrome. Do not introduce a third decorative family for feature work.

## Layout
Desktop keeps the established left research rail, readable central answer column and optional right evidence drawer. Mobile collapses to one content column. Heavy tools such as PDF evidence rendering remain lazy-loaded. Long tables and evidence previews own their scrolling rather than forcing the page shell into a fixed-height layout.

## Elevation & Depth
Static application surfaces are mostly flat with borders. Shadows are reserved for raised composer, drawer/dialog and intentionally floating surfaces. Do not turn ingestion/status cards into decorative tiles.

## Shapes
Controls use modest rounded rectangles; panels use a slightly larger radius. Pills are reserved for compact status/meta labels. Evidence overlays remain rectangular because their geometry maps to original source regions.

## Components
M08 upload, ingestion readiness, table evidence and PDF/image evidence previews reuse the established tokens and button language. Upload is an async workflow with explicit queued/processing/partial/failed states, cancellation and retry. Evidence views always retain a text alternative and an authenticated path to the original asset.

## Do's and Don'ts
Do preserve keyboard focus, reduced-motion behavior, visible scrollbars, semantic buttons/links and status text. Do keep original-source navigation prominent. Do not hide extraction uncertainty, present OCR confidence as truth probability, use browser alert/confirm/prompt, inject untrusted HTML, or execute model-produced chart/parser code.
