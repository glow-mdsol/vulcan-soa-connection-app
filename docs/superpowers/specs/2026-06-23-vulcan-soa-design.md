# SMART on FHIR App for Vulcan Schedule of Activities (V2) — Design

## Background

The HL7 Vulcan Schedule of Activities (SoA) Implementation Guide defines a pattern for representing a clinical trial's
schedule of activities — visits, activities, and the transitions between them — as FHIR resources
(`ResearchStudy`, `PlanDefinition`, `ActivityDefinition`), so that EHR/PHR and clinical research systems can
plan and execute a study protocol directly from a digital, computable source of truth.

The IG itself is explicit that representing the structure is not enough: interpreting the V2 graph extensions
(`soaTimepoint`, `soaTransition`) into actual patient progress requires "an application layer" — there is no
standard FHIR `$apply` implementation that understands these custom extensions. This project builds that
application layer as a SMART on FHIR app.

Source of truth for the IG content used in this design is the local ballot source repo
`/Users/GLW1/Documents/Devel/hl7/Vulcan-schedule-ig` (FHIR version `6.0.0-ballot3`, release `STU 2 - Ballot`).

## Problem statement

An EHR user (research/study coordinator or treating clinician/investigator) needs to:

1. Enroll a patient into a `ResearchStudy` whose Schedule of Activities is already defined in the EHR's FHIR
   server as a `StudyProtocolSoa` PlanDefinition graph.
2. View an existing `ResearchSubject`'s status, milestones, and schedule.
3. Schedule and track that subject's study activities within the framework of the FHIR workflow resources the
   IG specifies (`Encounter`, `Task`/`ServiceRequest`/`Appointment`, `CarePlan`), including the V2 dynamic
   features: branching arms, repeating treatment cycles, conditional (applicability) activities, and
   unscheduled visits.

## Goals

- Support both EHR launch (with `patient` context) and a research-study-centric entry point, so users can start
  from either a patient chart or a study worklist.
- Enroll a patient into a `ResearchStudy` and materialize their initial schedule from its protocol's
  `StudyProtocolSoa`/`StudyVisitSoa` graph.
- Resolve, for any `ResearchSubject`, the full V2 graph semantics: linear progression, branching arms, repeating
  treatment cycles (`soaRepeatAllowed`), FHIRPath-based applicability conditions, visit windows, and
  unscheduled-visit insertion/return paths.
- Surface decision support: when more than one outgoing transition is valid and no automatic signal
  distinguishes them, the user — not the engine — chooses.
- Track progress by writing back to standard FHIR workflow resources (`Encounter`, `Task`, `Appointment`,
  `CarePlan`), tagged to their originating `PlanDefinition.action.id` for traceability.

## Non-goals

- **Authoring or publishing Schedule of Activities definitions.** `ResearchStudy`, `PlanDefinition`, and
  `ActivityDefinition` resources are assumed to already exist in the FHIR server, produced by a separate
  study-build process. This app only reads them.
