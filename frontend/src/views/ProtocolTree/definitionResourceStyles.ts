import type { ProtocolResourceType } from "../../api/types";

// Fixed categorical order (never re-cycled) — one colour per FHIR resource type,
// validated for CVD-safe adjacent contrast against a white surface.
export const DEFINITION_TYPE_ORDER: ProtocolResourceType[] = [
  "ResearchStudy",
  "PlanDefinition",
  "ActivityDefinition",
  "Questionnaire",
  "ObservationDefinition",
];

export const DEFINITION_RESOURCE_STYLES: Record<
  ProtocolResourceType,
  { label: string; stroke: string; fill: string }
> = {
  ResearchStudy: { label: "Research Study", stroke: "#2a78d6", fill: "#dceaf9" },
  PlanDefinition: { label: "Plan Definition (protocol / visit)", stroke: "#1baf7a", fill: "#dcf3ea" },
  ActivityDefinition: { label: "Activity Definition", stroke: "#eda100", fill: "#fdf1d9" },
  Questionnaire: { label: "Questionnaire", stroke: "#008300", fill: "#dcecdc" },
  ObservationDefinition: { label: "Observation Definition", stroke: "#4a3aa7", fill: "#e3e0f3" },
};
