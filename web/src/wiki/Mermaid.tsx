import { useEffect, useId, useRef, useState } from "react";
import { useTheme, type ThemeName } from "./theme";

// Mermaid is large (d3 + dagre + dompurify, ~500kB+). It is NEVER imported at
// module top level — only dynamically inside the render effect — so Rollup
// emits it as its own on-demand chunk, kept out of the initial wiki bundle.

const MONO = '"DM Mono", ui-monospace, "SF Mono", Menlo, monospace';

// Role styling, injected into every chart so a node's saturated stroke encodes
// its role. Colours are baked into the SVG at render time and cannot ride CSS
// variables, so each theme carries its own concrete palette.
function classDefs(theme: ThemeName): string {
  const c =
    theme === "dark"
      ? {
          fill: "#141519", text: "#ededed",
          det: "#2fd4bb", judge: "#bccba9", decision: "#e0b15a",
          termFill: "#0e0f12", termStroke: "#31343c", termText: "#888d96",
        }
      : {
          fill: "#e2ddd0", text: "#34302a",
          det: "#0a7164", judge: "#5f6b54", decision: "#9a6a1f",
          termFill: "#dcd8cc", termStroke: "#b6b1a1", termText: "#5a564d",
        };
  return [
    `classDef det fill:${c.fill},stroke:${c.det},stroke-width:1.5px,color:${c.text}`,
    `classDef judge fill:${c.fill},stroke:${c.judge},stroke-width:1.5px,color:${c.text}`,
    `classDef terminal fill:${c.termFill},stroke:${c.termStroke},stroke-width:1px,color:${c.termText}`,
    `classDef decision fill:${c.fill},stroke:${c.decision},stroke-width:1.5px,color:${c.text}`,
  ].join("\n");
}

// "Engine Room" theme: chrome is warm ink on paper (or pale ink on near-black);
// only the role classDefs add colour. Background transparent so diagrams sit on
// the page's panel surface.
function themeConfig(theme: ThemeName) {
  const v =
    theme === "dark"
      ? {
          darkMode: true,
          primary: "#141519", primaryBorder: "#23252b", primaryText: "#ededed",
          secondary: "#0e0f12", secondaryBorder: "#23252b", secondaryText: "#c2c7d0",
          line: "#565a62", title: "#ededed", text: "#c2c7d0",
          labelBg: "#08090b", labelText: "#c2c7d0",
          clusterBkg: "#0e0f12", clusterBorder: "#23252b", nodeBorder: "#23252b",
          mainBkg: "#141519", nodeText: "#ededed",
        }
      : {
          darkMode: false,
          primary: "#e2ddd0", primaryBorder: "#c8c3b4", primaryText: "#34302a",
          secondary: "#dcd8cc", secondaryBorder: "#c8c3b4", secondaryText: "#5a564d",
          line: "#8a8578", title: "#34302a", text: "#5a564d",
          labelBg: "#dcd8cc", labelText: "#5a564d",
          clusterBkg: "#e6e2d6", clusterBorder: "#c8c3b4", nodeBorder: "#c8c3b4",
          mainBkg: "#e2ddd0", nodeText: "#34302a",
        };
  return {
    startOnLoad: false,
    theme: "base" as const,
    securityLevel: "strict" as const,
    fontFamily: MONO,
    themeVariables: {
      darkMode: v.darkMode,
      fontFamily: MONO,
      fontSize: "15px",
      background: "transparent",
      primaryColor: v.primary,
      primaryBorderColor: v.primaryBorder,
      primaryTextColor: v.primaryText,
      secondaryColor: v.secondary,
      secondaryBorderColor: v.secondaryBorder,
      secondaryTextColor: v.secondaryText,
      tertiaryColor: v.secondary,
      tertiaryBorderColor: v.secondaryBorder,
      tertiaryTextColor: v.secondaryText,
      lineColor: v.line,
      defaultLinkColor: v.line,
      titleColor: v.title,
      textColor: v.text,
      edgeLabelBackground: v.labelBg,
      labelBackground: v.labelBg,
      labelTextColor: v.labelText,
      clusterBkg: v.clusterBkg,
      clusterBorder: v.clusterBorder,
      nodeBorder: v.nodeBorder,
      mainBkg: v.mainBkg,
      nodeTextColor: v.nodeText,
    },
  };
}

// Cache only the imported module so repeated mounts share one fetch. The theme
// is applied per-render (mermaid.initialize is idempotent and cheap), so a
// palette toggle re-themes every diagram on the page.
let mermaidPromise: Promise<typeof import("mermaid")["default"]> | null = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then(({ default: mermaid }) => mermaid);
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
  const theme = useTheme();
  const [state, setState] = useState<State>(() =>
    canRenderMermaid() ? { kind: "loading" } : { kind: "fallback" }
  );

  const source = `${chart}\n${classDefs(theme)}`;

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
        mermaid.initialize(themeConfig(theme));
        const { svg } = await mermaid.render(renderId, source);
        if (alive) setState({ kind: "ready", svg });
      } catch {
        if (alive) setState({ kind: "fallback" });
      }
    })();
    return () => {
      alive = false;
    };
  }, [source, reactId, theme]);

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
