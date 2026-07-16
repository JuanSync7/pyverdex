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
  // whole-codebase coverage (the honest headline); overall_line_coverage_pct is
  // the legacy average over gap functions only, kept as a labelled secondary stat.
  whole_line_coverage_pct: number | null;
  whole_branch_coverage_pct: number | null;
  covered_lines: number | null;
  executable_lines: number | null;
  overall_line_coverage_pct: number | null;
  cross_package_edges: number;
  // function->function call-edge coverage (call-site-covered); null with no numerator
  edge_coverage_pct: number | null;
  function_edges_total: number;
  function_edges_exercised: number;
  mutation_kill_rate: number | null;
  weak_tests: number;
  dimensions: Dimension[];
  functions: FunctionCoverage[];
  edges: EdgeRecord[];
}

// Static-demo build (GitHub Pages): no backend, render a bundled sample report.
export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === "1";

const DEFAULT_BASE = (import.meta.env.VITE_API_BASE as string) || "";
const LS_KEY = "pyverdex_api_base";
const TOK_KEY = "pyverdex_token";

export function getApiBase(): string {
  return (typeof localStorage !== "undefined" && localStorage.getItem(LS_KEY)) || DEFAULT_BASE;
}
export function setApiBase(base: string): void {
  if (typeof localStorage !== "undefined") {
    if (base) localStorage.setItem(LS_KEY, base);
    else localStorage.removeItem(LS_KEY);
  }
}

// The server requires a per-process token on every sensitive endpoint. The
// bundled (same-origin) UI gets it from /api/session; a cross-origin client
// pastes the token printed at `pyverdex serve` startup.
export function getToken(): string {
  return (typeof localStorage !== "undefined" && localStorage.getItem(TOK_KEY)) || "";
}
export function setToken(t: string): void {
  if (typeof localStorage !== "undefined") {
    if (t) localStorage.setItem(TOK_KEY, t);
    else localStorage.removeItem(TOK_KEY);
  }
}
/** A backend is "live" when a base URL is configured, or when not a static build. */
export function hasBackend(): boolean {
  return !!getApiBase() || !STATIC_DEMO;
}

function u(path: string): string {
  return `${getApiBase()}${path}`;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const t = getToken();
  return { ...(extra || {}), ...(t ? { "X-Pyverdex-Token": t } : {}) };
}

// EventSource / WebSocket can't set headers, so they carry the token as a query.
function withToken(path: string): string {
  const t = getToken();
  if (!t) return u(path);
  const sep = path.includes("?") ? "&" : "?";
  return u(`${path}${sep}token=${encodeURIComponent(t)}`);
}

async function jpost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(u(path), {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

export function sampleReportUrl(): string {
  return `${import.meta.env.BASE_URL}sample-report.json`;
}

/** Pull the per-process token from a same-origin (or allowed) server. No-op on failure. */
export async function fetchSession(): Promise<boolean> {
  try {
    const r = await fetch(u("/api/session"));
    if (!r.ok) return false;
    const tok = (await r.json()).token as string | undefined;
    if (tok) {
      setToken(tok);
      return true;
    }
  } catch {
    /* server not reachable / cross-origin blocked — caller may prompt for a token */
  }
  return false;
}

export const api = {
  default: () => fetch(u("/api/default"), { headers: authHeaders() }).then((r) => r.json()),
  discover: (path: string) => jpost<ProjectInfo>("/api/discover", { path }),
  run: (path: string, apply: boolean, provider: string | null) =>
    jpost<{ run_id: string; info: ProjectInfo }>("/api/run", {
      path,
      apply,
      provider: provider || null,
    }),
  file: (root: string, path: string) =>
    // Token goes in the header only — never the URL — so it can't leak to the
    // server access log / browser history. (EventSource below must use a query.)
    fetch(u(`/api/file?root=${encodeURIComponent(root)}&path=${encodeURIComponent(path)}`), {
      headers: authHeaders(),
    }).then((r) => r.json()),
  eventsUrl: (runId: string) => withToken(`/api/runs/${runId}/events`),
};
