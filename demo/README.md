---
title: Demo
kind: demo
layer: n/a
status: stable
owner: Juan.Kok
summary: Runnable demo of the pyverdex pipeline over a sample project.
id: demo-readme
created: 2026-06-26
updated: 2026-06-26
visibility: public
canonical: true
---
# pyverdex demo

A self-contained walkthrough: a small `shop` package wired into the pyverdex
web app so you can see the multi-dimensional coverage metrics and drive tests
from a browser terminal.

## Run it

```bash
./demo/run_demo.sh        # builds the frontend (first run) + serves on :8000
```

Open <http://127.0.0.1:8000>. The demo project (`demo/sample_app`) is loaded by
default.

## What you'll see

`demo/sample_app` is a normal pytest project (`src/` layout) with deliberately
**partial** tests, so the dashboard lights up:

- **line** — `tier_discount` (the ≥500/≥1000 branches) and `final_price` (the
  VIP path) are uncovered; `reserve`'s error branches are uncovered.
- **edge (function-to-function)** — `shop.api.handle_checkout` calls `json` and
  `os`, so cross-package call edges are mapped.
- **boundary / critical** — `handle_checkout` reads `os.environ`, so it's a
  runtime boundary (critical tier, 95% target) and shows up as a real-
  integration candidate in the evaluate stage.
- **assertion-quality** — every test is scored.

## Drive it from the web

- **Run verification** — measure-only by default. Pick **claude-code** as the
  backend and tick **apply-mode** to have the headless `claude` CLI author
  tests, write them, and gate each on `mutation_runner` — then watch the line
  coverage climb on the next loop.
- **Web terminal** — a real shell in `demo/sample_app`. Try:
  ```
  uv run pyverdex run . --yes
  pytest -q
  ```

## Wiring your own project

The same works for any pytest project — pyverdex auto-detects `src/`-layout,
single-package, or flat layouts. Either type its path into the dashboard, or:

```bash
uv run pyverdex serve /path/to/your/project
```

Drop a `.pyverdex.yaml` (see `demo/sample_app/.pyverdex.yaml`) or a
`[tool.pyverdex]` table in your `pyproject.toml` to pin thresholds, the loop
bound, or the LLM backend.
