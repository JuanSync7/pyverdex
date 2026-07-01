---
title: docs — agent rules
kind: rules
layer: n/a
status: stable
owner: Juan.Kok
summary: Local rules for documentation.
id: docs-agent
created: 2026-06-26
updated: 2026-06-26
visibility: internal
canonical: true
---
# Agent rules — `docs/`

- Every `.md` here needs valid frontmatter (the `check_A` gate gives every doc a
  unique `id`, a `kind`, and a `visibility`).
- A decision goes in `adr/NNNN-title.md` (`kind: adr`, status
  `proposed|accepted|superseded`); a how-to in `guides/`; a contract in
  `reference/`.
- `SEVEN_STEPS.md` is **generated** from `web/src/wiki/content.ts`
  (`cd web && npm run gen:docs`) — edit the source, not the output.
