import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  assignSubjectIdentifier,
  completeVisit,
  deleteEnrollment,
  enrollPatient,
  getContext,
  getProtocolTree,
  getRequestEventTree,
  getResearchStudy,
  getSchedule,
  listResearchStudies,
  listStudySubjects,
  listVisitActivities,
  logout,
  recordMilestone,
  withdrawSubject,
} from "./client";

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  const response = { ok, status, json: () => Promise.resolve(body) } as Response;
  vi.mocked(fetch).mockResolvedValueOnce(response);
  return response;
}

describe("api client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("getContext calls GET /api/context with credentials included", async () => {
    mockFetchOnce({ patientId: "patient-1", researchStudyId: null });

    const context = await getContext();

    expect(context).toEqual({ patientId: "patient-1", researchStudyId: null });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/context");
    expect(init?.credentials).toBe("include");
  });

  it("listResearchStudies calls GET /api/research-studies", async () => {
    mockFetchOnce([{ id: "study-1", title: "UC1 Demo Study" }]);

    const studies = await listResearchStudies();

    expect(studies).toEqual([{ id: "study-1", title: "UC1 Demo Study" }]);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/research-studies");
  });

  it("getResearchStudy calls GET /api/research-studies/{id}", async () => {
    mockFetchOnce({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1"],
    });

    const study = await getResearchStudy("study-1");

    expect(study).toEqual({
      id: "study-1",
      title: "UC1 Demo Study",
      status: "active",
      protocolReferences: ["PlanDefinition/plan-1"],
    });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/research-studies/study-1");
  });

  it("listStudySubjects calls GET /api/research-studies/{id}/subjects", async () => {
    mockFetchOnce([
      {
        researchSubjectId: "subj-1",
        subjectIdentifier: "SUBJ-001",
        patientId: "patient-1",
        status: "on-study",
      },
    ]);

    const subjects = await listStudySubjects("study-1");

    expect(subjects).toEqual([
      {
        researchSubjectId: "subj-1",
        subjectIdentifier: "SUBJ-001",
        patientId: "patient-1",
        status: "on-study",
      },
    ]);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/research-studies/study-1/subjects");
  });

  it("assignSubjectIdentifier posts the identifier as JSON", async () => {
    mockFetchOnce({
      researchSubjectId: "subj-1",
      subjectIdentifier: "SUBJ-001",
      patientId: "patient-1",
      status: "active",
    });

    const summary = await assignSubjectIdentifier("subj-1", "SUBJ-001");

    expect(summary.subjectIdentifier).toBe("SUBJ-001");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-subjects/subj-1/identifier");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(JSON.stringify({ subjectIdentifier: "SUBJ-001" }));
  });

  it("recordMilestone posts the milestone, display, and date as JSON", async () => {
    mockFetchOnce({
      researchSubjectId: "subj-1",
      milestones: [{ milestone: "C114209", display: "Subject is Randomized", date: "2026-07-08" }],
    });

    const result = await recordMilestone("subj-1", "C114209", "2026-07-08", "Subject is Randomized");

    expect(result.milestones).toEqual([
      { milestone: "C114209", display: "Subject is Randomized", date: "2026-07-08" },
    ]);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-subjects/subj-1/milestones");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe(
      JSON.stringify({ milestone: "C114209", display: "Subject is Randomized", date: "2026-07-08" }),
    );
  });

  it("listVisitActivities calls GET /visits/{actionId}/activities", async () => {
    mockFetchOnce([
      {
        id: "act-vitals",
        title: "Vital Signs",
        type: "ActivityDefinition",
        observations: [{ id: "od-1", display: "Systolic blood pressure", members: [] }],
      },
    ]);

    const activities = await listVisitActivities("subj-1", "screening-1");

    expect(activities).toHaveLength(1);
    expect(activities[0].type).toBe("ActivityDefinition");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "/api/research-subjects/subj-1/visits/screening-1/activities",
    );
  });

  it("getProtocolTree calls GET /protocol-tree without a plan filter", async () => {
    mockFetchOnce({ id: "study-1", type: "ResearchStudy", label: "UC1 Demo Study", children: [] });

    const tree = await getProtocolTree("study-1");

    expect(tree.type).toBe("ResearchStudy");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "/api/research-studies/study-1/protocol-tree",
    );
  });

  it("getProtocolTree includes planDefinitionId as a query param when given", async () => {
    mockFetchOnce({ id: "study-1", type: "ResearchStudy", label: "UC1 Demo Study", children: [] });

    await getProtocolTree("study-1", "plan-2");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "/api/research-studies/study-1/protocol-tree?planDefinitionId=plan-2",
    );
  });

  it("getRequestEventTree calls GET /research-subjects/{id}/request-event-tree", async () => {
    mockFetchOnce({ id: "subj-1", type: "ResearchSubject", label: "SUBJ-001", children: [] });

    const tree = await getRequestEventTree("subj-1");

    expect(tree.type).toBe("ResearchSubject");
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "/api/research-subjects/subj-1/request-event-tree",
    );
  });

  it("logout calls DELETE /api/context", async () => {
    mockFetchOnce({}, true, 204);

    await logout();

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/context");
    expect(init?.method).toBe("DELETE");
    expect(init?.credentials).toBe("include");
  });

  it("enrollPatient posts the patientId and subjectIdentifier as JSON", async () => {
    mockFetchOnce({
      researchSubjectId: "subj-1",
      schedule: { completed: [], current: [], nextSteps: [], ambiguous: false },
    });

    const result = await enrollPatient("study-1", "patient-1", "SUBJ-001", "plan-2");

    expect(result.researchSubjectId).toBe("subj-1");
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-studies/study-1/enroll");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({
      patientId: "patient-1",
      subjectIdentifier: "SUBJ-001",
      planDefinitionId: "plan-2",
    });
  });

  it("deleteEnrollment calls DELETE /api/research-subjects/{id}", async () => {
    mockFetchOnce({ id: "subj-1", deleted: true });

    const result = await deleteEnrollment("subj-1");

    expect(result).toEqual({ id: "subj-1", deleted: true });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-subjects/subj-1");
    expect(init?.method).toBe("DELETE");
  });

  it("getSchedule calls GET /api/research-subjects/{id}/schedule", async () => {
    mockFetchOnce({ completed: [], current: [], nextSteps: [], ambiguous: false });

    await getSchedule("subj-1");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/research-subjects/subj-1/schedule");
  });

  it("completeVisit posts the transition choice", async () => {
    mockFetchOnce({ completed: [], current: [], nextSteps: [], ambiguous: false });

    await completeVisit("subj-1", "action-1", "day7-1");

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-subjects/subj-1/visits/action-1/complete");
    expect(JSON.parse(init?.body as string)).toEqual({ transitionChoice: "day7-1" });
  });

  it("withdrawSubject posts to the withdraw endpoint", async () => {
    mockFetchOnce({ id: "subj-1", subjectState: "withdrawn" });

    const result = await withdrawSubject("subj-1");

    expect(result).toEqual({ id: "subj-1", subjectState: "withdrawn" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/research-subjects/subj-1/withdraw");
    expect(init?.method).toBe("POST");
  });

  it("throws when the response is not ok", async () => {
    mockFetchOnce({}, false, 401);

    await expect(getContext()).rejects.toThrow();
  });
});
