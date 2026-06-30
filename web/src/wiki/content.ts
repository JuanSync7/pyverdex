// Single source of truth for the wiki's prose-as-data.
//
// Every fact here is drawn from the pyverdex source — `config/default.yaml`,
// `src/pyverdex/tools/adapters.py`, the skill subgraphs, and `docs/ARCHITECTURE.md`
// — NOT invented. Pages are thin renderers over this module, and the tests
// assert against it, so the wiki cannot silently drift from the engine.

export type DimensionKey =
  | "line"
  | "branch"
  | "edge"
  | "mutation"
  | "assertion"
  | "integration"
  | "lint";

export interface Dimension {
  key: DimensionKey;
  name: string;
  /** The plain-English question this dimension answers. */
  question: string;
  /** The tool that measures it. */
  tool: string;
  /** Why line coverage alone misses this. */
  why: string;
  /** A tiny, concrete junior-friendly illustration. */
  example: string;
}

export const DIMENSIONS: Dimension[] = [
  {
    key: "line",
    name: "Line coverage",
    question: "Did each line of code actually run while the tests executed?",
    tool: "coverage.py + coverage_analyzer",
    why: "It is the baseline everyone already measures — necessary, but it only proves a line was reached, not that anything about it was checked.",
    example:
      "A test that calls `price(10)` and asserts nothing still marks every line of `price` as covered. 100% line coverage, zero verification.",
  },
  {
    key: "branch",
    name: "Branch coverage",
    question:
      "Which branches (if/else, loops, except) exist in each function, and are they all exercised?",
    tool: "branch_mapper",
    why: "A function can be 100% line-covered while a whole `else:` path is never taken — the line counts as covered by the `if` side.",
    example:
      "`if user.is_admin: ... else: ...` — testing only the admin path leaves the non-admin branch unverified even at 100% lines.",
  },
  {
    key: "edge",
    name: "Edge / function-to-function",
    question:
      "Which cross-package call seams (function A → function B) are actually wired together by a test?",
    tool: "coverage_analyzer --edges",
    why: "Unit tests with mocks cover each function in isolation but never prove the *connections* between packages hold — the integration seams.",
    example:
      "`api.checkout()` calls `pricing.total()` calls `inventory.reserve()`. Three green unit tests, but no test exercises the real chain end-to-end.",
  },
  {
    key: "mutation",
    name: "Mutation kill-rate",
    question:
      "If the code is deliberately corrupted, do the tests notice and fail?",
    tool: "mutation_runner",
    why: "This is the real test of assertion *strength*. Weak tests pass against broken code; strong tests fail. The single best signal that coverage is honest.",
    example:
      "Flip `a + b` to `a - b`. If every test still passes, the suite proves nothing about that line — a 'surviving mutant'. pyverdex's generate gate requires a 100% kill-rate.",
  },
  {
    key: "assertion",
    name: "Assertion quality",
    question: "Are the tests making meaningful checks, or are they padding?",
    tool: "assertion_quality",
    why: "Counts and weighs assertions per test so 'assert True' / no-assert tests are flagged instead of inflating the coverage number.",
    example:
      "A test with one trivial `assert result is not None` scores low; a test asserting the exact value, type, and side effects scores high. Minimum: 2 real assertions, score ≥ 0.5.",
  },
  {
    key: "integration",
    name: "Integration / system",
    question: "Are real services exercised end-to-end, or is everything mocked?",
    tool: "evaluate / integrate (judgment)",
    why: "A suite can be all green while every external dependency is faked — so it never proves the system actually works wired together.",
    example:
      "An over-mocked test asserts your mock returned what you told it to. The `evaluate` stage judges whether tests touch real seams; `integrate` proposes ones that do.",
  },
  {
    key: "lint",
    name: "Lint / security / secrets",
    question: "Is the code statically healthy — style, likely bugs, leaked secrets?",
    tool: "lint_reporter + secret_scanner",
    why: "The cheap static floor: catch the obvious defects and committed credentials before spending effort on dynamic measurement.",
    example:
      "An unused import or a hard-coded API key never shows up in coverage %, but `lint_reporter` and `secret_scanner` catch them in the first stage.",
  },
];

