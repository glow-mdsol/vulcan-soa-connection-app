import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  completeTask,
  completeVisit,
  getSchedule,
  performVisit,
  promoteVisit,
  respondToAppointment,
  scheduleVisit,
  withdrawSubject,
} from "../../api/client";
import SubjectDashboard from "./SubjectDashboard";

vi.mock("../../api/client");

function renderAtSubject(subjectId: string) {
  return render(
    <MemoryRouter initialEntries={[`/subjects/${subjectId}`]}>
      <Routes>
        <Route path="/subjects/:subjectId" element={<SubjectDashboard />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SubjectDashboard", () => {
  beforeEach(() => {
    vi.mocked(getSchedule).mockReset();
    vi.mocked(completeVisit).mockReset();
    vi.mocked(withdrawSubject).mockReset();
    vi.mocked(promoteVisit).mockReset();
    vi.mocked(scheduleVisit).mockReset();
    vi.mocked(respondToAppointment).mockReset();
    vi.mocked(performVisit).mockReset();
    vi.mocked(completeTask).mockReset();
  });

  it("shows a decision prompt when completing a visit is ambiguous, then schedules the chosen step", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: ["screening-1"],
      current: ["treatment-1"],
      nextSteps: [],
      ambiguous: false,
      visits: { "treatment-1": { phase: "performing", tasks: [] } },
    });
    vi.mocked(completeVisit).mockResolvedValueOnce({
      completed: ["screening-1", "treatment-1"],
      current: [],
      nextSteps: [
        { actionId: "day7-1", title: "Day 7", transitionType: "SS" },
        { actionId: "eos-1", title: "End of Study", transitionType: "FS" },
      ],
      ambiguous: true,
      visits: {},
    });
    vi.mocked(completeVisit).mockResolvedValueOnce({
      completed: ["screening-1", "treatment-1"],
      current: ["day7-1"],
      nextSteps: [],
      ambiguous: false,
      visits: {},
    });

    renderAtSubject("subj-1");

    const completeButton = await screen.findByRole("button", { name: "Complete visit" });
    await userEvent.click(completeButton);

    expect(await screen.findByText("Decision needed")).toBeInTheDocument();
    const day7Button = screen.getByRole("button", { name: "Day 7" });
    await userEvent.click(day7Button);

    expect(completeVisit).toHaveBeenNthCalledWith(1, "subj-1", "treatment-1", null);
    expect(completeVisit).toHaveBeenNthCalledWith(2, "subj-1", "treatment-1", "day7-1");
    expect(screen.queryByText("Decision needed")).not.toBeInTheDocument();
  });

  it("withdraws the subject and shows a confirmation message", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: ["screening-1"],
      nextSteps: [],
      ambiguous: false,
      visits: { "screening-1": { phase: "performing", tasks: [] } },
    });
    vi.mocked(withdrawSubject).mockResolvedValue({ id: "subj-1", subjectState: "withdrawn" });

    renderAtSubject("subj-1");

    const withdrawButton = await screen.findByRole("button", { name: "Withdraw subject" });
    await userEvent.click(withdrawButton);

    expect(await screen.findByRole("status")).toHaveTextContent("Subject withdrawn from study.");
    expect(withdrawSubject).toHaveBeenCalledWith("subj-1");
  });
});
