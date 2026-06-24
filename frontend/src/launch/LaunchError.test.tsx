import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import LaunchError from "./LaunchError";

function renderWithReason(reason: string | null) {
  const path = reason ? `/launch-error?reason=${reason}` : "/launch-error";
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/launch-error" element={<LaunchError />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LaunchError", () => {
  it("shows a specific message for untrusted_iss", async () => {
    renderWithReason("untrusted_iss");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This app was launched from an unrecognized FHIR server.",
    );
  });

  it("shows a specific message for invalid_state", async () => {
    renderWithReason("invalid_state");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your sign-in session expired or was already used.",
    );
  });

  it("falls back to a generic message for an unknown or missing reason", async () => {
    renderWithReason(null);
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed.");
  });
});