// --------------------------------------------------------------------------
// Pipeline steps — one compiled LangGraph subgraph each (skills/*.py).
// --------------------------------------------------------------------------

export type StepKind = "deterministic" | "judgment" | "mixed";
export type GateMode = "auto" | "gated";

export interface Step {
  id: string;
  name: string;
  kind: StepKind;
  /** Default gate from config/default.yaml. */
  gate: GateMode;
  /** One-line role in the pipeline (index + lede). */
  summary: string;
  /** What happens inside, in one paragraph. */
  detail: string;
  /** Why this step exists — the problem it solves and when it earns its place. */
  why: string;
  /** How it operates: the ordered internal phases of its own subgraph. */
  how: string[];
  /** How it relates to — or actually determines — coverage. */
  coverage: string;
  /** What state or decision this step drives downstream. */
  outcome: string;
  /** Why it runs unattended (auto) or pauses for human approval (gated). */
  gateReason: string;
  /** A concrete, junior-friendly illustration. */
  example: string;
  /** Deterministic tools this step drives (adapter/vendored names). */
  tools: string[];
  inputs: string;
  outputs: string;
}

export const STEPS: Step[] = [
  {
    id: "lint",
    name: "lint",
    kind: "deterministic",
    gate: "auto",
    summary: "Static health floor — style, likely bugs, leaked secrets.",
    detail:
      "Runs the linters over the source tree and scans for committed secrets. No LLM. It is the cheap first pass that catches defects you should never pay dynamic-analysis time to find.",
    why: "Cheapest signal first. Static defects (style, type errors, security smells, dead code) and committed secrets need neither the test suite nor a model to find — a parser sees them. Catching them here means you never spend coverage or LLM budget on a problem the AST already knows about, and it hands `fix` a concrete worklist.",
    how: [
      "SCAN — walk the source root for Python modules.",
      "RUN-LINTERS — drive the vendored lint_reporter, which fans out to ruff (style + likely bugs), mypy (types), bandit (security/SAST) and vulture (dead code), plus the secret scanner.",
      "AGGREGATE — fold every finding into one typed LintReport (issue and error counts per tool).",
      "EMIT — publish lint_report into graph state. It classifies only; it never fails the build on findings.",
    ],
    coverage:
      "Feeds the lint dimension of the unified report (pass when zero errors, fail on any error). It is orthogonal to line/branch/mutation — the static floor, true whether or not a single test ran.",
    outcome:
      "A lint_report in state that `fix` acts on and `report` rolls up. No gate, so the run flows straight into `fix`.",
    gateReason:
      "auto — it only reads and classifies; it changes nothing on disk, so there is nothing to approve.",
    example:
      "An unused import or a hard-coded API key never moves the coverage %, but vulture and the secret scanner flag both here, before any test runs.",
    tools: ["lint_reporter", "secret_scanner"],
    inputs: "source tree",
    outputs: "lint findings + secret hits (the lint dimension)",
  },
  {
    id: "fix",
    name: "fix",
    kind: "mixed",
    gate: "gated",
    summary: "Auto-fix the mechanical, propose a plan for the rest.",
    detail:
      "Applies `ruff --fix` for the safely-automatable findings (deterministic), then asks the LLM for a remediation *plan* for what is left. Propose-only: it does not rewrite your logic unattended, which is why it is gated for human approval by default.",
    why: "Lint findings split in two: mechanical ones a tool rewrites safely, and judgement ones that need a human. `fix` clears the mechanical class automatically and turns the rest into a reviewable plan — so trivial defects are gone before measurement without ever silently rewriting your logic.",
    how: [
      "RUFF-FIX — run `ruff check --fix` over the source: only ruff's safe, mechanical autofixes, applied deterministically.",
      "RE-LINT — re-run the linter to confirm what remains and refresh lint_report, so the fix is verified rather than assumed.",
      "LLM-PLAN — for the non-ruff remainder (mypy/bandit/vulture), if a backend is configured, ask the model for a concise file-by-file remediation plan — prose, never code patches.",
      "GATE — pause at the human gate (gated by default) so a person approves before the run continues.",
    ],
    coverage:
      "Indirect. By clearing trivial lint it lifts the lint dimension; it authors no tests and moves no line/branch/mutation number.",
    outcome:
      "A fix_report (ruff result + remaining count + optional remediation plan) and a refreshed lint_report. Control then passes to `audit`.",
    gateReason:
      "gated — it can modify files (ruff --fix) and proposes changes to your code, so it stops for approval by default; the non-mechanical part is propose-only and never hand-edited unattended.",
    example:
      "ruff auto-removes the unused import; the mypy type error and a bandit `subprocess(shell=True)` finding become a short plan you approve, not a silent rewrite.",
    tools: ["lint_reporter (ruff --fix)"],
    inputs: "lint findings",
    outputs: "applied trivial fixes + an LLM remediation plan (proposed)",
  },
  {
    id: "audit",
    name: "audit",
    kind: "deterministic",
    gate: "auto",
    summary: "The measurement core — and the pivot of the loop.",
    detail:
      "Runs the test suite under coverage.py, then measures per-function line gaps, branch structure, boundary tiers, cross-package edges, and assertion quality. It computes whether every function meets its tier target and sets `coverage_met`. This is where the audit⇄generate loop decides whether to keep going.",
    why: "This is the heart of pyverdex. Line coverage alone lies — it proves a line ran, not that anything checked it. `audit` measures every dimension a single % hides, and it is the only step that decides whether the suite is actually good enough. That verdict — `coverage_met` — is the pivot the whole loop turns on.",
    how: [
      "COLLECT — run the target test suite under coverage.py (best-effort) to produce a .coverage data file.",
      "SNAPSHOT — derive per-function line gaps (coverage_analyzer), cross-package call edges (--edges), branch structure (branch_mapper), boundary/critical tiers (boundary_classifier), assertion quality (assertion_quality) and log-path coverage (log_contract_validator), each from its own deterministic tool.",
      "SCORE — for every function compare its line % against its tier target (critical 95 / standard 85 / cold 70), mark anything below as a gap, rank modules worst-first and flag critical modules.",
      "EMIT — set coverage_met (true only when nothing is below its tier target) and write the gap report + coverage state.",
    ],
    coverage:
      "This is where coverage is determined. It computes the multi-dimensional measurement for every function and the pass/fail of the line dimension against tier thresholds; every downstream step reads its numbers.",
    outcome:
      "audit_gap_report, coverage_state, and the coverage_met boolean. The after_audit edge then routes to `generate` (a gap remains and budget is left) or falls through to evaluate/integrate/report.",
    gateReason:
      "auto — pure measurement, deterministic and read-only. There is nothing to approve, and identical inputs always yield identical numbers.",
    example:
      "A function is 100% line-covered, but its `else:` branch never runs and its only test asserts nothing — audit's branch and assertion dimensions surface exactly what the line % hid.",
    tools: [
      "coverage.py",
      "coverage_analyzer",
      "branch_mapper",
      "boundary_classifier",
      "coverage_analyzer --edges",
      "assertion_quality",
      "log_contract_validator",
    ],
    inputs: "source + test suite",
    outputs: "per-function multi-dimensional measurements + coverage_met",
  },
  {
    id: "generate",
    name: "generate",
    kind: "judgment",
    gate: "gated",
    summary: "Author tests for the gaps — and prove they are strong.",
    detail:
      "For each gap the audit found, the LLM authors a candidate test. In apply-mode it writes the test, runs it green, then gates it on `mutation_runner`: the test must kill 100% of mutants or it is re-strengthened with the surviving mutants fed back to the model. Only tests that pass the mutation gate stick — then `audit` re-measures. This is the loop that actually closes gaps.",
    why: "Measuring a gap doesn't close it. `generate` is the step that actually moves coverage — it authors the missing tests. But an authored test is only worth keeping if it is strong, so each must pass the mutation gate (kill 100% of injected bugs) before it counts. This is the loop that turns a red audit green.",
    how: [
      "SELECT — pick the unhandled below-target gaps, up to loop.max_gaps_per_cycle (10).",
      "AUTHOR — the LLM writes one pytest module per gap (system prompt distilled from the assertion-policy + layer-unit knowledge), requiring ≥ assertion_min meaningful assertions.",
      "GATE — human approval (gated by default) before anything is written.",
      "APPLY (only when generate.apply=true) — write the test, check it parses, run it green, then run mutation_runner on the target function; it must reach mutation_kill_rate (1.0) or the surviving mutants are fed back and the test is re-authored, bounded by restrengthen_attempts. Only passing tests stick and the gap is marked handled.",
      "RE-MEASURE — control returns to `audit`, which re-runs and updates coverage_met.",
    ],
    coverage:
      "The only step that raises coverage — it closes line gaps with new tests, and the mutation gate guarantees those tests actually verify, driving the mutation dimension to a 100% kill-rate.",
    outcome:
      "Candidate tests (apply-mode: written to pyverdex_generated/, mutation-gated, recorded with kill-rate + gate status), gen_handled updated, and the audit⇄generate loop either continues or exhausts at loop.max_cycles.",
    gateReason:
      "gated — it writes test files and runs model-authored code, a material change to your repo, so it stops for approval. Off by default (apply=false): propose-only, nothing written unattended.",
    example:
      "audit finds price() 60% covered; generate writes a test, but flipping `a + b` → `a - b` still passes, so a mutant survives — it re-strengthens the assertions until that mutant dies, then keeps the test.",
    tools: ["mutation_runner"],
    inputs: "coverage gaps from audit",
    outputs: "candidate tests (apply-mode: written + mutation-gated)",
  },
  {
    id: "evaluate",
    name: "evaluate",
    kind: "judgment",
    gate: "auto",
    summary: "Judge whether tests exercise real seams or just mocks.",
    detail:
      "Looks at the existing suite and judges integration effectiveness — are real services exercised, or is everything mocked into meaninglessness? Feeds the integration/system dimension.",
    why: "A green suite can still be a lie if every external dependency is mocked — it only proves the mocks returned what you told them to. `evaluate` decides which boundaries deserve a real-service test, ranked by how much risk a real test would buy, so integration effort goes where mocks are most dangerous.",
    how: [
      "CLASSIFY — take the boundary functions that still carry line gaps from the audit snapshot and categorise each as db / api / queue / file / cli.",
      "SCORE — rank each candidate by replacement value, score = tier_weight × risk_weight × coverage_gap, so the riskiest under-tested seams rise to the top.",
      "PATTERN — assign a lifecycle pattern per category (db → transaction-rollback, api → vcrpy, queue → celery-harness, file → tmp_path, cli → subprocess-capture).",
      "GATE — pass through the gate (auto by default) and hand the ranked strategies to `integrate`.",
    ],
    coverage:
      "Feeds the integration/system dimension. It changes no line number — it judges whether the seams between real services are exercised and queues the ones that aren't.",
    outcome:
      "A ranked integration_strategies list (each with category, risk, score and a lifecycle pattern) for `integrate` to act on.",
    gateReason:
      "auto — it only classifies and ranks; it proposes nothing to your files, so it runs unattended. The real approval happens at `integrate`.",
    example:
      "A payments.charge() boundary is mocked everywhere; evaluate scores it high (api risk 4 × runtime tier 3 × its gap) and tags it `vcrpy`, putting it at the top of the integration queue.",
    tools: [],
    inputs: "test suite + measurements",
    outputs: "integration-effectiveness assessment",
  },
  {
    id: "integrate",
    name: "integrate",
    kind: "judgment",
    gate: "gated",
    summary: "Propose integration tests that hit real boundaries.",
    detail:
      "Authors candidate integration tests for the unwired seams `evaluate` flagged. Propose-only today; the apply-mode hooks (flakiness + cassette secret-scanning gates) are wired for when you opt in.",
    why: "`evaluate` says what to integrate; `integrate` proposes how — a concrete real-service test using the assigned lifecycle pattern. Because real-service tests touch databases, APIs and recorded cassettes, it hard-gates: nothing lands without review, and (when applied) flakiness and cassette-secret checks run before anything is trusted.",
    how: [
      "PLAN — queue the ranked strategies (ordered by replacement value), up to loop.max_gaps_per_cycle.",
      "CONVERT — for each, the LLM proposes a real-service integration test using the assigned pattern (testcontainers / vcrpy / tmp_path / …).",
      "GATE — hard human approval before anything is applied. This build is propose-only; the apply-mode hooks — flakiness_checker (≥10 reruns, ≤2% fail) and secret_scanner over recorded cassettes — are wired for when you opt in.",
    ],
    coverage:
      "Improves the integration dimension by replacing mocks with real seams. Like generate it adds tests, but at the system boundary rather than the unit.",
    outcome:
      "Candidate integration tests appended to `generated` (proposed), awaiting the gate. Control then passes to `report`.",
    gateReason:
      "gated — real-service tests are the highest-risk thing the pipeline writes (live dependencies, recorded secrets), so it always stops for approval.",
    example:
      "integrate drafts a vcrpy-backed test for payments.charge() that records one real API round-trip, then pauses — you review the cassette for leaked keys before it is kept.",
    tools: ["flakiness_checker", "secret_scanner"],
    inputs: "integration assessment",
    outputs: "candidate integration tests (proposed)",
  },
  {
    id: "report",
    name: "report",
    kind: "deterministic",
    gate: "auto",
    summary: "Merge every dimension into one verdict.",
    detail:
      "Merges all dimensions per function into the UnifiedCoverageReport and writes `coverage-report.{json,html}`. Computes the overall verdict: fail if any dimension fails, warn if any did not run, else pass. This is the headline output — the dashboard you see in the Playground.",
    why: "Seven dimensions across many functions are useless as scattered numbers. `report` turns them into one answer — a per-function table, dimension rollups, and a single pass/warn/fail verdict — and persists it as the JSON + HTML you actually read and the Playground dashboard renders.",
    how: [
      "ASSEMBLE — merge every dimension's per-function measurement into the UnifiedCoverageReport.",
      "ROLL-UP — reduce each dimension to a status (line fails if any function is below tier; mutation passes at ≥ kill-rate; assertion fails on weak tests; …) and compute the overall verdict: fail if any dimension failed, warn if any didn't run, else pass.",
      "WRITE — persist coverage-report.json and coverage-report.html to the report dir.",
    ],
    coverage:
      "It doesn't measure coverage — it adjudicates it, combining every dimension into the headline verdict, so 'passing' means every dimension passed, not just lines.",
    outcome:
      "unified_coverage in state, the written report files, and the overall status — the headline output the dashboard shows.",
    gateReason:
      "auto — it only reads measurements and writes a report; there is nothing to approve.",
    example:
      "Lines pass at 96%, but one surviving mutant fails the mutation dimension — report's overall verdict is fail, exactly the honest signal line coverage alone would have hidden.",
    tools: [],
    inputs: "all dimension measurements",
    outputs: "coverage-report.{json,html} + overall verdict",
  },
];

