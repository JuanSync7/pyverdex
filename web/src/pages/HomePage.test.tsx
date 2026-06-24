import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { HomePage } from "./HomePage";

function renderHome() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>
  );
}

describe("HomePage (the hook)", () => {
  it("leads with the coverage-vs-proof thesis", () => {
    renderHome();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/proof/i);
    expect(screen.getByText(/false signal/i)).toBeInTheDocument();
  });

  it("has primary calls to action to get started and to the playground", () => {
    renderHome();
    const starts = screen.getAllByRole("link", { name: /get started/i });
    expect(starts.length).toBeGreaterThan(0);
    starts.forEach((s) => expect(s).toHaveAttribute("href", "/start"));
    const play = screen.getByRole("link", { name: /playground/i });
    expect(play).toHaveAttribute("href", "/playground");
  });

  it("shows every coverage dimension as a teaser", () => {
    renderHome();
    const grid = screen.getByTestId("dimension-teasers");
    for (const name of [
      "Line coverage",
      "Branch coverage",
      "Edge / function-to-function",
      "Mutation kill-rate",
      "Assertion quality",
      "Integration / system",
      "Lint / security / secrets",
    ]) {
      expect(within(grid).getByText(name)).toBeInTheDocument();
    }
  });

  it("renders the pipeline as a diagram", () => {
    renderHome();
    const diagram = screen.getByTestId("pipeline-diagram");
    // Scope to the diagram SOURCE (the role=img element), not the whole figure:
    // the caption also contains "audit"/"generate", so asserting on the figure
    // would pass even if the diagram failed to mount. "flowchart" is source-only.
    const src = within(diagram).getByRole("img");
    expect(src.textContent).toMatch(/flowchart/);
    expect(src.textContent).toMatch(/generate/);
  });
});
