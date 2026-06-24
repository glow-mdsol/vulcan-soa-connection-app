import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listResearchStudies } from "../../api/client";
import StudyWorklist from "./StudyWorklist";

vi.mock("../../api/client");

describe("StudyWorklist", () => {
  beforeEach(() => {
    vi.mocked(listResearchStudies).mockReset();
  });

  it("renders a link to enroll for each study", async () => {
    vi.mocked(listResearchStudies).mockResolvedValue([
      { id: "study-1", title: "UC1 Demo Study" },
    ]);

    render(
      <MemoryRouter>
        <StudyWorklist />
      </MemoryRouter>,
    );

    const link = await screen.findByRole("link", { name: "UC1 Demo Study" });
    expect(link).toHaveAttribute("href", "/enroll/study-1");
  });

  it("shows an error message when the studies request fails", async () => {
    vi.mocked(listResearchStudies).mockRejectedValue(new Error("network error"));

    render(
      <MemoryRouter>
        <StudyWorklist />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load research studies.");
  });
});
