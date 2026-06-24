import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getContext } from "./api/client";
import AppRoutes from "./routes";

vi.mock("./api/client");
vi.mock("./views/StudyWorklist/StudyWorklist", () => ({
  default: () => <p>Study worklist</p>,
}));
vi.mock("./views/Enroll/Enroll", () => ({
  default: () => <p>Enroll view</p>,
}));

describe("AppRoutes", () => {
  beforeEach(() => {
    vi.mocked(getContext).mockReset();
  });

  it("shows the study worklist when there is no research study context", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Study worklist")).toBeInTheDocument();
  });

  it("redirects to enroll when context carries a research study id", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: "patient-1", researchStudyId: "study-1" });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByText("Enroll view")).toBeInTheDocument();
  });

  it("shows a standalone-launch link when there is no session", async () => {
    vi.mocked(getContext).mockRejectedValue(new Error("401"));

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("link", { name: "start a standalone launch" })).toHaveAttribute(
      "href",
      "/launch/standalone",
    );
  });
});
