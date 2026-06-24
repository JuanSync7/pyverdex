import { describe, expect, it } from "vitest";
import {
  APPLY_MODE_LOOP,
  AUDIT_GENERATE_LOOP,
  BACKENDS,
  DIMENSIONS,
  getStep,
  PIPELINE,
  STEPS,
  THRESHOLDS,
  TOOLS,
} from "./content";

describe("wiki content model", () => {
  it("covers the seven coverage dimensions with a question + tool each", () => {
    const keys = DIMENSIONS.map((d) => d.key);
    expect(keys).toEqual([
      "line",
      "branch",
      "edge",
      "mutation",
      "assertion",
      "integration",
      "lint",
    ]);
    for (const d of DIMENSIONS) {
      expect(d.question.endsWith("?")).toBe(true);
      expect(d.tool.length).toBeGreaterThan(0);
      expect(d.why.length).toBeGreaterThan(0);
      expect(d.example.length).toBeGreaterThan(0);
    }
  });

  it("describes the seven pipeline steps in engine order", () => {
    expect(STEPS.map((s) => s.id)).toEqual([
      "lint",
      "fix",
      "audit",
      "generate",
      "evaluate",
      "integrate",
      "report",
    ]);
  });

  it("marks generate as a gated judgment step that uses the mutation gate", () => {
    const gen = getStep("generate")!;
    expect(gen.kind).toBe("judgment");
    expect(gen.gate).toBe("gated");
    expect(gen.tools).toContain("mutation_runner");
  });

  it("marks audit as the deterministic measurement core", () => {
    const audit = getStep("audit")!;
    expect(audit.kind).toBe("deterministic");
    expect(audit.outputs).toMatch(/coverage_met/);
  });

  it("includes the deterministic mutation_runner tool feeding the mutation dimension", () => {
    const mut = TOOLS.find((t) => t.name === "mutation_runner");
    expect(mut?.feeds).toContain("mutation");
  });

  it("offers a no-API-key claude-code backend", () => {
    const cc = BACKENDS.find((b) => b.id === "claude-code");
    expect(cc?.apiKey).toBe("none");
  });

  it("pins the mutation kill-rate threshold at 1.0", () => {
    const kill = THRESHOLDS.find((t) => t.key === "mutation_kill_rate");
    expect(kill?.value).toBe("1.0");
  });

  it("keeps the pipeline diagram in sync with every engine stage", () => {
    expect(PIPELINE.mermaid.startsWith("flowchart")).toBe(true);
    for (const s of STEPS) {
      expect(PIPELINE.mermaid).toContain(s.id);
    }
    // the audit⇄generate loop-back edge must exist (generate returns to audit)
    expect(PIPELINE.mermaid).toMatch(/generate[^\n]*audit/);
  });

  it("models the apply-mode and after_audit loops as mermaid flowcharts", () => {
    for (const d of [APPLY_MODE_LOOP, AUDIT_GENERATE_LOOP]) {
      expect(d.mermaid.startsWith("flowchart")).toBe(true);
      expect(d.caption.length).toBeGreaterThan(0);
    }
    expect(APPLY_MODE_LOOP.mermaid).toMatch(/mutation/i);
    expect(AUDIT_GENERATE_LOOP.mermaid).toMatch(/coverage met/i);
  });
});