export function getStep(id: string): Step | undefined {
  return STEPS.find((s) => s.id === id);
}

// --------------------------------------------------------------------------
// Deterministic toolbox — the vendored tools behind tools/adapters.py.
// Exit-code convention: 0 = pass/clean, 1 = findings/fail, 2 = tool error
// (coverage_analyzer: 0 = complete, 2 = error).
// --------------------------------------------------------------------------

export interface Tool {
  name: string;
  /** What it measures, plainly. */
  measures: string;
  /** Which dimension(s) it feeds. */
  feeds: string;
}

export const TOOLS: Tool[] = [
  {
    name: "lint_reporter",
    measures: "Static lint + security findings (ruff and friends) over the source.",
    feeds: "lint",
  },
  {
    name: "secret_scanner",
    measures: "Hard-coded credentials / secrets in a file or test cassette.",
    feeds: "lint, integrate",
  },
  {
    name: "coverage.py",
    measures: "Runs the suite and records which lines executed (the .coverage file).",
    feeds: "line",
  },
  {
    name: "coverage_analyzer",
    measures:
      "Per-function line gaps from the .coverage file; with --edges, the cross-package call graph.",
    feeds: "line, edge",
  },
  {
    name: "branch_mapper",
    measures: "Per-function branch structure (if/else, loops, except) via static AST.",
    feeds: "branch",
  },
  {
    name: "boundary_classifier",
    measures:
      "Classifies functions into tiers (boundary/critical vs internal) so thresholds apply correctly.",
    feeds: "line tiers",
  },
  {
    name: "assertion_quality",
    measures: "Scores assertion strength per test; flags padded / assertion-free tests.",
    feeds: "assertion",
  },
  {
    name: "mutation_runner",
    measures:
      "Mutates the code and checks the suite fails — the kill-rate. The generate gate.",
    feeds: "mutation",
  },
  {
    name: "flakiness_checker",
    measures: "Re-runs a test many times to detect non-determinism (default 10 runs).",
    feeds: "integrate (apply-mode gate)",
  },
  {
    name: "log_contract_validator",
    measures: "Checks log statements against a structured-logging policy.",
    feeds: "lint",
  },
  {
    name: "hypothesis_strategy_generator",
    measures: "Proposes property-based (Hypothesis) strategies for functions.",
    feeds: "generate (assist)",
  },
];

