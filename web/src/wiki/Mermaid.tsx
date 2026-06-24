import { useEffect, useId, useRef, useState } from "react";

// Mermaid is large (d3 + dagre + dompurify, ~500kB+). It is NEVER imported at
// module top level — only dynamically inside the render effect — so Rollup
// emits it as its own on-demand chunk, kept out of the initial wiki bundle.

const MONO = '"IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace';

// Shared role styling, injected into every chart so the diagrams are themed
// consistently (and the chart constants stay DRY — they only assign classes).
// Saturated colour here encodes a node's role, matching the page discipline.
const CLASSDEFS = [
  "classDef det fill:#1a1f28,stroke:#46c06a,stroke-width:1.5px,color:#e8eaed",
  "classDef judge fill:#1a1f28,stroke:#9d8cff,stroke-width:1.5px,color:#e8eaed",
  "classDef terminal fill:#14181f,stroke:#5b6470,stroke-width:1px,color:#aab2bd",
  "classDef decision fill:#1a1f28,stroke:#e3a740,stroke-width:1.5px,color:#e8eaed",
].join("\n");

// "Test Bench" theme: chrome stays monochrome ink; only the role classDefs add
// colour. Background transparent so diagrams sit on the page's grid surface.
const THEME = {
  startOnLoad: false,
  theme: "base" as const,
  securityLevel: "strict" as const,
  fontFamily: MONO,
  themeVariables: {
    darkMode: true,
    fontFamily: MONO,
    fontSize: "13px",
    background: "transparent",
    primaryColor: "#1a1f28",
    primaryBorderColor: "#2f3744",
    primaryTextColor: "#e8eaed",
    secondaryColor: "#14181f",
    secondaryBorderColor: "#242a34",
    secondaryTextColor: "#aab2bd",
    tertiaryColor: "#14181f",
    tertiaryBorderColor: "#242a34",
    tertiaryTextColor: "#aab2bd",
    lineColor: "#5b6470",
    defaultLinkColor: "#5b6470",
    titleColor: "#e8eaed",
    textColor: "#aab2bd",
    edgeLabelBackground: "#0d1014",
    labelBackground: "#0d1014",
    labelTextColor: "#aab2bd",
    clusterBkg: "#14181f",
    clusterBorder: "#242a34",
    nodeBorder: "#2f3744",
    mainBkg: "#1a1f28",
    nodeTextColor: "#e8eaed",
  },
};

// Cache the imported + initialized module so repeated mounts share one fetch.
let mermaidPromise: Promise<typeof import("mermaid")["default"]> | null = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then(({ default: mermaid }) => {
      mermaid.initialize(THEME);
      return mermaid;
    });
  }
  return mermaidPromise;
}

// True only in a real browser layout engine. Mermaid needs getBBox() to lay out
// SVG — and getBBox lives on SVGGraphicsElement, NOT SVGElement (checking the
// latter is wrong and fails even in Chromium). jsdom advertises itself in the UA
// and implements no real SVG layout, so under vitest this is false and we never
// load/run mermaid — the component degrades to an accessible source fallback.
function canRenderMermaid(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) return false;
  return (
    typeof SVGGraphicsElement !== "undefined" &&
    typeof SVGGraphicsElement.prototype.getBBox === "function"
  );
}

type State = { kind: "loading" } | { kind: "ready"; svg: string } | { kind: "fallback" };

export interface MermaidProps {
  chart: string;
  caption?: string;
  testId?: string;
}

export function Mermaid({ chart, caption, testId }: MermaidProps) {
  const reactId = useId().replace(/:/g, "");
  const attempt = useRef(0);
  const [state, setState] = useState<State>(() =>
    canRenderMermaid() ? { kind: "loading" } : { kind: "fallback" }
  );

  const source = `${chart}\n${CLASSDEFS}`;

  useEffect(() => {
    if (!canRenderMermaid()) {
      setState({ kind: "fallback" });
      return;
    }
    let alive = true;
    const renderId = `mmd-${reactId}-${attempt.current++}`;
    setState({ kind: "loading" });
    (async () => {
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(renderId, source);
        if (alive) setState({ kind: "ready", svg });
      } catch {
        if (alive) setState({ kind: "fallback" });
      }
    })();
    return () => {
      alive = false;
    };
  }, [source, reactId]);

  const label = caption ?? "Diagram";

  return (
    <figure className="mermaid-figure" data-testid={testId}>
      {state.kind === "loading" && (
        <div className="mermaid-loading" role="status" aria-live="polite">
          Rendering diagram…
        </div>
      )}
      {state.kind === "ready" && (
        <div
          className="mermaid-svg"
          role="img"
          aria-label={label}
          dangerouslySetInnerHTML={{ __html: state.svg }}
        />
      )}
      {state.kind === "fallback" && (
        <pre className="mermaid-fallback" role="img" aria-label={label}>
          <code>{chart}</code>
        </pre>
      )}
      {/* The source above carries role=img + aria-label={caption}, so the
          visible caption is hidden from AT to avoid announcing it twice. */}
      {caption && <figcaption aria-hidden="true">{caption}</figcaption>}
    </figure>
  );
}
