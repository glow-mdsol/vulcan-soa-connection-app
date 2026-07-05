import type {
  Context,
  EnrollResult,
  NextStep,
  ResearchStudySummary,
  Schedule,
  VisitDetail,
  WithdrawResult,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, credentials: "include" });
  if (!response.ok) {
    throw new Error(`Request to ${url} failed with status ${response.status}`);
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

export function listResearchStudies(): Promise<ResearchStudySummary[]> {
  return request<ResearchStudySummary[]>("/api/research-studies");
}

export function enrollPatient(studyId: string, patientId: string): Promise<EnrollResult> {
  return postJson<EnrollResult>(`/api/research-studies/${studyId}/enroll`, { patientId });
}

export function getSchedule(subjectId: string): Promise<Schedule> {
  return request<Schedule>(`/api/research-subjects/${subjectId}/schedule`);
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
