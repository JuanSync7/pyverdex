import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AgentsPage } from "./AgentsPage";
import { BACKENDS } from "../wiki/content";

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentsPage />
    </MemoryRouter>
  );
}

describe("AgentsPage", () => {
  it("lists every LLM backend", () => {
    renderPage();
    const table = screen.getByTestId("backend-table");
    for (const b of BACKENDS) {
      expect(within(table).getByText(b.name)).toBeInTheDocument();
    }
  });

  it("highlights that claude-code needs no API key", () => {
    renderPage();
    expect(screen.getAllByText(/no api key|without an api key|no key/i).length).toBeGreaterThan(0);
  });

  it("explains the apply-mode mutation gate that verifies LLM output", () => {
    renderPage();
    expect(screen.getAllByText(/apply-mode/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/mutation/i).length).toBeGreaterThan(0);
  });

  it("notes the engine still runs with no backend at all", () => {
    renderPage();
    expect(screen.getAllByText(/no backend|without a backend|skipped/i).length).toBeGreaterThan(0);
  });

  it("visualizes the apply-mode mutation-gate loop as a diagram", () => {
    renderPage();
    const src = within(screen.getByTestId("apply-mode-diagram")).getByRole("img");
    expect(src.textContent).toMatch(/flowchart/);
    expect(src.textContent).toMatch(/mutation gate/i);
  });
});
