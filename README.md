# pyverify

A **multi-dimensional test-verification engine** for Python, built as a
[LangGraph](https://langchain-ai.github.io/langgraph/) state machine.

It is the productionised successor to the `juansync-synapse` "test coverage
engine" — the `test-lint → test-fix → test-audit → test-generate →
test-evaluate → test-integrate` skill flow — turned into a single deterministic
graph with a config-driven loop and human gates.

Its thesis: **line coverage + lint is a false signal.** Real verification
measures several orthogonal dimensions of test *effectiveness*:

| Dimension | What it answers | Tool |
|---|---|---|
| **line** | did the code run? | `coverage.py` |
| **branch** | which branches exist per function? | `branch_mapper` |
| **edge (function-to-function)** | which cross-package call seams are wired? | `coverage_analyzer --edges` |
| **mutation** | are the assertions actually strong? | `mutation_runner` |
| **assertion-quality** | are the tests meaningful or padded? | `assertion_quality` |
| **integration / system** | are real services exercised, not just mocks? | `test-evaluate`/`test-integrate` |
| **lint / security / secrets** | static health | `lint_reporter`, `secret_scanner` |

## Architecture in one diagram

```mermaid
flowchart LR
  start([START]) --> lint --> fix --> audit
  audit --> afteraudit{coverage met?}
  afteraudit -->|"gap + budget"| generate
  afteraudit -->|"coverage met"| evaluate
  generate -->|"re-measure"| audit
  evaluate --> integrate --> report --> done([END])
```

- **Deterministic nodes** = the 10 vendored juansync tools (no LLM) behind
  typed adapters in `pyverify/tools/`.
- **Judgment nodes** (`fix`, `generate`, `evaluate`, `integrate`) call an LLM
  with a **system prompt distilled from the original `SKILL.md` + rules + the
  TDD protocol** (`pyverify/knowledge/`). Without `ANTHROPIC_API_KEY` they
  degrade to logged pass-throughs, so the deterministic measurement + report
  always run.
- **Per-stage config-toggle gates**: each stage's `gate: gated|auto` decides
  whether it pauses for human approval (LangGraph `interrupt()` + SQLite
  checkpointer) or proceeds unattended.
- **The audit⇄generate loop** keeps measuring after authoring tests, bounded by
  `loop.max_cycles`.

Each `SKILL.md` flowchart is its own compiled subgraph (`pyverify/skills/`),
composed into one engine in `pyverify/graph.py`.

## Install

```bash
uv sync           # Python 3.11+, installs LangGraph + the analysis toolchain
```

### Vendored tools (sync step)

The 10 deterministic measurement tools and the skill/protocol docs are **copies
of a separate repo (`juansync-synapse`)** and are intentionally *not* committed
here. Populate them from your own checkout before running the engine:

```bash
./scripts/sync-vendor.sh /path/to/juansync-synapse
# or: PYVERIFY_JUANSYNC_ROOT=/path/to/juansync-synapse ./scripts/sync-vendor.sh
```

`import pyverify` works without them; running the engine (and the test suite)
requires the sync.

## Use

### CLI

```bash
# Verify a project (auto-approve all gates — good for CI):
uv run pyverify run /path/to/project -c config/default.yaml --yes

# Stop at the first human gate, then resume after review:
uv run pyverify run /path/to/project -c config/default.yaml --thread myrun
uv run pyverify resume --thread myrun --approve     # or --reject

# Any pytest project works — layout is auto-detected (src/, package, or flat):
uv run pyverify run /path/to/any/pytest/project --yes
```

Outputs land in `<project>/project/coverage/report/coverage-report.{html,json}`
— the unified, per-function, multi-dimensional view.

### Web app + demo

```bash
./demo/run_demo.sh                       # builds the UI, serves the demo on :8000
uv run pyverify serve /path/to/project   # or point it at your own project
```

The dashboard shows the dimension cards + per-function table, streams the run
log live, and embeds a **web terminal** (a real shell in the project) so you can
run `pytest` / `pyverify run .` from the browser. See [`demo/`](demo/).

### GitHub Pages (the wiki + static showcase)

The published site is a **documentation wiki** that explains every concept,
pipeline step, tool, and backend — plus a **Playground** that embeds the real
dashboard. Because GitHub Pages serves static files only, the Playground there
renders a bundled sample report (not the live engine or terminal — those need
the backend). The `.github/workflows/pages.yml` workflow builds `web/` with
`VITE_STATIC_DEMO=1` and `VITE_BASE=/pyverify/` and deploys it on push to
`main`. Enable it once under **Settings → Pages → Source: GitHub Actions**. On
the Playground you can paste a `pyverify serve` URL into the **backend** field
to switch the same UI into live mode against your own server.

The web app is a Vite/React SPA with a `HashRouter` (so deep links resolve on a
static host with no 404 fallback) and a Vitest + Testing-Library suite
(`npm test` in `web/`). The wiki content lives as a typed source-of-truth model
in `web/src/wiki/content.ts`, so the docs can't silently drift from the engine.
(Adjust `VITE_BASE` if the repo is renamed; a private-repo Pages site may be
public depending on plan — the build contains only the frontend + demo data, no
vendored content.)

### Apply-mode (closing the loop)

With `generate.apply: true` and an LLM backend, `generate` writes the approved
test to disk, **gates it on `mutation_runner`** (the test must hit
`mutation_kill_rate`, with `restrengthen_attempts` retries feeding surviving
mutants back to the model), then the audit⇄generate loop re-measures so coverage
actually improves. Two backends, selectable via `model.provider`:

- `claude-code` — the local `claude` CLI headless, **no API key needed**, with
  session memory carried across calls.
- `anthropic` — the Anthropic API (`ANTHROPIC_API_KEY`).

## Configure

Everything is in one YAML (see [`config/default.yaml`](config/default.yaml)):
tier thresholds (line 95/85/70, mutation kill 1.0, assertion 0.5/min-2,
flakiness 2%/10-runs), the LLM model, the loop bound, and per-stage
`enabled` + `gate`. Any field is also overridable by env (`PYVERIFY_*`).

## Status / scope

- Deterministic measurement (line, branch, edge, assertion, lint) + the unified
  report are complete and tested.
- `generate` supports **apply-mode** (write test → mutation-gate → re-audit), and
  is **propose-only by default** (`generate.apply: false`) so nothing is written
  unattended unless you opt in. `fix`/`integrate` remain propose-only.
- Two LLM backends (`anthropic`, `claude-code`) with cross-call memory; the
  deterministic measurement + report run with no backend at all.
- Only the 10 tools that actually existed upstream are vendored; the SKILL docs
  referenced a few (`critical_scorer`, `gaming_detector`, `dep_vulnerability`)
  that were never implemented — those dimensions are intentionally omitted
  rather than faked.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and the
mapping back to juansync-synapse.
