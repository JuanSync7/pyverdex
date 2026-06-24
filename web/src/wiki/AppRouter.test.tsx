import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRouter } from "./AppRouter";

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRouter />
    </MemoryRouter>
  );
}

describe("AppRouter", () => {
  it("renders the overview hook at /", () => {
    at("/");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/proof/i);
  });

  it("routes to the tools page", () => {
    at("/tools");
    expect(screen.getByRole("heading", { level: 1, name: "Deterministic tools" })).toBeInTheDocument();
  });

  it("routes to the playground (lazy-loaded)", async () => {
    at("/playground");
    // PlaygroundPage is code-split, so it resolves asynchronously behind Suspense.
    expect(await screen.findByRole("heading", { level: 1, name: "Playground" })).toBeInTheDocument();
  });

  it("shows a not-found page for unknown routes", () => {
    at("/does-not-exist");
    expect(screen.getByRole("heading", { level: 1, name: "Not found" })).toBeInTheDocument();
  });
});
