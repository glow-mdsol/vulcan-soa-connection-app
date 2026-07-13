import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getRequestEventTree } from "../../api/client";
import type { RequestEventTreeNode } from "../../api/types";
import RequestEventTree from "./RequestEventTree";

vi.mock("../../api/client");

const TREE: RequestEventTreeNode = {
  id: "subj-1",
  type: "ResearchSubject",
  label: "SUBJ-001",
  children: [
    {
      id: "sr-visit-proposal",
      type: "ServiceRequest",
      label: "Screening — proposal · completed",
      children: [
        {
          id: "sr-act-order",
          type: "ServiceRequest",
          label: "Vital Signs — order · active",
          children: [
            {
              id: "task-1",
              type: "Task",
              label: "Vital Signs — ready",
              children: [],
            },
          ],
        },
        {
          id: "sr-visit-order",
          type: "ServiceRequest",
          label: "Screening — order · active",
          children: [
            {
              id: "appt-1",
              type: "Appointment",
              label: "Appointment — booked",
              children: [
                { id: "enc-1", type: "Encounter", label: "Encounter — in-progress", children: [] },
              ],
            },
          ],
        },
      ],
    },
  ],
};

function renderAt(subjectId: string) {
  return render(
    <MemoryRouter initialEntries={[`/subjects/${subjectId}/request-event-tree`]}>
      <Routes>
        <Route path="/subjects/:subjectId/request-event-tree" element={<RequestEventTree />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RequestEventTree", () => {
  beforeEach(() => {
    vi.mocked(getRequestEventTree).mockReset();
  });

  it("renders the materialized request/event lineage with a legend and text outline", async () => {
    vi.mocked(getRequestEventTree).mockResolvedValue(TREE);

    renderAt("subj-1");

    expect(getRequestEventTree).toHaveBeenCalledWith("subj-1");

    const svg = await screen.findByRole("img", {
      name: "Request / event diagram for SUBJ-001",
    });
    expect(svg).toBeInTheDocument();

    const legend = screen.getByRole("list", { name: "Legend" });
    expect(legend).toHaveTextContent("Research Subject");
    expect(legend).toHaveTextContent("Service Request");
    expect(legend).toHaveTextContent("Appointment");
    expect(legend).toHaveTextContent("Encounter");
    expect(legend).toHaveTextContent("Task");
    // Not present in this fixture, so it should be absent from the legend.
    expect(legend).not.toHaveTextContent("Procedure");

    const outline = screen.getByRole("list", { name: "Text outline" });
    expect(outline.textContent).toContain("Appointment — booked (Appointment)");
    expect(outline.textContent).toContain("Encounter — in-progress (Encounter)");
  });

  it("shows an empty-state message when nothing has been materialized yet", async () => {
    vi.mocked(getRequestEventTree).mockResolvedValue({
      id: "subj-2",
      type: "ResearchSubject",
      label: "SUBJ-002",
      children: [],
    });

    renderAt("subj-2");

    expect(
      await screen.findByText(
        "Nothing has been materialized for this subject yet — no requests, appointments, or tasks exist so far.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error message when the tree fails to load", async () => {
    vi.mocked(getRequestEventTree).mockRejectedValue(new Error("network error"));

    renderAt("subj-1");

    expect(
      await screen.findByText("Could not load the request/event diagram for this subject."),
    ).toBeInTheDocument();
  });
});
