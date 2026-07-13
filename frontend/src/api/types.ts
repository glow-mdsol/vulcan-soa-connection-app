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

export interface ActivityObservation {
  id: string;
  display: string;
  members: ActivityObservation[];
}

export interface VisitActivity {
  id: string;
  title: string;
  type: "ActivityDefinition" | "Questionnaire";
  observations: ActivityObservation[];
}

export interface SubjectMilestone {
  milestone: string;
  display: string | null;
  date: string | null;
}

export interface WorkUnit {
  id: string;
  title: string;
  status: string;
  description: string | null;
}

export interface Schedule {
  completed: string[];
  current: string[];
  nextSteps: NextStep[];
  ambiguous: boolean;
  visits: Record<string, VisitDetail>;
  titles?: Record<string, string>;
  subjectIdentifier?: string | null;
  subjectStatus?: string | null;
  subjectState?: string | null;
  milestones?: SubjectMilestone[];
  studyId?: string;
  planDefinitionId?: string;
}

// Shared shape for both the static (definition) and instance (request/event)
// workflow diagrams — generic over the resource-type domain each one uses.
export interface WorkflowTreeNode<TType extends string = string> {
  id: string;
  type: TType;
  label: string;
  children: WorkflowTreeNode<TType>[];
}

export type ProtocolResourceType =
  | "ResearchStudy"
  | "PlanDefinition"
  | "ActivityDefinition"
  | "Questionnaire"
  | "ObservationDefinition";

export type ProtocolTreeNode = WorkflowTreeNode<ProtocolResourceType>;

export type RequestEventResourceType =
  | "ResearchSubject"
  | "ServiceRequest"
  | "Appointment"
  | "Encounter"
  | "Task"
  | "Procedure";

export type RequestEventTreeNode = WorkflowTreeNode<RequestEventResourceType>;

export interface RecordMilestoneResult {
  researchSubjectId: string;
  milestones: SubjectMilestone[];
}

export interface StudySubjectSummary {
  researchSubjectId: string;
  subjectIdentifier: string | null;
  patientId: string;
  status: string | null;
}

export interface EnrollResult {
  researchSubjectId: string;
  schedule: Schedule;
}

export interface DeleteEnrollmentResult {
  id: string;
  deleted: boolean;
}

export interface WithdrawResult {
  id: string;
  subjectState: string;
}
