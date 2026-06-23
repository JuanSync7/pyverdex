export interface ProjectInfo {
  project_root: string;
  source_root: string;
  test_root: string;
  source_files: string[];
  test_files: string[];
  source_count: number;
  test_count: number;
  has_tests: boolean;
}

export interface Dimension {
  name: string;
  status: "pass" | "fail" | "warn" | "not_run" | "unknown";
  headline: string;
}

export interface FunctionCoverage {
  module: string;
  function_name: string;
  tier: string;
  is_boundary: boolean;
  line_coverage_pct: number | null;
  missing_lines: number[];
  branch_count: number | null;
  mutation_kill_rate: number | null;
}

export interface EdgeRecord {
  caller_module: string;
  callee_module: string;
  call_site_line: number | null;
}

export interface Report {
  overall_status: string;
  total_functions: number;
  functions_with_line_gaps: number;
  boundary_gaps: number;
  overall_line_coverage_pct: number | null;
  cross_package_edges: number;
  mutation_kill_rate: number | null;
  weak_tests: number;
  dimensions: Dimension[];
  functions: FunctionCoverage[];
  edges: EdgeRecord[];
}

// Static-demo build (GitHub Pages): no backend, render a bundled sample report.
export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === "1";

const DEFAULT_BASE = (import.meta.env.VITE_API_BASE as string) || "";
const LS_KEY = "pyverify_api_base";

export function getApiBase(): string {
  return (typeof localStorage !== "undefined" && localStorage.getItem(LS_KEY)) || DEFAULT_BASE;
}
export function setApiBase(base: string): void {
  if (typeof localStorage !== "undefined") {
    if (base) localStorage.setItem(LS_KEY, base);
    else localStorage.removeItem(LS_KEY);
  }
}
/** A backend is "live" when a base URL is configured, or when not a static build. */
export function hasBackend(): boolean {
  return !!getApiBase() || !STATIC_DEMO;
}

function u(path: string): string {
  return `${getApiBase()}${path}`;
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(u(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

export function sampleReportUrl(): string {
  return `${import.meta.env.BASE_URL}sample-report.json`;
}

export const api = {
  default: () => fetch(u("/api/default")).then((r) => r.json()),
  discover: (path: string) => jpost<ProjectInfo>("/api/discover", { path }),
  run: (path: string, apply: boolean, provider: string | null) =>
    jpost<{ run_id: string; info: ProjectInfo }>("/api/run", {
      path,
      apply,
      provider: provider || null,
    }),
  file: (root: string, path: string) =>
    fetch(u(`/api/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`)).then(
      (r) => r.json()
    ),
  eventsUrl: (runId: string) => u(`/api/runs/${runId}/events`),
};