// --------------------------------------------------------------------------
// LLM backends for the judgment nodes (config: model.provider).
// --------------------------------------------------------------------------

export interface Backend {
  id: string;
  name: string;
  apiKey: string;
  memory: string;
  note: string;
}

export const BACKENDS: Backend[] = [
  {
    id: "claude-code",
    name: "claude-code (headless)",
    apiKey: "none",
    memory: "Resumes a claude CLI session across calls — state carried for free.",
    note: "The local `claude` CLI run headless. No API key needed; great for laptops and CI that already has the CLI.",
  },
  {
    id: "anthropic",
    name: "anthropic API",
    apiKey: "ANTHROPIC_API_KEY",
    memory: "History-based: prior turns replayed into each request.",
    note: "The Anthropic API directly (default model claude-sonnet-4-6). Best when you want explicit model control.",
  },
  {
    id: "fake",
    name: "fake / none",
    apiKey: "none",
    memory: "—",
    note: "No backend: judgment nodes log 'skipped' and the deterministic measurement + report still run. 'fake' is the deterministic stand-in used by the test suite.",
  },
];

// --------------------------------------------------------------------------
// Configuration facts (config/default.yaml).
// --------------------------------------------------------------------------

export interface ConfigItem {
  key: string;
  value: string;
  meaning: string;
}

