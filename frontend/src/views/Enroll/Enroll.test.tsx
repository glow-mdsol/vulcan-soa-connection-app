import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { enrollPatient, getContext } from "../../api/client";
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
  });

  it("enrolls the patient from launch context without asking for manual input", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: "patient-1", researchStudyId: null });
    vi.mocked(enrollPatient).mockResolvedValue({
      researchSubjectId: "subj-1",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false, visits: {} },
    });

    renderAtStudy("study-1");

    expect(await screen.findByText("Patient: patient-1")).toBeInTheDocument();
    expect(screen.queryByLabelText("Patient FHIR ID")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
    expect(enrollPatient).toHaveBeenCalledWith("study-1", "patient-1");
  });

  it("accepts a manually entered patient id when there is no launch context", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });
    vi.mocked(enrollPatient).mockResolvedValue({
      researchSubjectId: "subj-2",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false, visits: {} },
    });

    renderAtStudy("study-1");

    const input = await screen.findByLabelText("Patient FHIR ID");
    await userEvent.type(input, "uc1-demo-patient");
    await userEvent.click(screen.getByRole("button", { name: "Enroll" }));

    expect(await screen.findByText("Subject dashboard")).toBeInTheDocument();
    expect(enrollPatient).toHaveBeenCalledWith("study-1", "uc1-demo-patient");
  });

  it("disables the Enroll button until a patient id is available", async () => {
    vi.mocked(getContext).mockResolvedValue({ patientId: null, researchStudyId: null });

    renderAtStudy("study-1");

    expect(await screen.findByRole("button", { name: "Enroll" })).toBeDisabled();
  });
});
