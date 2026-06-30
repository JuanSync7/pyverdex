import { Link, useParams } from "react-router-dom";
import { getStep, STEPS } from "../wiki/content";
import { GITHUB_URL } from "../wiki/nav";
import { StepBadges } from "../wiki/StepBadges";

// The canonical Markdown is generated from the same STEPS data (web/scripts/
// gen-steps-doc.ts) and shipped two ways: committed to the repo for GitHub, and
// copied into the build so the wiki can offer it as a download.
const DOC_GITHUB = `${GITHUB_URL}/blob/main/docs/SEVEN_STEPS.md`;
const DOC_DOWNLOAD = `${import.meta.env.BASE_URL}seven-steps.md`;

// Two views from one component: the index (all seven steps) and a single-step
// detail when /steps/:stepId is matched.
export function StepsPage() {
  const { stepId } = useParams();
  if (stepId) return <StepDetail id={stepId} />;
  return <StepIndex />;
}

function StepIndex() {
  return (
    <article className="page">
      <h1 className="page-title">The seven steps</h1>
      <p className="page-lede">
        The pipeline is seven compiled subgraphs, each with one job. Every step below
        explains itself in full — what it does, why it exists, how it operates, how it
        touches coverage, what it drives next, and why it does or doesn&apos;t pause for you.
      </p>
      <ol className="steplist" data-testid="step-index">
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

      <div className="callout">
        <div className="callout-label">Doc</div>
        <div>
          Every word on these pages is generated from one source and also published as a
          single Markdown file:{" "}
          <a href={DOC_GITHUB} target="_blank" rel="noreferrer">
            read it on GitHub ↗
          </a>{" "}
          or{" "}
          <a href={DOC_DOWNLOAD} download="pyverdex-seven-steps.md">
            download the Markdown
          </a>
          .
        </div>
      </div>

      <p>
        See how they connect in <Link to="/pipeline">the pipeline</Link>.
      </p>
    </article>
  );
}

function StepDetail({ id }: { id: string }) {
  const step = getStep(id);
  if (!step) {
    return (
      <article className="page">
        <Link className="step-back" to="/steps">
          ← all steps
        </Link>
        <h1 className="page-title">Unknown step</h1>
        <p>
          There&apos;s no stage called <code>{id}</code>. Pick one from{" "}
          <Link to="/steps">the seven steps</Link>.
        </p>
      </article>
    );
  }

  const idx = STEPS.findIndex((s) => s.id === id);
  const prev = idx > 0 ? STEPS[idx - 1] : null;
  const next = idx < STEPS.length - 1 ? STEPS[idx + 1] : null;

  return (
    <article className="page">
      <Link className="step-back" to="/steps">
        ← all steps
      </Link>
      <p className="page-eyebrow">
        step {String(idx + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}
      </p>
      <h1 className="page-title">{step.name}</h1>
      <div className="pill-row" style={{ marginBottom: "1rem" }}>
        <StepBadges kind={step.kind} gate={step.gate} />
      </div>

      <p className="page-lede">{step.summary}</p>

      <h2>What it does</h2>
      <p>{step.detail}</p>

      <h2>Why this step exists</h2>
      <p>{step.why}</p>

      <h2>How it operates</h2>
      <p className="meta" style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
        Internally, <code>{step.name}</code> runs as its own compiled subgraph; these are
        its phases, in order.
      </p>
      <ol>
        {step.how.map((phase) => (
          <li key={phase}>{phase}</li>
        ))}
      </ol>

      <h2>How it determines coverage</h2>
      <p>{step.coverage}</p>

      <div className="callout">
        <div className="callout-label">Example</div>
        <div>{step.example}</div>
      </div>

      <h2>What it drives next</h2>
      <p>{step.outcome}</p>

      <h2>What it reads and writes</h2>
      <table className="wiki-table">
        <tbody>
          <tr>
            <th>Kind</th>
            <td>
              {step.kind === "deterministic"
                ? "Deterministic — no LLM, identical output for identical input."
                : step.kind === "judgment"
                ? "LLM judgment — calls the configured model behind a gate."
                : "Mixed — a deterministic part plus an LLM-proposed part."}
            </td>
          </tr>
          <tr>
            <th>Gate</th>
            <td>{step.gateReason}</td>
          </tr>
          <tr>
            <th>Input</th>
            <td>{step.inputs}</td>
          </tr>
          <tr>
            <th>Output</th>
            <td>{step.outputs}</td>
          </tr>
        </tbody>
      </table>

      {step.tools.length > 0 && (
        <>
          <h2>Tools it drives</h2>
          <ul>
            {step.tools.map((t) => (
              <li key={t}>
                <code>{t}</code>
              </li>
            ))}
          </ul>
          <p className="meta" style={{ color: "var(--muted)", fontSize: "0.85rem" }}>
            See the full <Link to="/tools">deterministic toolbox</Link>.
          </p>
        </>
      )}

      <div className="cta-row" style={{ marginTop: "2rem" }}>
        {prev && (
          <Link className="cta" to={`/steps/${prev.id}`}>
            ← {prev.name}
          </Link>
        )}
        {next && (
          <Link className="cta" to={`/steps/${next.id}`}>
            {next.name} →
          </Link>
        )}
      </div>
    </article>
  );
}