export const THRESHOLDS: ConfigItem[] = [
  { key: "line_critical", value: "95.0%", meaning: "Line target for boundary / critical functions." },
  { key: "line_standard", value: "85.0%", meaning: "Line target for ordinary functions." },
  { key: "line_cold", value: "70.0%", meaning: "Line target for cold / rarely-run code." },
  { key: "mutation_kill_rate", value: "1.0", meaning: "generate gate: 100% of mutants must be killed." },
  { key: "assertion_score", value: "0.5", meaning: "Minimum assertion-quality score." },
  { key: "assertion_min", value: "2", meaning: "Minimum real assertions per generated test." },
  { key: "flakiness_max_fail_rate", value: "0.02", meaning: "Max tolerated flaky-fail rate (2%)." },
  { key: "flakiness_min_runs", value: "10", meaning: "Re-runs used to detect flakiness." },
];

export const LOOP: ConfigItem[] = [
  { key: "loop.max_cycles", value: "3", meaning: "Bound on the audit⇄generate loop (the 'Ralph budget')." },
  { key: "loop.max_gaps_per_cycle", value: "10", meaning: "Gaps generate will tackle per cycle." },
];

export const GENERATE_CFG: ConfigItem[] = [
  { key: "generate.apply", value: "false", meaning: "true ⇒ write tests to disk + re-audit (closes the loop). Off by default — nothing written unattended." },
  { key: "generate.restrengthen_attempts", value: "1", meaning: "Re-author cycles when mutants survive." },
  { key: "generate.mutation_max_lines", value: "20", meaning: "Cap on lines mutated per gap (keeps the gate fast)." },
];

