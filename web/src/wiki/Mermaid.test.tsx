import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Mermaid } from "./Mermaid";

const CHART = `flowchart LR
  a[audit] --> b[generate] --> a`;

describe("Mermaid", () => {
  // Under jsdom there is no SVGElement.getBBox, so the component must never load
  // or run mermaid — it degrades to an accessible, assertable source fallback.
  it("renders an accessible fallback with the source in jsdom", () => {
    render(<Mermaid chart={CHART} caption="audit generate loop" testId="diag" />);
    const fig = screen.getByTestId("diag");
    expect(fig).toBeInTheDocument();
    const img = screen.getByRole("img", { name: "audit generate loop" });
    // jsdom forces the fallback branch (not loading/ready): it must be the <pre>
    // source, carrying the full chart incl. the audit→generate→audit loop-back.
    expect(img.tagName).toBe("PRE");
    expect(fig.querySelector(".mermaid-loading")).toBeNull();
    expect(img.textContent).toMatch(/flowchart/);
    expect(img.textContent).toMatch(/audit/);
    expect(img.textContent).toMatch(/generate/);
  });

  it("shows the caption", () => {
    render(<Mermaid chart={CHART} caption="audit generate loop" />);
    expect(screen.getByText("audit generate loop")).toBeInTheDocument();
  });
});
