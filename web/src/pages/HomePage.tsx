import { Link } from "react-router-dom";
import { DIMENSIONS, PIPELINE_COMPACT } from "../wiki/content";
import { DimensionReadout, FALSE_SIGNAL_CHANNELS } from "../wiki/DimensionReadout";
import { Mermaid } from "../wiki/Mermaid";

// The hook. A newcomer should leave understanding the one idea that makes
// pyverdex worth using — green ≠ verified — and know exactly where to click.
export function HomePage() {
  return (
    <article className="page">
      <div className="hero">
        <div className="hero-eyebrow">Python · test verification</div>
        <h1>Coverage counts lines, pyverdex counts proof.</h1>
        <p className="sub">
          A passing suite at 100% line coverage can verify almost nothing. <strong>pyverdex</strong>{" "}
          measures whether your tests <em>actually</em> check your code — across seven dimensions —
          and can author the tests that close the gaps.
        </p>

        <figure className="false-signal">
          <div className="fs-head">
            <div className="fs-reading">
              <span className="fs-number">100%</span>
              <span className="fs-reading-label">reported line coverage</span>
            </div>
            <span className="fs-verdict">not verified</span>
          </div>
          <DimensionReadout channels={FALSE_SIGNAL_CHANNELS} />
          <figcaption className="fs-caption">
            <b>What a single number hides.</b> The line reads 100% — yet mutations survive and
            integration seams are untested. That gap is the <strong>false signal</strong> pyverdex
            exists to expose.
          </figcaption>
        </figure>

        <div className="cta-row">
          <Link className="cta primary" to="/start">
            Get started →
          </Link>
          <Link className="cta" to="/playground">
            Open the playground
          </Link>
          <Link className="cta" to="/concepts">
            Why it matters
          </Link>
        </div>
      </div>

      <h2>Seven questions one number can&apos;t answer</h2>
      <p>
        Line coverage only proves a line <em>ran</em> — not that any test would notice if it broke.
        pyverdex treats verification as <strong>multi-dimensional</strong>; each dimension answers a
        question your coverage report can&apos;t:
      </p>

      <div className="wiki-grid" data-testid="dimension-teasers">
        {DIMENSIONS.map((d) => (
          <div className="wiki-card" key={d.key}>
            <h3>{d.name}</h3>
            <div className="q">{d.question}</div>
            <div className="meta">measured by {d.tool}</div>
          </div>
        ))}
      </div>

      <p>
        <Link to="/concepts">Read each dimension explained for a junior engineer →</Link>
      </p>

      <h2>One deterministic pipeline</h2>
      <p>
        pyverdex is a <strong>LangGraph state machine</strong>: a fixed sequence of stages with a
        measure-and-improve loop in the middle. Deterministic tools do the measuring; an LLM only
        does the judgment work — authoring tests — behind human gates you control.
      </p>
      <Mermaid
        chart={PIPELINE_COMPACT.mermaid}
        caption={PIPELINE_COMPACT.caption}
        testId="pipeline-diagram"
      />
      <p>
        <Link to="/pipeline">Walk through the pipeline →</Link>
      </p>

      <h2>Why you&apos;ll keep it</h2>
      <ul>
        <li>
          <strong>It catches what coverage hides</strong> — surviving mutants, untested branches,
          unwired integration seams, padded assertions.
        </li>
        <li>
          <strong>It closes the loop</strong> — in apply-mode it writes a test, proves it kills
          mutants, then re-measures, so the number rises for the right reason.
        </li>
        <li>
          <strong>It runs anywhere</strong> — any pytest project, no API key required (the local{" "}
          <code>claude</code> CLI works headless), and the measurement + report run with no LLM at
          all.
        </li>
      </ul>
      <div className="cta-row">
        <Link className="cta primary" to="/start">
          Get started →
        </Link>
        <Link className="cta" to="/tutorials">
          See the tutorials
        </Link>
      </div>
    </article>
  );
}