// --------------------------------------------------------------------------
// The Python stack — the third-party libraries pyverdex is built on, grouped
// by the job they do. Every entry is a package the engine imports or invokes
// directly (checked against the source); `seenIn` names where so the claim is
// falsifiable. Deliberately ABSENT: mutmut and detect-secrets. pyverdex ships
// its own AST mutation runner and entropy/pattern secret scanner instead of
// calling those, so they never appear here as if they powered a measurement —
// the engine's own toolbox lives in TOOLS / the Deterministic tools page.
// --------------------------------------------------------------------------

export interface Package {
  /** PyPI / import name, exactly as engineers know it. */
  name: string;
  /** One line: the job it does for pyverdex. */
  role: string;
  /** Where it shows up in the engine — proof, not marketing. */
  seenIn: string;
}

export interface PackageGroup {
  title: string;
  /** One sentence framing what this layer is responsible for. */
  blurb: string;
  packages: Package[];
}

export const PACKAGE_GROUPS: PackageGroup[] = [
  {
    title: "Orchestration",
    blurb:
      "pyverdex is a LangGraph state machine — every step is a compiled subgraph and the audit⇄generate loop is an edge in the graph. This layer is model-agnostic by design: it depends on LangGraph, never on a model vendor.",
    packages: [
      {
        name: "langgraph",
        role: "The engine itself — each pipeline step is a compiled subgraph, and the audit⇄generate loop is a conditional edge.",
        seenIn: "graph.py · skills/*.py",
      },
      {
        name: "langgraph-checkpoint-sqlite",
        role: "Checkpoints graph state to SQLite, so a run can stop at a human gate and resume on the next invocation.",
        seenIn: "graph.py — SqliteSaver",
      },
    ],
  },
  {
    title: "Typed core",
    blurb:
      "Nothing in the pipeline passes around loose dicts. State, tool results, and report schemas are typed models, and configuration is layered and validated.",
    packages: [
      {
        name: "pydantic",
        role: "Tool results and the unified report are typed Pydantic models — which is why the graph branches on structured fields, not prose. (Graph state itself is a typed TypedDict.)",
        seenIn: "models.py · tools/vendored/*/schemas.py",
      },
      {
        name: "pydantic-settings",
        role: "Layered config: built-in defaults, then a config file, then PYVERDEX_* environment overrides.",
        seenIn: "config.py — Config(BaseSettings)",
      },
      {
        name: "pyyaml",
        role: "Parses the YAML config file and the per-project discovery rules (.pyverdex.yaml).",
        seenIn: "config.py · discovery.py",
      },
    ],
  },
  {
    title: "Measurement",
    blurb:
      "These produce the numbers. No model touches them — identical input gives identical output, which is what makes the report trustworthy.",
    packages: [
      {
        name: "coverage",
        role: "coverage.py runs the suite and records which lines executed — the raw line dimension and the .coverage file everything else reads.",
        seenIn: "adapters.py — collect_coverage",
      },
      {
        name: "ruff",
        role: "Fast Python linter, and the safe auto-fixer (ruff check --fix) the fix step applies.",
        seenIn: "lint_reporter · fix step",
      },
      {
        name: "mypy",
        role: "Static type checking, folded into the lint report.",
        seenIn: "lint_reporter",
      },
      {
        name: "bandit",
        role: "Security static analysis (SAST) for the lint dimension.",
        seenIn: "lint_reporter",
      },
      {
        name: "vulture",
        role: "Dead-code detection for the lint dimension.",
        seenIn: "lint_reporter",
      },
      {
        name: "hypothesis",
        role: "Property-based testing. The strategy generator proposes Hypothesis @given strategies for a function's inputs.",
        seenIn: "hypothesis_strategy_generator",
      },
    ],
  },
  {
    title: "Model layer",
    blurb:
      "Optional and pluggable. The judgment nodes (fix, generate, evaluate, integrate) reach an LLM through a small LLMBackend interface — the deterministic core needs none of it. One API provider is wired today; adding OpenAI, Google or a local model is a new backend, not a rewrite.",
    packages: [
      {
        name: "langchain-anthropic",
        role: "The one API provider wired today — binds Claude via ChatAnthropic (needs ANTHROPIC_API_KEY). The claude-code backend shells out to the local CLI with no package and no key; the fake backend needs neither.",
        seenIn: "backends.py · llm.py — ChatAnthropic",
      },
    ],
  },
  {
    title: "Run & present",
    blurb:
      "How a run is driven and how its verdict is shown — on the command line, as a standalone HTML report, and in the live dashboard.",
    packages: [
      {
        name: "pytest",
        role: "The runner everything executes under — coverage shells out to pytest to exercise the suite.",
        seenIn: "adapters.py",
      },
      {
        name: "typer",
        role: "The pyverdex command-line interface.",
        seenIn: "cli.py",
      },
      {
        name: "rich",
        role: "Readable, colourised terminal output and tables.",
        seenIn: "cli.py — Console, Table",
      },
      {
        name: "jinja2",
        role: "Renders the standalone HTML coverage report.",
        seenIn: "report/builder.py",
      },
      {
        name: "fastapi",
        role: "The dashboard / serve API the Playground talks to.",
        seenIn: "server/app.py",
      },
      {
        name: "uvicorn",
        role: "The ASGI server that hosts the dashboard.",
        seenIn: "cli.py — serve",
      },
    ],
  },
];

