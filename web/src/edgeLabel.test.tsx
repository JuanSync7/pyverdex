import { describe, expect, it } from "vitest";
import { edgeLabel, Report, systemLabel } from "./api";

const base: Report = {
  overall_status: "pass",
  total_functions: 0,
  functions_with_line_gaps: 0,
  boundary_gaps: 0,
  whole_line_coverage_pct: null,
  whole_branch_coverage_pct: null,
  covered_lines: null,
  executable_lines: null,
  overall_line_coverage_pct: null,
  cross_package_edges: 3,
  edge_coverage_pct: null,
  function_edges_total: 0,
  function_edges_exercised: null,
  boundary_coverage_pct: null,
  boundaries_total: 0,
  boundaries_covered: 0,
  log_path_coverage_pct: null,
  mutation_kill_rate: null,
  weak_tests: 0,
  dimensions: [],
  functions: [],
  edges: [],
};

describe("edgeLabel", () => {
  it("shows the function->function coverage ratio when edges exist", () => {
    expect(
      edgeLabel({ ...base, function_edges_total: 4, function_edges_exercised: 3, edge_coverage_pct: 75 }),
    ).toBe("edges 75% (3/4)");
  });

  it("shows map-only when there is no coverage numerator", () => {
    expect(edgeLabel({ ...base, function_edges_total: 4, edge_coverage_pct: null })).toBe(
      "4 edges mapped",
    );
  });

  it("falls back to the cross-package count when no function edges are mapped", () => {
    expect(edgeLabel(base)).toBe("3 edges");
  });
});

describe("systemLabel", () => {
  it("returns null when no external boundaries were detected", () => {
    expect(systemLabel(base)).toBeNull();
  });

  it("shows the boundary coverage ratio when boundaries exist", () => {
    expect(
      systemLabel({ ...base, boundaries_total: 4, boundaries_covered: 1, boundary_coverage_pct: 25 }),
    ).toBe("system 25% (1/4)");
  });
});
