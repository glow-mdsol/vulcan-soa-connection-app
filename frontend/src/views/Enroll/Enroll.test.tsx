import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  assignSubjectIdentifier,
  deleteEnrollment,
  enrollPatient,
  getContext,
  getResearchStudy,
  listPatients,
  listStudySubjects,
} from "../../api/client";
import Enroll from "./Enroll";

vi.mock("../../api/client");

function renderAtStudy(studyId: string) {
  return render(
    <MemoryRouter initialEntries={[`/enroll/${studyId}`]}>
      <Routes>
        <Route path="/enroll/:studyId" element={<Enroll />} />
        <Route path="/subjects/:subjectId" element={<p>Subject dashboard</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Enroll", () => {
  beforeEach(() => {
    vi.mocked(getContext).mockReset();
    vi.mocked(enrollPatient).mockReset();
    vi.mocked(getResearchStudy).mockReset();
    vi.mocked(listPatients).mockReset();
    vi.mocked(listStudySubjects).mockReset();
    vi.mocked(listStudySubjects).mockResolvedValue([]);
    vi.mocked(assignSubjectIdentifier).mockReset();
    vi.mocked(deleteEnrollment).mockReset();
  });

  it("enrolls the selected patient from the list", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: "patient-1", researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1"],
    });
    vi.mocked(listPatients).mockResolvedValue([
      { id: "patient-1", gender: "female", birthDate: "1980-01-01", deceased: null, active: true },
      { id: "patient-2", gender: "male", birthDate: null, deceased: null, active: true },
    ]);
    vi.mocked(enrollPatient).mockResolvedValue({
      researchSubjectId: "subj-1",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false, visits: {} },
    });

    renderAtStudy("study-1");

  expect(await screen.findByRole("heading", { name: "UC1 Demo Study" })).toBeInTheDocument();
  expect(screen.getByText("study-1")).toBeInTheDocument();
  expect(screen.getByText("1 protocol is attached to this study.")).toBeInTheDocument();
    const select = await screen.findByLabelText("Patient");
    expect(select).toHaveValue("patient-1");

    const enrollButton = screen.getByRole("button", { name: "Enroll" });
    expect(enrollButton).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Subject identifier"), "SUBJ-001");
    await userEvent.click(enrollButton);

    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
    expect(enrollPatient).toHaveBeenCalledWith("study-1", "patient-1", "SUBJ-001", "plan-1");
  });

  it("lets the user choose a different patient when there is no launch context", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1", "PlanDefinition/plan-2"],
    });
    vi.mocked(listPatients).mockResolvedValue([
      { id: "patient-1", gender: "female", birthDate: null, deceased: null, active: true },
      { id: "uc1-demo-patient", gender: "unknown", birthDate: null, deceased: null, active: true },
    ]);
    vi.mocked(enrollPatient).mockResolvedValue({
      researchSubjectId: "subj-2",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false, visits: {} },
    });

    renderAtStudy("study-1");

    const select = await screen.findByLabelText("Patient");
    await userEvent.selectOptions(select, "uc1-demo-patient");
    await userEvent.type(screen.getByLabelText("Subject identifier"), "SUBJ-002");
    await userEvent.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
    expect(enrollPatient).toHaveBeenCalledWith("study-1", "uc1-demo-patient", "SUBJ-002", "plan-1");
  });

  it("lets the user choose a protocol when the study has several", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: "patient-1", researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1", "PlanDefinition/plan-2"],
    });
    vi.mocked(listPatients).mockResolvedValue([
      { id: "patient-1", gender: "female", birthDate: null, deceased: null, active: true },
    ]);
    vi.mocked(enrollPatient).mockResolvedValue({
      researchSubjectId: "subj-3",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false, visits: {} },
    });

    renderAtStudy("study-1");

    const protocolSelect = await screen.findByLabelText("Protocol");
    expect(protocolSelect).toHaveValue("plan-1");
    await userEvent.selectOptions(protocolSelect, "plan-2");
    await userEvent.type(screen.getByLabelText("Subject identifier"), "SUBJ-003");
    await userEvent.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
    expect(enrollPatient).toHaveBeenCalledWith("study-1", "patient-1", "SUBJ-003", "plan-2");
  });

  it("hides the protocol selector when the study has a single protocol", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1"],
    });
    vi.mocked(listPatients).mockResolvedValue([]);

    renderAtStudy("study-1");

    expect(await screen.findByRole("heading", { name: "UC1 Demo Study" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Protocol")).not.toBeInTheDocument();
  });

  it("removes an enrolment from the roster", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);
    vi.mocked(listStudySubjects).mockResolvedValue([
      {
        researchSubjectId: "subj-1",
        subjectIdentifier: "SUBJ-001",
        patientId: "patient-1",
        status: "active",
      },
    ]);
    vi.mocked(deleteEnrollment).mockResolvedValue({ id: "subj-1", deleted: true });

    renderAtStudy("study-1");

    await userEvent.click(await screen.findByRole("button", { name: "Remove SUBJ-001" }));

    expect(deleteEnrollment).toHaveBeenCalledWith("subj-1");
    expect(await screen.findByText("No subjects are enrolled in this study yet.")).toBeInTheDocument();
  });

  it("shows a conflict message when the enrolment identifier is already taken", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: "patient-1", researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([
      { id: "patient-1", gender: "female", birthDate: null, deceased: null, active: true },
    ]);
    vi.mocked(enrollPatient).mockRejectedValue(
      new Error("Request to /api/research-studies/study-1/enroll failed with status 409"),
    );

    renderAtStudy("study-1");

    await userEvent.type(await screen.findByLabelText("Subject identifier"), "SUBJ-001");
    await userEvent.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That subject identifier is already in use in this study.",
    );
  });

  it("disables the Enroll button until patients have loaded", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);

    renderAtStudy("study-1");

    expect(await screen.findByRole("button", { name: "Enroll" })).toBeDisabled();
  });

  it("lists the research subjects already enrolled in the study", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);
    vi.mocked(listStudySubjects).mockResolvedValue([
      {
        researchSubjectId: "subj-1",
        subjectIdentifier: "SUBJ-001",
        patientId: "patient-1",
        status: "on-study",
      },
      {
        researchSubjectId: "subj-2-long-id",
        subjectIdentifier: null,
        patientId: "patient-2",
        status: null,
      },
    ]);

    renderAtStudy("study-1");

    const roster = await screen.findByRole("region", { name: "Enrolled research subjects" });
    expect(roster).toBeInTheDocument();
    expect(screen.getByText("on-study")).toBeInTheDocument();
    expect(screen.getByText("subj-2-l")).toBeInTheDocument();
    expect(listStudySubjects).toHaveBeenCalledWith("study-1");

    const subjectLink = screen.getByRole("link", { name: /SUBJ-001/ });
    expect(subjectLink).toHaveAttribute("href", "/subjects/subj-1");
    await userEvent.click(subjectLink);
    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
  });

  it("assigns a subject identifier to a subject without one", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);
    vi.mocked(listStudySubjects).mockResolvedValue([
      {
        researchSubjectId: "subj-2-long-id",
        subjectIdentifier: null,
        patientId: "patient-2",
        status: "active",
      },
    ]);
    vi.mocked(assignSubjectIdentifier).mockResolvedValue({
      researchSubjectId: "subj-2-long-id",
      subjectIdentifier: "SUBJ-002",
      patientId: "patient-2",
      status: "active",
    });

    renderAtStudy("study-1");

    const input = await screen.findByLabelText("Subject identifier for subj-2-l");
    await userEvent.type(input, "SUBJ-002");
    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(await screen.findByText("SUBJ-002")).toBeInTheDocument();
    expect(assignSubjectIdentifier).toHaveBeenCalledWith("subj-2-long-id", "SUBJ-002");
    expect(
      screen.queryByLabelText("Subject identifier for subj-2-l"),
    ).not.toBeInTheDocument();
  });

  it("shows a conflict message when the identifier is already in use", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);
    vi.mocked(listStudySubjects).mockResolvedValue([
      {
        researchSubjectId: "subj-2-long-id",
        subjectIdentifier: null,
        patientId: "patient-2",
        status: "active",
      },
    ]);
    vi.mocked(assignSubjectIdentifier).mockRejectedValue(
      new Error("Request to /api/research-subjects/subj-2-long-id/identifier failed with status 409"),
    );

    renderAtStudy("study-1");

    const input = await screen.findByLabelText("Subject identifier for subj-2-l");
    await userEvent.type(input, "SUBJ-001");
    await userEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(
      await screen.findByText("That subject identifier is already in use in this study."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Subject identifier for subj-2-l")).toBeInTheDocument();
  });

  it("shows an empty state when no subjects are enrolled yet", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockResolvedValue({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: [],
    });
    vi.mocked(listPatients).mockResolvedValue([]);
    vi.mocked(listStudySubjects).mockResolvedValue([]);

    renderAtStudy("study-1");

    expect(
      await screen.findByText("No subjects are enrolled in this study yet."),
    ).toBeInTheDocument();
  });

  it("shows a study details error when the study request fails", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(getResearchStudy).mockRejectedValue(new Error("network error"));
    vi.mocked(listPatients).mockResolvedValue([]);

    renderAtStudy("study-1");

    expect(await screen.findByText("Loading study details…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load study details.");
  });
});
