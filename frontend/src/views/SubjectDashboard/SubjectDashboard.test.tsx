import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  completeTask,
  completeVisit,
  getSchedule,
  listVisitActivities,
  performVisit,
  promoteVisit,
  recordMilestone,
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
    vi.mocked(recordMilestone).mockReset();
    vi.mocked(listVisitActivities).mockReset();
    vi.mocked(listVisitActivities).mockResolvedValue([]);
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

  it("links each current visit to both the definition and request/event diagrams", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: ["screening-1"],
      nextSteps: [],
      ambiguous: false,
      visits: { "screening-1": { phase: "proposed" } },
      studyId: "study-1",
      planDefinitionId: "plan-1",
    });

    renderAtSubject("subj-1");

    const definitionLink = await screen.findByRole("link", { name: "Definition diagram ↗" });
    expect(definitionLink).toHaveAttribute("href", "/studies/study-1/protocol-tree?plan=plan-1");

    const eventLink = screen.getByRole("link", { name: "Request/event diagram ↗" });
    expect(eventLink).toHaveAttribute("href", "/subjects/subj-1/request-event-tree");
  });

  it("shows an inline alert on a gate failure while keeping the dashboard rendered", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: ["screening-1"],
      nextSteps: [],
      ambiguous: false,
      visits: { "screening-1": { phase: "proposed" } },
    });
    vi.mocked(promoteVisit).mockRejectedValue(new Error("409"));

    renderAtSubject("subj-1");

    const acceptButton = await screen.findByRole("button", { name: "Accept proposal" });
    await userEvent.click(acceptButton);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not accept the proposal.");
    // The dashboard is still rendered (Current section survives the error).
    expect(screen.getByRole("heading", { name: "Current" })).toBeInTheDocument();
    expect(screen.getByLabelText("Visit screening-1")).toBeInTheDocument();
  });

  it("shows the subject state and recorded milestones, and records a new milestone", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: [],
      nextSteps: [],
      ambiguous: false,
      visits: {},
      subjectStatus: "active",
      subjectState: "on-study",
      milestones: [{ milestone: "C16735", display: "Informed Consent", date: "2026-07-01" }],
    });
    vi.mocked(recordMilestone).mockResolvedValue({
      researchSubjectId: "subj-1",
      milestones: [
        { milestone: "C16735", display: "Informed Consent", date: "2026-07-01" },
        { milestone: "C114209", display: "Subject is Randomized", date: "2026-07-08" },
      ],
    });

    renderAtSubject("subj-1");

    expect(await screen.findByText("on-study")).toBeInTheDocument();
    expect(screen.getByText("active")).toHaveClass("badge-success");
    expect(
      screen.getByText("Informed Consent", { selector: ".milestone-name" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2026-07-01")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Milestone"), "C114209");
    await userEvent.type(screen.getByLabelText("Date"), "2026-07-08");
    await userEvent.click(screen.getByRole("button", { name: "Record milestone" }));

    expect(recordMilestone).toHaveBeenCalledWith(
      "subj-1",
      "C114209",
      "2026-07-08",
      "Subject is Randomized",
    );
    expect(
      await screen.findByText("Subject is Randomized", { selector: ".milestone-name" }),
    ).toBeInTheDocument();
  });

  it("shows an alert when recording a milestone fails", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: [],
      nextSteps: [],
      ambiguous: false,
      visits: {},
      subjectState: "on-study",
      milestones: [],
    });
    vi.mocked(recordMilestone).mockRejectedValue(new Error("500"));

    renderAtSubject("subj-1");

    expect(await screen.findByText("No milestones recorded yet.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Milestone"), "C186212");
    await userEvent.click(screen.getByRole("button", { name: "Record milestone" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not record the milestone.");
  });

  it("lists planned activities with their type and expandable observations", async () => {
    vi.mocked(getSchedule).mockResolvedValue({
      completed: [],
      current: ["screening-1"],
      nextSteps: [],
      ambiguous: false,
      visits: { "screening-1": { phase: "proposed" } },
    });
    vi.mocked(listVisitActivities).mockResolvedValue([
      {
        id: "act-vitals",
        title: "Vital Signs and Temperature",
        type: "ActivityDefinition",
        observations: [
          {
            id: "od-bp-panel",
            display: "Blood pressure panel",
            members: [
              { id: "od-systolic", display: "Systolic blood pressure", members: [] },
              { id: "od-diastolic", display: "Diastolic blood pressure", members: [] },
            ],
          },
          { id: "od-temperature", display: "Body temperature", members: [] },
        ],
      },
      { id: "q-adas-cog", title: "ADAS-Cog", type: "Questionnaire", observations: [] },
    ]);

    renderAtSubject("subj-1");

    expect(await screen.findByText("Vital Signs and Temperature")).toBeInTheDocument();
    expect(listVisitActivities).toHaveBeenCalledWith("subj-1", "screening-1");
    expect(screen.getByText("ActivityDefinition")).toBeInTheDocument();
    expect(screen.getByText("Questionnaire")).toBeInTheDocument();
    expect(screen.queryByText("Systolic blood pressure")).not.toBeInTheDocument();

    const expandButton = screen.getByRole("button", { name: "Show observations (2)" });
    expect(expandButton).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(expandButton);

    // Panel members are shown nested beneath the panel entry.
    expect(screen.getByText(/Blood pressure panel/)).toBeInTheDocument();
    expect(screen.getByText("Systolic blood pressure")).toBeInTheDocument();
    expect(screen.getByText("Diastolic blood pressure")).toBeInTheDocument();
    expect(screen.getByText("Body temperature")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Hide observations" }),
    ).toHaveAttribute("aria-expanded", "true");

    await userEvent.click(screen.getByRole("button", { name: "Hide observations" }));
    expect(screen.queryByText("Systolic blood pressure")).not.toBeInTheDocument();
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
