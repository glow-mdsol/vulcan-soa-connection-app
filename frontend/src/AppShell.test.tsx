import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AppShell from "./AppShell";

describe("AppShell", () => {
  it("renders the brand heading with its exact accessible name", () => {
    render(<AppShell>content</AppShell>);
    expect(screen.getByRole("heading", { name: "Vulcan Schedule of Activities" })).toBeInTheDocument();
  });

  it("renders children inside the main landmark", () => {
    render(<AppShell>page body</AppShell>);
    expect(screen.getByRole("main")).toHaveTextContent("page body");
  });
});
