// Renders the canonical "Seven Steps" Markdown document from the SAME data the
// wiki renders (web/src/wiki/content.ts). This is the single source of truth, so
// the GitHub doc and the frontend can never drift. Pure (no I/O, no clock) so a
// vitest drift-guard can compare its output byte-for-byte to the committed file.

import {
  DIMENSIONS,
  GENERATE_CFG,
  LOOP,
  PIPELINE,
  STEPS,
  THRESHOLDS,
  type ConfigItem,
  type Step,
} from "../src/wiki/content";

function kindLabel(step: Step): string {
  if (step.kind === "deterministic") return "Deterministic — no LLM; identical output for identical input.";
  if (step.kind === "judgment") return "LLM judgment — calls the configured model behind a gate.";
  return "Mixed — a deterministic part plus an LLM-proposed part.";
}

function cfgTable(rows: ConfigItem[]): string {
  return [
    "| Key | Default | Meaning |",
    "| --- | --- | --- |",
    ...rows.map((r) => `| \`${r.key}\` | \`${r.value}\` | ${r.meaning} |`),
  ].join("\n");
}

function stepSection(step: Step, ordinal: number): string {
  const n = String(ordinal).padStart(2, "0");
  const tools = step.tools.length ? step.tools.map((t) => `\`${t}\``).join(", ") : "—";
  return `## ${n}. ${step.name}

\`${step.kind}\` · \`${step.gate === "gated" ? "human gate" : "auto"}\`

**In one line.** ${step.summary}

### What it does

${step.detail}

### Why this step exists

${step.why}

### How it operates

Internally, \`${step.name}\` runs as its own compiled subgraph. Its phases, in order:

${step.how.map((h, i) => `${i + 1}. ${h}`).join("\n")}

### How it determines coverage

${step.coverage}

### Example

${step.example}

### What it drives next

${step.outcome}

### Reads & writes

| Field | Value |
| --- | --- |
| Kind | ${kindLabel(step)} |
| Gate | ${step.gateReason} |
| Input | ${step.inputs} |
| Output | ${step.outputs} |
| Tools | ${tools} |
`;
}

export function renderStepsMarkdown(): string {
  // A GitHub-renderable pipeline diagram: reuse the wiki's Mermaid source but
  // drop the `class …` role assignments, whose classDefs are injected only at
  // runtime in the app and would be undefined on GitHub.
  const pipelineMermaid = PIPELINE.mermaid
    .split("\n")
    .filter((line) => !line.trim().startsWith("class "))
    .join("\n");

  const overview = [
    "| # | Step | Kind | Gate | What it does |",
    "| --- | --- | --- | --- | --- |",
    ...STEPS.map(
      (s, i) =>
        `| ${String(i + 1).padStart(2, "0")} | [\`${s.name}\`](#${String(i + 1).padStart(2, "0")}-${s.name}) | ${s.kind} | ${
          s.gate === "gated" ? "human gate" : "auto"
        } | ${s.summary} |`
    ),
  ].join("\n");

  const dimensions = [
    "| Dimension | The question it answers | Measured by |",
    "| --- | --- | --- |",
    ...DIMENSIONS.map((d) => `| **${d.name}** | ${d.question} | \`${d.tool}\` |`),
  ].join("\n");

  return `---
title: The seven steps
kind: doc
layer: n/a
status: stable
owner: Juan.Kok
summary: How each of the seven pipeline steps operates, why it exists, and how it determines coverage.
id: seven-steps-doc
created: 2026-06-26
updated: 2026-06-30
visibility: public
canonical: true
---

# The seven steps

> **Generated file — do not edit by hand.** This document is rendered from
> \`web/src/wiki/content.ts\`, the single source of truth it shares with the
> pyverdex wiki (the "Understand → The seven steps" pages). Regenerate with
> \`cd web && npm run gen:docs\`.

pyverdex runs as a **deterministic LangGraph pipeline**: seven compiled subgraphs,
each with exactly one job. Line coverage alone proves a line *ran*, not that anything
*checked* it — so pyverdex measures seven dimensions instead of one, and only a step
that survives its gate counts. Steps are one of two kinds:

- **Deterministic** steps (\`lint\`, \`audit\`, \`report\`) measure. No model touches
  them, so identical input gives identical output — that is what makes the report
  trustworthy.
- **Judgment** steps (\`fix\`, \`generate\`, \`evaluate\`, \`integrate\`) ask an LLM to
  author or assess. Each one that changes your repo sits behind a **human gate**.

The spine of the pipeline is the **audit⇄generate loop**: \`audit\` measures and decides
whether coverage targets are met; while a gap remains and the cycle budget is unspent,
\`generate\` authors tests and hands control back to \`audit\` to re-measure.

## Pipeline at a glance

\`\`\`mermaid
${pipelineMermaid}
\`\`\`

${overview}

---

${STEPS.map((s, i) => stepSection(s, i + 1)).join("\n---\n\n")}
---

## The loop and its budgets

The \`generate → audit\` self-loop continues while coverage targets are unmet, the cycle
cap is not hit, and \`generate\` still has unhandled gaps; otherwise control falls through
to \`evaluate → integrate → report\`.

### Thresholds (\`config/default.yaml\`)

${cfgTable(THRESHOLDS)}

### Loop bounds

${cfgTable(LOOP)}

### Generate apply-mode

${cfgTable(GENERATE_CFG)}

## The seven coverage dimensions

The steps above produce these seven dimensions; \`report\` merges them into one verdict
(**fail** if any dimension failed, **warn** if any did not run, else **pass**).

${dimensions}
`;
}
