import { Link } from "react-router-dom";
import { AUDIT_GENERATE_LOOP, PIPELINE, STEPS } from "../wiki/content";
import { StepBadges } from "../wiki/StepBadges";
import { Mermaid } from "../wiki/Mermaid";

// How the stages fit together: the fixed order, the measure-and-improve loop,
// and the human gates. Each step links to its own detail page.
export function PipelinePage() {
  return (
    <article className="page">
      <h1 className="page-title">The pipeline</h1>
      <p className="page-lede">
        pyverify is one <strong>LangGraph state machine</strong>. The original juansync-synapse
        engine was a set of prose flowcharts that only <em>suggested</em> the next step; pyverify
        compiles that into a deterministic graph with a real loop and real gates.
      </p>

      <Mermaid chart={PIPELINE.mermaid} caption={PIPELINE.caption} testId="pipeline-diagram" />

      <h2>Read it left to right</h2>
      <p>
        Control flows from <code>lint</code> to <code>fix</code> to <code>audit</code>, then into
        the <strong>audit⇄generate loop</strong>, and finally out through <code>evaluate</code>,{" "}
        <code>integrate</code>, and <code>report</code>. Every stage is a compiled subgraph (one per
        skill), and every stage reads and writes a shared typed state object that the SQLite
        checkpointer persists.
      </p>

      <ol className="steplist">
        {STEPS.map((s) => (
          <li key={s.id}>
            <div className="pill-row" style={{ justifyContent: "space-between" }}>
              <Link to={`/steps/${s.id}`}>{s.name}</Link>
              <StepBadges kind={s.kind} gate={s.gate} />
            </div>
            <div className="s">{s.summary}</div>
          </li>
        ))}
      </ol>

      <h2>The loop is the whole point</h2>
      <p>
        <code>audit</code> measures, then a conditional edge decides what happens next:
      </p>
      <Mermaid
        chart={AUDIT_GENERATE_LOOP.mermaid}
        caption={AUDIT_GENERATE_LOOP.caption}
        testId="audit-generate-diagram"
      />
      <pre>
        <code>{`def after_audit(state):
    if generate_enabled and not state["coverage_met"] \\
       and state["cycle"] < max_cycles and not state["loop_exhausted"]:
        return "generate"      # there's a gap and budget left → author tests
    return next_enabled_stage  # evaluate / integrate / report`}</code>
      </pre>
      <p>
        <code>audit</code> sets <code>coverage_met</code> when no function is below its tier
        target. <code>generate</code> authors tests for the gaps, increments the cycle counter,
        and sets <code>loop_exhausted</code> when there&apos;s no more work it can do this run. The
        loop is bounded by <code>loop.max_cycles</code> (default <strong>3</strong>) — the
        descendant of juansync&apos;s &ldquo;Ralph budget&rdquo; — so it always terminates.
      </p>

      <h2>Per-stage human gates</h2>
      <p>
        Each stage carries a <code>gate</code> setting. <code>gated</code> stages call LangGraph&apos;s{" "}
        <code>interrupt()</code> and pause for human approval before proceeding; <code>auto</code>{" "}
        stages run unattended. Because state is checkpointed, an interrupted run can be resumed
        later with an approve/reject decision (<code>pyverify resume</code>), or auto-approved in CI
        with <code>--yes</code>.
      </p>
      <p>
        By default the stages that <em>write or judge</em> (<code>fix</code>, <code>generate</code>,{" "}
        <code>integrate</code>) are gated, and the deterministic measurement stages (
        <code>lint</code>, <code>audit</code>, <code>evaluate</code>, <code>report</code>) run on
        auto. You can flip any of them — see <Link to="/config">configuration</Link>.
      </p>

      <p>
        Now dig into what happens inside each stage: <Link to="/steps">the seven steps →</Link>
      </p>
    </article>
  );
}