/** Flat list of every highlighted package, for counts and tests. */
export const PACKAGES: Package[] = PACKAGE_GROUPS.flatMap((g) => g.packages);

// --------------------------------------------------------------------------
// Flow diagrams, as Mermaid sources (rendered by <Mermaid>). All graphs in the
// wiki are Mermaid-driven — no hand-drawn ASCII. The `class … det|judge|
// terminal|decision` assignments reference the shared classes the <Mermaid>
// component injects; keep node ids in sync with STEPS so they can't drift.
// --------------------------------------------------------------------------

export interface Diagram {
  /** Mermaid flowchart source (without the shared classDefs). */
  mermaid: string;
  /** Doubles as the figure caption and the accessible label. */
  caption: string;
}

export const PIPELINE: Diagram = {
  mermaid: `flowchart TD
  start([start]) --> lint --> fix --> audit
  audit --> afteraudit{coverage met?}
  afteraudit -->|"gap + budget"| generate
  afteraudit -->|"coverage met"| evaluate
  generate -->|"re-measure"| audit
  evaluate --> integrate --> report --> done([end])
  class start,done terminal
  class lint,audit,report det
  class fix,generate,integrate,evaluate judge
  class afteraudit decision`,
  caption:
    "The pyverdex pipeline: lint, fix, audit, then the audit⇄generate loop, and out through evaluate, integrate, report.",
};

