import type { RequestEventResourceType } from "../../api/types";

// Fixed categorical order (never re-cycled) — validated for CVD-safe adjacent
// contrast against a white surface, same method as the definition tree's palette.
export const EVENT_TYPE_ORDER: RequestEventResourceType[] = [
  "ResearchSubject",
  "ServiceRequest",
  "Appointment",
  "Encounter",
  "Task",
  "Procedure",
];

export const EVENT_RESOURCE_STYLES: Record<
  RequestEventResourceType,
  { label: string; stroke: string; fill: string }
> = {
  ResearchSubject: { label: "Research Subject", stroke: "#2a78d6", fill: "#dceaf9" },
  ServiceRequest: { label: "Service Request", stroke: "#1baf7a", fill: "#dcf3ea" },
  Appointment: { label: "Appointment", stroke: "#eda100", fill: "#fdf1d9" },
  Encounter: { label: "Encounter", stroke: "#008300", fill: "#dcecdc" },
  Task: { label: "Task", stroke: "#4a3aa7", fill: "#e3e0f3" },
  Procedure: { label: "Procedure", stroke: "#e34948", fill: "#fbdedd" },
};
