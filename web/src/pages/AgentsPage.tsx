import { Link } from "react-router-dom";
import { APPLY_MODE_LOOP, BACKENDS, STEPS } from "../wiki/content";
import { Mermaid } from "../wiki/Mermaid";

const JUDGMENT_STEPS = STEPS.filter((s) => s.kind === "judgment" || s.kind === "mixed");

// The LLM side of pyverify, and — just as important — its leash. The model only
// does judgment work, behind gates, and in apply-mode its output must pass a
// deterministic mutation gate before it is trusted.
export function AgentsPage() {
  return (
    <article className="page">
      <h1 className="page-title">Agents &amp; backends</h1>
      <p className="page-lede">
        Deterministic tools <em>measure</em>; an LLM only does the <strong>judgment</strong> work
        no tool can — reading a gap and writing a test for it. pyverify keeps that model on a short
        leash: it runs behind human gates, and anything it writes must survive a deterministic
        check before it counts.
      </p>

      <h2>Which stages think</h2>
      <p>Only these stages call a model. The rest is pure measurement.</p>
      <ul>
        {JUDGMENT_STEPS.map((s) => (
          <li key={s.id}>
            <Link to={`/steps/${s.id}`}>
              <code>{s.name}</code>
            </Link>{" "}
            — {s.summary}
          </li>
        ))}
      </ul>

      <h2>Backends</h2>
      <p>
        The model provider is one config value (<code>model.provider</code>). Three options:
      </p>
      <table className="wiki-table" data-testid="backend-table">
        <thead>
          <tr>
            <th>Backend</th>
            <th>API key</th>
            <th>Memory</th>
            <th>When to use</th>
          </tr>
        </thead>
        <tbody>
          {BACKENDS.map((b) => (
            <tr key={b.id}>
              <td>
                <code>{b.id}</code>
                <div className="meta" style={{ color: "var(--muted)", fontSize: "0.78rem" }}>
                  {b.name}
                </div>
              </td>
              <td>{b.apiKey}</td>
              <td>{b.memory}</td>
              <td>{b.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        The headline option is <code>claude-code</code>: it drives your local <code>claude</code>{" "}
        CLI headless, so it needs <strong>no API key</strong> and carries memory across calls by
        resuming the same CLI session.
      </p>

      <h2>Memory across calls</h2>
      <p>
        Closing a coverage gap takes several model calls — author, see the mutants that survived,
        try again. Each backend keeps context so the model isn&apos;t starting cold every time:{" "}
        <code>claude-code</code> resumes its session id; <code>anthropic</code> replays prior turns
        into each request. State between graph steps lives in the checkpointed engine state, not
        the model — so a run can be paused and resumed without losing its place.
      </p>

      <h2>Apply-mode: never trust, always verify</h2>
      <p>
        This is what makes generated tests trustworthy. With <code>generate.apply: true</code>,{" "}
        <Link to="/steps/generate">generate</Link> doesn&apos;t just propose a test — it:
      </p>
      <ol>
        <li>extracts the test code from the model&apos;s reply and checks it parses;</li>
        <li>writes it and runs it to confirm it&apos;s green against the real code;</li>
        <li>
          gates it on <code>mutation_runner</code> — the test must kill <strong>100%</strong> of
          mutants, or the surviving mutants are fed back to the model to re-strengthen it;
        </li>
        <li>
          only then keeps it, and <code>audit</code> re-measures so coverage rises for the right
          reason.
        </li>
      </ol>
      <Mermaid
        chart={APPLY_MODE_LOOP.mermaid}
        caption={APPLY_MODE_LOOP.caption}
        testId="apply-mode-diagram"
      />
      <div className="callout">
        <span className="callout-label">why</span>
        <div>
          A model can write a test that passes but asserts nothing. The mutation gate is a
          deterministic referee: a weak test lets mutants survive and is rejected automatically. The
          LLM proposes; the tools decide.
        </div>
      </div>

      <h2>No backend? Still works.</h2>
      <p>
        With no backend at all, the judgment nodes simply log <code>skipped</code> and the
        deterministic measurement + the unified report still run end-to-end. You always get the
        honest numbers; the LLM only adds the test-authoring on top.
      </p>

      <p>
        Set all of this in <Link to="/config">configuration</Link>, or try it on the{" "}
        <Link to="/playground">playground</Link>.
      </p>
    </article>
  );
}
