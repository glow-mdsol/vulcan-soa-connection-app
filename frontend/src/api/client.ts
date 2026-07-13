import type {
  Context,
  DeleteEnrollmentResult,
  EnrollResult,
  NextStep,
  PatientSummary,
  ProtocolTreeNode,
  RecordMilestoneResult,
  RequestEventTreeNode,
  ResearchStudyDetail,
  ResearchStudySummary,
  Schedule,
  StudySubjectSummary,
  VisitActivity,
  VisitDetail,
  WithdrawResult,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: "include" });
  if (!response.ok) {
    throw new Error(`Request to ${url} failed with status ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function postJson<T>(url: string, body: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getContext(): Promise<Context> {
  return request<Context>("/api/context");
}

export function logout(): Promise<void> {
  return request<void>("/api/context", { method: "DELETE" });
}

export function listResearchStudies(): Promise<ResearchStudySummary[]> {
  return request<ResearchStudySummary[]>("/api/research-studies");
}

export function getResearchStudy(studyId: string): Promise<ResearchStudyDetail> {
  return request<ResearchStudyDetail>(`/api/research-studies/${studyId}`);
}

export function getProtocolTree(
  studyId: string,
  planDefinitionId: string | null = null,
): Promise<ProtocolTreeNode> {
  const query = planDefinitionId
    ? `?planDefinitionId=${encodeURIComponent(planDefinitionId)}`
    : "";
  return request<ProtocolTreeNode>(`/api/research-studies/${studyId}/protocol-tree${query}`);
}

export function listStudySubjects(studyId: string): Promise<StudySubjectSummary[]> {
  return request<StudySubjectSummary[]>(`/api/research-studies/${studyId}/subjects`);
}

export function listPatients(): Promise<PatientSummary[]> {
  return request<PatientSummary[]>("/api/patients");
}

export function enrollPatient(
  studyId: string,
  patientId: string,
  subjectIdentifier: string,
  planDefinitionId: string | null = null,
): Promise<EnrollResult> {
  return postJson<EnrollResult>(`/api/research-studies/${studyId}/enroll`, {
    patientId,
    subjectIdentifier,
    planDefinitionId,
  });
}

export function deleteEnrollment(subjectId: string): Promise<DeleteEnrollmentResult> {
  return request<DeleteEnrollmentResult>(`/api/research-subjects/${subjectId}`, {
    method: "DELETE",
  });
}

export function assignSubjectIdentifier(
  subjectId: string,
  subjectIdentifier: string,
): Promise<StudySubjectSummary> {
  return postJson<StudySubjectSummary>(`/api/research-subjects/${subjectId}/identifier`, {
    subjectIdentifier,
  });
}

export function recordMilestone(
  subjectId: string,
  milestone: string,
  date: string | null = null,
  display: string | null = null,
): Promise<RecordMilestoneResult> {
  return postJson<RecordMilestoneResult>(`/api/research-subjects/${subjectId}/milestones`, {
    milestone,
    display,
    date,
  });
}

export function getRequestEventTree(subjectId: string): Promise<RequestEventTreeNode> {
  return request<RequestEventTreeNode>(`/api/research-subjects/${subjectId}/request-event-tree`);
}

export function getSchedule(subjectId: string): Promise<Schedule> {
  return request<Schedule>(`/api/research-subjects/${subjectId}/schedule`);
}

export function listVisitActivities(
  subjectId: string,
  actionId: string,
): Promise<VisitActivity[]> {
  return request<VisitActivity[]>(
    `/api/research-subjects/${subjectId}/visits/${actionId}/activities`,
  );
}

export function completeVisit(
  subjectId: string,
  actionId: string,
  transitionChoice: string | null,
): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/complete`, {
    transitionChoice,
  });
}

export function promoteVisit(
  subjectId: string,
  actionId: string,
  step: "plan" | "order",
): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/${step}`, undefined);
}

export function scheduleVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/schedule`, undefined);
}

export function expediteVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/expedite`, undefined);
}

export function respondToAppointment(
  subjectId: string,
  actionId: string,
  participant: "patient" | "site",
  response: "accepted" | "declined",
): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/respond`, {
    participant,
    response,
  });
}

export function performVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/perform`, undefined);
}

export function completeTask(subjectId: string, actionId: string, taskId: string): Promise<Schedule> {
  return postJson<Schedule>(
    `/api/research-subjects/${subjectId}/visits/${actionId}/tasks/${taskId}/complete`,
    undefined,
  );
}

export function withdrawSubject(subjectId: string): Promise<WithdrawResult> {
  return postJson<WithdrawResult>(`/api/research-subjects/${subjectId}/withdraw`, undefined);
}

export type { NextStep, VisitDetail };