export const PIPELINE_COMPACT: Diagram = {
  mermaid: `flowchart TD
  start([start]) --> lint --> fix --> audit
  audit --> gap{gap?}
  gap -->|yes| generate --> audit
  gap -->|no| evaluate --> integrate --> report --> done([end])
  class start,done terminal
  class lint,audit,report det
  class fix,generate,integrate,evaluate judge
  class gap decision`,
  caption: "The pyverdex pipeline at a glance, with the audit⇄generate loop.",
};

export const APPLY_MODE_LOOP: Diagram = {
  mermaid: `flowchart TD
  start([gap selected]) --> author[author test]
  author --> green{green run?}
  green -->|no| restrengthen[re-strengthen]
  green -->|yes| mutate{mutation gate<br/>kill 100%?}
  mutate -->|survivors| restrengthen
  mutate -->|all killed| keep[keep test]
  restrengthen --> budget{attempts left?<br/>restrengthen_attempts}
  budget -->|yes| author
  budget -->|no| keep
  keep --> reaudit([audit re-measures])
  class start,reaudit terminal
  class author,keep,restrengthen judge
  class green,mutate,budget decision`,
  caption:
    "Apply-mode: author a test, require a green run, then gate on the mutation runner. Surviving mutants re-strengthen the test — bounded by restrengthen_attempts — and the final candidate is kept (recorded with its gate status) before audit re-measures.",
};

export const AUDIT_GENERATE_LOOP: Diagram = {
  mermaid: `flowchart TD
  audit[audit] --> met{coverage met?}
  met -->|yes| evaluate[evaluate]
  met -->|no| budget{cycle < max<br/>and not exhausted?}
  budget -->|no| evaluate
  budget -->|yes| generate[generate]
  generate -->|"re-measure"| audit
  class audit det
  class generate,evaluate judge
  class met,budget decision`,
  caption:
    "The after_audit decision: generate runs only while a gap remains and the cycle budget is not spent, then control returns to audit to re-measure.",
};
