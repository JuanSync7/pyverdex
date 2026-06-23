import { useEffect, useRef, useState } from "react";
import {
  api, Dimension, FunctionCoverage, getApiBase, ProjectInfo, Report,
  sampleReportUrl, setApiBase, STATIC_DEMO,
} from "./api";
import { Terminal } from "./Terminal";

const STATUS_COLOR: Record<string, string> = {
  pass: "#1a7f37", fail: "#cf222e", warn: "#9a6700", not_run: "#6e7781", unknown: "#6e7781",
};

function Badge({ status }: { status: string }) {
  return (
    <span className="badge" style={{ background: STATUS_COLOR[status] ?? "#6e7781" }}>
      {status}
    </span>
  );
}

function DimensionCard({ d }: { d: Dimension }) {
  return (
    <div className="card dim">
      <div className="dim-head">
        <span className="dim-name">{d.name}</span>
        <Badge status={d.status} />
      </div>
      <div className="dim-head-line">{d.headline}</div>
    </div>
  );
}

const pct = (v: number | null) => (v === null || v === undefined ? "—" : `${v}%`);

function FunctionsTable({ funcs }: { funcs: FunctionCoverage[] }) {
  return (
    <table className="cov">
      <thead>
        <tr>
          <th>Module</th><th>Function</th><th>Tier</th>
          <th className="num">Line</th><th className="num">Missing</th>
          <th className="num">Branches</th><th className="num">Mutation</th>
        </tr>
      </thead>
      <tbody>
        {funcs.map((f, i) => (
          <tr key={i} className={f.is_boundary ? "boundary" : ""}>
            <td>{f.module}</td>
            <td>{f.function_name}</td>
            <td>{f.tier}</td>
            <td className="num" style={{ color: f.line_coverage_pct !== null && f.line_coverage_pct < 85 ? "#cf222e" : "#1a7f37" }}>
              {pct(f.line_coverage_pct)}
            </td>
            <td className="num">{f.missing_lines.length || "—"}</td>
            <td className="num">{f.branch_count ?? "—"}</td>
            <td className="num">
              {f.mutation_kill_rate === null ? "—" : `${Math.round(f.mutation_kill_rate * 100)}%`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function App() {
  const [backend, setBackend] = useState(getApiBase());
  const live = !!backend || !STATIC_DEMO;

  const [path, setPath] = useState("");
  const [info, setInfo] = useState<ProjectInfo | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [apply, setApply] = useState(false);
  const [provider, setProvider] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (live) {
      api.default()
        .then((d) => { if (d.path) { setPath(d.path); return api.discover(d.path).then(setInfo); } })
        .catch((e) => setErr(`backend unreachable: ${e.message ?? e}`));
    } else {
      fetch(sampleReportUrl())
        .then((r) => r.json())
        .then(setReport)
        .catch(() => setErr("could not load bundled sample report"));
    }
  }, [live]);

  useEffect(() => {
    logRef.current?.scrollTo(0, logRef.current.scrollHeight);
  }, [logs]);

  const connect = () => { setApiBase(backend.trim()); location.reload(); };

  const discover = async () => {
    setErr(null);
    try { setInfo(await api.discover(path)); } catch (e: any) { setErr(String(e.message ?? e)); }
  };

  const run = async () => {
    setErr(null); setLogs([]); setReport(null); setRunning(true);
    try {
      const { run_id, info } = await api.run(path, apply, provider);
      setInfo(info);
      const es = new EventSource(api.eventsUrl(run_id));
      es.onmessage = (e) => {
        const d = JSON.parse(e.data);
        if (d.log) setLogs((l) => [...l, d.log]);
        if (d.status) {
          if (d.report) setReport(d.report);
          if (d.error) setErr(d.error);
          setRunning(false); es.close();
        }
      };
      es.onerror = () => { setRunning(false); es.close(); };
    } catch (e: any) { setErr(String(e.message ?? e)); setRunning(false); }
  };

  const termPath = info?.project_root || path;

  return (
    <div className="app">
      <header>
        <h1>pyverify</h1>
        <span className="tagline">multi-dimensional test coverage · line · branch · edges · mutation · assertions</span>
        <span className={`mode ${live ? "modelive" : "modestatic"}`}>{live ? "LIVE" : "STATIC DEMO"}</span>
      </header>

      {!live && (
        <div className="notice">
          Static showcase (GitHub Pages) — rendering a bundled sample report.
          Interactive runs and the web terminal need the pyverify backend. Run
          <code>pyverify serve</code> (or <code>./demo/run_demo.sh</code>) and paste its URL below to go live.
        </div>
      )}

      <section className="controls card">
        <input
          value={backend}
          onChange={(e) => setBackend(e.target.value)}
          placeholder="backend URL (blank = static demo), e.g. http://localhost:8000"
          spellCheck={false}
          style={{ flex: "1 1 280px" }}
        />
        <button onClick={connect}>{backend ? "Connect" : "Use static"}</button>
      </section>

      {live && (
        <section className="controls card">
          <input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/path/to/any/pytest/project"
            spellCheck={false}
          />
          <button onClick={discover} disabled={!path}>Discover</button>
          <select value={provider} onChange={(e) => setProvider(e.target.value)} title="LLM backend">
            <option value="">measure only (no LLM)</option>
            <option value="claude-code">claude-code (headless)</option>
            <option value="anthropic">anthropic API</option>
          </select>
          <label className="chk">
            <input type="checkbox" checked={apply} onChange={(e) => setApply(e.target.checked)} />
            apply-mode
          </label>
          <button className="primary" onClick={run} disabled={!path || running}>
            {running ? "Running…" : "Run verification"}
          </button>
        </section>
      )}

      {err && <div className="error">{err}</div>}

      {info && live && (
        <section className="card info">
          <b>{info.project_root}</b> — source <code>{info.source_root}</code>,
          tests <code>{info.test_root}</code> · {info.source_count} source files ·{" "}
          {info.test_count} test files
          <details>
            <summary>files</summary>
            <div className="filelists">
              <div><h4>source</h4><ul>{info.source_files.map((f) => <li key={f}>{f}</li>)}</ul></div>
              <div><h4>tests</h4><ul>{info.test_files.map((f) => <li key={f}>{f}</li>)}</ul></div>
            </div>
          </details>
        </section>
      )}

      {report && (
        <>
          <section className="verdict-row">
            <span className="verdict" style={{ background: STATUS_COLOR[report.overall_status] ?? "#6e7781" }}>
              {report.overall_status.toUpperCase()}
            </span>
            <span>{report.total_functions} functions</span>
            <span>{report.functions_with_line_gaps} line gaps ({report.boundary_gaps} boundary)</span>
            <span>avg line {pct(report.overall_line_coverage_pct)}</span>
            <span>{report.cross_package_edges} edges</span>
            <span>mutation {report.mutation_kill_rate === null ? "—" : `${Math.round(report.mutation_kill_rate * 100)}%`}</span>
            <span>{report.weak_tests} weak tests</span>
          </section>

          <section className="dims">
            {report.dimensions.map((d) => <DimensionCard key={d.name} d={d} />)}
          </section>

          <section className="card">
            <h3>Functions</h3>
            <FunctionsTable funcs={report.functions} />
          </section>
        </>
      )}

      {live && (
        <section className="card logs">
          <h3>Run log</h3>
          <div className="logbox" ref={logRef}>
            {logs.length === 0 ? <span className="muted">no run yet</span> :
              logs.map((l, i) => <div key={i} className={l.startsWith("!") ? "logerr" : ""}>{l}</div>)}
          </div>
        </section>
      )}

      {live && termPath && (
        <section className="card term-card">
          <h3>Web terminal <span className="muted">({termPath})</span></h3>
          <Terminal key={termPath} path={termPath} wsBase={backend} />
        </section>
      )}

      <footer>pyverify · LangGraph engine · vendored juansync tools</footer>
    </div>
  );
}
