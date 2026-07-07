export interface Context {
  patientId: string | null;
  researchStudyId: string | null;
}

export interface ResearchStudySummary {
  id: string;
  title: string;
}

export interface ResearchStudyDetail {
  id: string;
  title: string;
  status: string | null;
  protocolReferences: string[];
}

export type PatientGender = "male" | "female" | "other" | "unknown";

export interface PatientSummary {
  id: string;
  gender: PatientGender | null;
  birthDate: string | null;
  deceased: boolean | null;
  active: boolean | null;
}

export interface NextStep {
  actionId: string;
  title: string;
  transitionType: string | null;
}

export type VisitPhase =
  | "proposed"
  | "planned"
  | "ordered"
  | "scheduled"
  | "booked"
  | "performing"
  | "completed"
  | "revoked";

export interface Participant {
  role: "patient" | "site" | "other";
  status: string;
}

export interface VisitTask {
  id: string;
  description: string;
  status: string;
}

export interface VisitDetail {
  phase: VisitPhase;
  participants?: Participant[];
  tasks?: VisitTask[];
}

export interface Schedule {
  completed: string[];
  current: string[];
  nextSteps: NextStep[];
  ambiguous: boolean;
  visits: Record<string, VisitDetail>;
  titles?: Record<string, string>;
}

export interface EnrollResult {
  researchSubjectId: string;
  schedule: Schedule;
}

export interface WithdrawResult {
  id: string;
  subjectState: string;
}
