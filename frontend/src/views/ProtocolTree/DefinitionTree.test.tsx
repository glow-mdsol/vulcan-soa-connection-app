import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getProtocolTree } from "../../api/client";
import type { ProtocolTreeNode } from "../../api/types";
import DefinitionTree from "./DefinitionTree";

vi.mock("../../api/client");

const TREE: ProtocolTreeNode = {
  id: "study-1",
  type: "ResearchStudy",
  label: "UC1 Demo Study",
  children: [
    {
      id: "plan-1",
      type: "PlanDefinition",
      label: "UC1 Protocol",
      children: [
        {
          id: "screening-1",
          type: "PlanDefinition",
          label: "Screening",
          children: [
            {
              id: "act-vitals",
              type: "ActivityDefinition",
              label: "Vital Signs",
              children: [
                {
                  id: "od-temp",
                  type: "ObservationDefinition",
                  label: "Body temperature",
                  children: [],
                },
              ],
            },
            {
              id: "q-adas-cog",
              type: "Questionnaire",
              label: "ADAS-Cog",
              children: [],
            },
          ],
        },
      ],
    },
  ],
};

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/studies/:studyId/protocol-tree" element={<DefinitionTree />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DefinitionTree", () => {
  beforeEach(() => {
    vi.mocked(getProtocolTree).mockReset();
    vi.stubGlobal("print", vi.fn());
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:mock"), revokeObjectURL: vi.fn() });
  });

  it("renders every resource as a node, a legend entry per type present, and a text outline", async () => {
    vi.mocked(getProtocolTree).mockResolvedValue(TREE);

    renderAt("/studies/study-1/protocol-tree?plan=plan-1");

    expect(getProtocolTree).toHaveBeenCalledWith("study-1", "plan-1");

    const svg = await screen.findByRole("img", { name: "Definition diagram for UC1 Demo Study" });
    expect(svg).toBeInTheDocument();

    const legend = screen.getByRole("list", { name: "Legend" });
    expect(legend).toHaveTextContent("Research Study");
    expect(legend).toHaveTextContent("Plan Definition");
    expect(legend).toHaveTextContent("Activity Definition");
    expect(legend).toHaveTextContent("Questionnaire");
    expect(legend).toHaveTextContent("Observation Definition");

    const outline = screen.getByRole("list", { name: "Text outline" });
    expect(outline.textContent).toContain("Vital Signs (Activity Definition)");
    expect(outline.textContent).toContain("Body temperature (Observation Definition)");
  });

  it("shows an error message when the tree fails to load", async () => {
    vi.mocked(getProtocolTree).mockRejectedValue(new Error("network error"));

    renderAt("/studies/study-1/protocol-tree");

    expect(
      await screen.findByText("Could not load the workflow diagram for this study."),
    ).toBeInTheDocument();
  });

  it("triggers the browser print dialog from the Print button", async () => {
    vi.mocked(getProtocolTree).mockResolvedValue(TREE);
    renderAt("/studies/study-1/protocol-tree");

    await userEvent.click(await screen.findByRole("button", { name: "Print" }));

    expect(window.print).toHaveBeenCalled();
  });
});