- **Expanding the LZZT example protocol.** The user will separately provide a fuller LZZT protocol
  implementation (beyond what the IG's release-constrained examples contain) directly into the IG source repo /
  Aidbox. This app treats that content purely as an input/fixture once it lands — expanding it is not a
  deliverable of this project.
- **CQL evaluation.** The IG notes CQL as a possible future option for richer conditional logic. V1 supports the
  IG's `text/x-soa-expressionplain` mini-language and FHIRPath only; CQL is out of scope.
- **Multi-tenant study-build tooling, billing, or any non-SoA EHR functionality.**

## Personas

Both personas share the same views, with coordinators doing most of the day-to-day scheduling/tracking legwork
and clinicians using the same dashboard in a more read-and-act capacity (e.g. confirming a decision-support
prompt). No separate role-specific UI is planned for V1; permission differences, if needed, are a future
refinement.

## Key domain concepts (from the IG)

- **`ResearchStudy` / `ResearchSubject`** — link a `Patient` to a study and carry its protocol reference and
  subject-level state/milestones (`subjectState`, arm/`comparisonGroup` assignment).
- **`StudyProtocolSoa` (PlanDefinition)** — the protocol-level graph: each `action` is a node (visit/encounter)
  with a stable `id`; nodes carry the `soaTimepoint` extension (planned offset, window/range, reference
  timepoint, duration, repeat-allowed flag) and child `action`s representing outgoing transitions, each carrying
  a `soaTransition` extension (target id/name, transition type, delay, range) and a `condition` controlling
  whether that path is currently valid.
- **`StudyActivitySoa` (ActivityDefinition)** — an activity scheduled within a visit; may carry an
  `applicability` condition (FHIRPath) gating whether it's required for a given subject.
- **Conditions** come in two flavors used by the IG's own examples: the compact
  `text/x-soa-expressionplain` language for transition gating (e.g. `{'withdrawn':true}`,
  `{'exists':['V1','V2']}`), and `text/fhirpath` for applicability conditions referencing `Condition`,
  `Observation`, or `ResearchSubject` data.
- **FHIR-as-state**: the IG's own unscheduled-visit example computes transition validity from whether prior
  visit instances already exist for the subject — i.e., the subject's existing `Encounter`/`Task` resources
  *are* the state. This app does not maintain a separate position-tracker; it (re)computes position from
  existing instance resources every time.

## Architecture

```
┌─────────────────┐      session cookie       ┌──────────────────────┐      OAuth2 + FHIR REST      ┌─────────────┐
│  React/Vite SPA │ ─────────────────────────▶ │  Python backend (BFF) │ ─────────────────────────▶  │   Aidbox     │
│  (browser)      │ ◀───────────────────────── │  FastAPI             │ ◀─────────────────────────  │  (FHIR R6)  │
└─────────────────┘      JSON API              └──────────────────────┘      ResearchStudy/          └─────────────┘
                                                                              PlanDefinition/
                                                                              ResearchSubject/
                                                                              Encounter/Task/...
```

- **React/Vite SPA**: never talks to Aidbox or holds a FHIR token directly. Calls only the backend's JSON API,
  authenticated via a server-side session cookie (backend-for-frontend pattern).
- **Python backend (FastAPI)**: the SMART confidential client. Handles EHR launch (`patient` context) and a
  research-study-centric entry using the SMART App Launch `fhirContext` parameter (the standard mechanism for
  passing arbitrary resource context, e.g. a `ResearchStudy` reference), plus a standalone launch for the
  general worklist when there's no incoming context. Holds the FHIR access/refresh token server-side, keyed to
  the session.
- **Aidbox (FHIR R6 ballot)**: system of record, run locally, targeted at FHIR R6 ballot to match the IG exactly
  (see Risks). Hosts both the SoA definitions (read-only from this app's perspective) and all per-subject
  instance data.
- The **SoA graph engine** is a self-contained, FHIR-server-agnostic module (plain JSON in, computed
  schedule/decision-support state out), independently testable against the IG's own bundled examples.

## Components

**Backend (FastAPI)**

| Module | Responsibility |
|---|---|
| `auth` | SMART launch (EHR + standalone), `fhirContext`/`patient` parsing, OAuth2 code+PKCE exchange, server-side session store |
| `fhir_client` | Thin Aidbox REST wrapper (search/create/update/conditional-create) working with raw FHIR JSON dicts — R6-ballot resources aren't covered by typed Python FHIR model packages (e.g. `fhir.resources`), so a strict typed layer would block us. Aidbox remains the authority on profile conformance. |
| `soa_engine` | PlanDefinition → DAG parser; condition evaluator (interpreter for `text/x-soa-expressionplain`, plus FHIRPath evaluation via `fhirpathpy` for `applicability` conditions); date/window resolver anchored off existing visit instances. Pure and FHIR-server-agnostic. |
| `scheduling` | Orchestrates: try `PlanDefinition/$apply` for extension-free segments, otherwise drive `soa_engine`; materializes resolved visits/activities as `Encounter`/`Task`/`Appointment`, tagged back to their originating `PlanDefinition.action.id`. |
| `enrollment` | Creates `ResearchSubject`, links to `ResearchStudy`, sets initial milestone/state. |
| `tracking` | Mark visit/activity complete, record outcomes, resolve ambiguous transitions, insert unscheduled visits, record withdrawal/milestones. |
| `api` | FastAPI routers exposing the above as JSON endpoints for the SPA. |

**Frontend (React/Vite)**

- `launch/` — loading/error states while the backend completes the SMART redirect dance.
- `api/` — typed client for the backend's JSON API.
- `views/StudyWorklist` — browse `ResearchStudy`s and their enrolled `ResearchSubject`s.
- `views/Enroll` — search/select a `Patient`, enroll into a chosen `ResearchStudy`.
- `views/SubjectDashboard` — milestones/state, schedule timeline (completed + suggested-next), task list of
  imminent activities, decision-support prompts, and actions (complete visit, add unscheduled visit, record
  withdrawal).

## Data flow

1. **Launch**: EHR redirects to `/launch` with `iss` + `launch` → backend redirects to Aidbox `/authorize` →
   callback to `/callback` with an auth code → backend exchanges it for a token, capturing `patient` and/or
   `fhirContext`-derived `ResearchStudy` id in the server-side session → sets session cookie → redirects into the
   SPA. Standalone launch starts the OAuth2 dance directly from a "Launch" button instead.
2. **Landing view**: SPA calls `GET /api/context` once; backend returns whatever launch context it captured
   (`patientId`, `researchStudyId`, or neither) and the SPA renders the corresponding view.
3. **Enrollment**: `POST /api/research-studies/{id}/enroll {patientId}` → conditional-create `ResearchSubject` →
   `scheduling` resolves the first reachable node(s) (e.g. Screening) → materializes the corresponding
   `Encounter`/`Task` → returns the initial schedule slice.
4. **Viewing a subject's schedule**: `GET /api/research-subjects/{id}/schedule` → backend loads the protocol
   graph (parsed once, cached) and the subject's existing instance resources, asks `soa_engine` to compute
   completed nodes, current position, valid next transition(s) with dates/windows, applicable activities, and
   any points requiring a coordinator decision.
5. **Recording progress**: `POST /api/research-subjects/{id}/visits/{actionId}/complete` (optionally carrying a
   transition choice) → updates `Encounter`/`Task` status, re-runs the engine, materializes next step(s).
6. **Unscheduled visit**: `POST /api/research-subjects/{id}/unscheduled-visits {reason}` → creates an `Encounter`
   tagged as originating from the protocol's "Unscheduled" node, then resolves valid forward paths exactly as
   any other node.

## Error handling

- **Launch/auth failures** → friendly error page, no silent retry loops; user is told to relaunch from the EHR.
- **Aidbox unavailable/timeout** → retryable error surfaced to the SPA; writes that must not duplicate on retry
  (enrollment, unscheduled-visit creation) use conditional-create.
- **Malformed protocol graph** (dangling `soaTargetId`, missing `soaTimepoint`, unreachable/cyclic-without-exit
  nodes) → validated when a protocol is first loaded/parsed, producing a diagnostic naming the offending
  actions, not a runtime failure discovered mid-enrollment.
- **Condition evaluation errors** (a FHIRPath expression fails to parse/evaluate) → fail closed (treated as
  inapplicable) and logged, with a visible warning in the dashboard's decision-support area — never silently
  vanish.
- **Ambiguous transitions** (more than one valid outgoing edge with no automatic signal) → always a required
  decision-support prompt; the backend never auto-selects.
- **Concurrent edits** → rely on FHIR resource versioning (`ETag`/`If-Match`) on instance writes; a conflicting
  write surfaces as "this subject changed, please refresh," never a silent overwrite.

## Testing strategy

- **`soa_engine` unit tests** against the IG's own bundled examples: H2Q-MC-LZZT (linear), Use Case 1 (linear +
  early termination), Use Case 2 (branching arms), Use Case 3 (treatment cycles), the Levothyroxine titration
  example (conditional dose-adjustment), and the Unscheduled-visit example. These are authoritative fixtures
  that already encode the tricky edge cases.
- **Integration tests** against a local Aidbox (Docker) loaded with the IG's StructureDefinitions and example
  resources, exercising real FHIR search/create/update calls.
- **Auth contract tests** for SMART launch (EHR with `patient`/`fhirContext`, and standalone) against mocked or
  sandboxed OAuth endpoints.
- **Frontend**: component tests for the enrollment flow and schedule timeline; Playwright E2E covering the
  golden path — launch → enroll → view schedule → complete a visit → see the next suggested step — against the
  local Aidbox.
- Before any phase is called done: actually run the dev server, perform a real SMART launch against Aidbox, and
  walk the golden path by hand.

## Assumptions & dependencies

- Aidbox is run locally (already available) and will be targeted at FHIR R6 ballot, matching the IG exactly,
  per explicit decision. This is a meaningful risk (see below) but is the chosen path.
- SoA definitions (`ResearchStudy`, `PlanDefinition`, `ActivityDefinition`) are authored and loaded into Aidbox
  by a separate process; this app only consumes them.
- A fuller LZZT protocol implementation will be provided separately (in the IG source repo) as richer test/dev
  data; this app treats it as an external input once available, not something it produces.

## Risks / open items

- **R6 ballot instability**: FHIR R6 is not finalized, and Aidbox's R6 support is early. Resource shapes
  (`ResearchSubject` in particular has changed materially across R4→R5→R6) may shift under us. This should be
  validated early — first phase of implementation should include a spike that loads the IG's
  StructureDefinitions and example resources into Aidbox and confirms basic CRUD/search works before deeper
  engine work proceeds.
- **Treatment cycle complexity**: repeating cycles (`soaRepeatAllowed`) with even/odd variation (Use Case 3) are
  the most structurally complex part of the graph engine and may reveal the need for additional modeling beyond
  what's directly inferable from the current extensions.
- **FHIRPath library maturity against R6 data**: `fhirpathpy` (or equivalent) needs validation against the kinds
  of expressions the IG's conditional-activity examples actually use (simple `where()`/`exists()` queries
  against `Condition`/`ResearchSubject`); deeper FHIRPath features are not expected to be needed for V1.
