# ADR 003 — Native semantic CSS for the first UI slice

**Status:** accepted for the first vertical slice — 2026-10-02

## Context

The blueprint recommends Tailwind and Radix primitives. The current verified UI surface needs a shell, composer, progress timeline, claim citations and one evidence drawer. Adding a styling framework before the frontend dependency graph can even be installed in this execution environment would increase unverified surface and produce no functional capability.

## Decision

Use React plus semantic CSS tokens and native controls for the first slice. Keep focus states, responsive layout and citation/evidence behavior explicit. Do not add non-functional Radix/Tailwind dependencies merely to match the plan.

## Revisit trigger

When V1 adds menus, dialogs, upload flows and richer overlays, evaluate Radix for accessibility primitives and Tailwind only if it materially improves consistency/maintenance. The visual direction remains the blueprint's calm blue-gray/teal ARES identity.
