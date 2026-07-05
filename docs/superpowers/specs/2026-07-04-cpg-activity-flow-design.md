# CPG Activity Flow for Study Visits — Design

**Date:** 2026-07-04
**Status:** Draft, awaiting user review
**References:** [FHIR CPG IG — Activity Flow](https://hl7.org/fhir/uv/cpg/activityflow.html),
[FHIR Workflow Module](https://build.fhir.org/workflow.html)

## Goal

Reproduce the CPG activity lifecycle — `definition → proposal → plan → order → event` —
inside the vulcan-soa app, outside any EHR, as a Connectathon demo track. The visible
deliverable is the full request chain inspectable in Aidbox: every phase a distinct
resource, linked by `basedOn`, instantiating its definition, with the CPG status
machine (`active → completed`, `active → revoked`) honoured.

The app plays all three CPG actors:

| CPG actor | Played by |
|---|---|
| Clinical reasoning system | SoA engine (emits proposals) |
| Workflow system | BFF + SPA (coordinator accepts/authorizes) |
| Performer | Study coordinator via the UI |

Beyond the CPG request chain, the design uses the wider
[FHIR workflow module](https://build.fhir.org/workflow.html): `Appointment` /
`AppointmentResponse` for the scheduling/engagement layer between order and event
(Patient and site staff as participants), and `Task` as the fulfillment resource
enumerating the activities inside each Encounter. These are the engagement surfaces
that matter for planning and executing a visit in the IG's target workflow.

**Fidelity caveat:** the CPG IG is R4-based; our stack is FHIR R6 ballot3. We reproduce
the *pattern* (intent ladder, `basedOn` chains, state transitions), not CPG profile
conformance. CPG's two-step prepare/initiate operations collapse to one BFF call per
gate — the "application-level interaction" those two steps exist to allow *is* our UI.

## Decisions made during brainstorming

- **Goal:** Connectathon demo track (standards-faithful chain is the point).
- **Scope:** visits *and* in-visit activities get the lifecycle.
- **Protocol:** the WIP PhUSE IG (`~/Documents/Devel/phuseorg/fhir-schedule-of-activities-ig`),
  specifically the USDM chain — it is R6-ballot3 and complete:
  `PlanDefinition/H2Q-MC-LZZT-ProtocolDesign-USDM` (soaTransition graph + `definitionUri`
  per visit) → `E*-USDM` visit PlanDefinitions → 31 `usdm-act-*` ActivityDefinitions
  (`kind: ServiceRequest`, CDISC codes, `observationResultRequirement`).
- **UX:** visit-level gates. Coordinator promotes per visit; in-visit activity requests
  cascade in bulk with their visit.
- **Approach:** new request resource per phase, promotion via BFF endpoints
  (chosen over Aidbox custom operations and over mutating `intent` in place).
- **Scheduling & engagement:** `Appointment` + `AppointmentResponse` between order and
  event; Patient and site staff respond before the visit is performed.
- **Task UX:** hybrid — Tasks enumerate the encounter's activities and can be ticked
  one by one, but "Complete visit" is always available and sweeps the remainder.

## Section 1 — Resource model & lifecycle

### Visit chain (one per SoA node)

```
SR intent=proposal ─basedOn→ SR intent=plan ─basedOn→ SR intent=order
                                                        │ basedOn
                                                        ▼
                                       Appointment (proposed)
                                         ├─ AppointmentResponse (Patient: accepted)
                                         ├─ AppointmentResponse (site staff: accepted)
                                         └─→ Appointment (booked)
                                              │
                                              ▼
                                       Encounter (in-progress, appointment: [ref], event)
                                         └─ Task per activity (see below)
```

- All ServiceRequests carry `instantiatesUri` → the visit PlanDefinition
  (e.g. `PlanDefinition/H2Q-MC-LZZT-E2-USDM`) and the action-tag identifier
  `urn:vulcan-soa:plan-action | <protocolPdId>#<actionId>` — the tag goes on **every**
  resource in the chain (Appointment, Encounter, and Tasks included).
- Each promotion **creates a new** ServiceRequest (`status: active`) and marks its
  predecessor `status: completed`.
- Requests authored together in one promotion (visit + its activities) share a
  group identifier (`<protocolPdId>#<actionId>:<intent>`) — the workflow module's
  lightweight grouping, standing in for RequestOrchestration. *(Implementation
  note, confirmed against live Aidbox R6: on `ServiceRequest` this field is named
  `requisition`, not `groupIdentifier`.)*
- Phase is derived from resourceType + `intent`/`status`; chain membership from the
  shared action-tag identifier (existing `ACTION_TAG_SYSTEM`).

### Scheduling & engagement layer

- `schedule` creates an `Appointment` (`status: proposed`, `basedOn` the visit order)
  with participant slots for the Patient and a site-staff `Practitioner`
  (`participationStatus: needs-action`).
- Since the demo has no patient portal, the UI simulates engagement: "Patient accepts"
  and "Site confirms" buttons write real `AppointmentResponse` resources
  (`participantStatus: accepted`); the BFF updates the matching participant and flips
  the Appointment to `booked` once all participants have accepted.
- A `declined` response leaves the Appointment `proposed` and the participant
  `declined`; re-responding is allowed. A rebooking/renegotiation flow is out of scope.
- `perform` requires a `booked` Appointment and creates the Encounter
  (`status: in-progress`, `appointment` → the Appointment, `basedOn` the order).
  One Appointment maps to one Encounter here; the model extends to recurring/multi-
  encounter appointments but the demo does not.

### Task layer (fulfillment inside the Encounter)

- `perform` also creates one `Task` per activity order: `status: ready`,
  `basedOn` → the activity SR order, `focus` → the same SR, `for` → the Patient,
  `encounter` → the Encounter, `code`/`description` from the ActivityDefinition.
- Hybrid completion: staff can tick Tasks one by one (`ready → completed`, each
  writing the activity's `Procedure` — `status: completed`, `basedOn` the activity
  order, `encounter` → the Encounter — referenced from `Task.output`), **or** hit
  "Complete visit", which sweeps every remaining non-completed Task to `completed`
  with its Procedure before closing the Encounter.

### Activity chain (cascades with the visit)

- At visit-proposal time the BFF reads the visit PlanDefinition (via the protocol
  action's `definitionUri`) and, for each action with a `definitionUri` →
  ActivityDefinition, creates an activity ServiceRequest:
  `intent: proposal`, `instantiatesUri` → the AD, `code` from `AD.code`,
  `basedOn` → the visit proposal, same action-tag identifier plus an activity
  discriminator (`<protocolPdId>#<actionId>#<activityAdId>`).
- Visit promotions cascade: each activity gets its next-phase request with
  `basedOn: [its own predecessor, the visit's new request]`; predecessors are completed.
- Activity **events** are `Procedure` resources written when the activity's Task
  completes (individually or via the visit-completion sweep — see Task layer above).
- Stretch goal, explicitly out of scope for the first build: `Observation` stubs from
  the ADs' `observationResultRequirement` ObservationDefinitions.

### Withdrawal

`withdraw_subject` additionally revokes every still-active request in the subject's
chains (`status: revoked`), cancels any non-terminal Appointments (`cancelled`) and
Tasks (`cancelled`), then retires the ResearchSubject — demonstrating the CPG
`active → revoked` transition across the whole workflow surface.

## Section 2 — Definitions & fixtures

- New fixture `ResearchStudy/lzzt-usdm-demo-study` with `protocol` →
  `PlanDefinition/H2Q-MC-LZZT-ProtocolDesign-USDM`. The `uc1` exit-example study stays
  as a regression fixture.
- New fixture `Practitioner/site-coordinator-demo` (site staff) used as the second
  Appointment participant alongside the Patient.
- New Taskfile target `fixtures:load-soa-ig` loading the WIP IG's
  `fsh-generated/resources/` via the existing generic loader. Path from
  `SOA_IG_RESOURCES_DIR`, default
  `~/Documents/Devel/phuseorg/fhir-schedule-of-activities-ig/fsh-generated/resources`.
- `soa_engine/graph.py` accepts both extension base URLs when locating
  `soaTransition`/`soaTimepoint`: `http://hl7.org/fhir/uv/vulcan-schedule/StructureDefinition/…`
  and `http://example.org/br-and-r/soa/StructureDefinition/…`.
- **Drift guard:** the WIP IG is moving. Everything the app relies on (protocol action
  `id`s present, `definitionUri` targets resolvable in the loaded set) is asserted by
  the fixture loader at load time so drift fails loudly before a demo, not during one.

## Section 3 — Backend

New module `backend/src/vulcan_soa/activity_flow.py` owning the request lifecycle:

- `materialize_proposal(client, patient_id, plan_definition_id, node)` — replaces
  `materialize_visit` as the engine's output. Creates the visit proposal + activity
  proposals (reads visit PD and its ADs from Aidbox).
- `promote(client, subject_id, action_id, to_phase)` — validates the current phase from
  the chain (wrong-phase attempts → 409), creates the next visit request, cascades the
  activity requests, completes predecessors.
- `schedule(client, subject_id, action_id)` — creates the Appointment (`proposed`) from
  the order, with Patient + site-staff participant slots.
- `respond(client, subject_id, action_id, participant, response)` — writes an
  `AppointmentResponse`, updates the participant's status, books the Appointment when
  all participants have accepted.
- `perform(client, subject_id, action_id)` — requires a booked Appointment; creates the
  Encounter (`in-progress`) and one `ready` Task per activity order.
- `complete_task(client, subject_id, action_id, task_id)` — Task `completed` + activity
  `Procedure`, Procedure referenced from `Task.output`.
- `complete(client, subject_id, action_id, transition_choice)` — sweeps remaining Tasks
  to `completed` (with Procedures), completes the Encounter, then materializes the
  *next* visit's proposal (absorbs today's `tracking.complete_visit`).

API additions (join existing `complete` and `withdraw`):

```
POST /api/research-subjects/{id}/visits/{actionId}/plan
POST /api/research-subjects/{id}/visits/{actionId}/order
POST /api/research-subjects/{id}/visits/{actionId}/schedule
POST /api/research-subjects/{id}/visits/{actionId}/respond   {participant, response}
POST /api/research-subjects/{id}/visits/{actionId}/perform
POST /api/research-subjects/{id}/visits/{actionId}/tasks/{taskId}/complete
```

Schedule-state derivation: `load_subject_context` additionally searches tagged
`ServiceRequest`s, `Appointment`s, and `Task`s. Completion semantics are unchanged
(Encounter `completed`); "visited" becomes "any chain resource exists for the action".
The schedule response gains a per-action `phase`
(`proposed | planned | ordered | scheduled | booked | performing | completed`), the
Appointment participant statuses while scheduling, and, for the current visit, its
Task list with statuses.

Engine core (`graph.py` traversal, `conditions.py`, `engine.py`) is untouched apart
from the extension-URL configurability.

## Section 4 — Frontend

- `SubjectDashboard` visit cards: a phase stepper (chips for
  proposed → planned → ordered → scheduled → booked → performing → completed) plus
  **one** gate button whose label follows the phase — `Accept proposal` → `Authorize` →
  `Schedule` → `Perform` → `Complete visit`.
- While `scheduled`, the card shows the two participants with their response status and
  the simulated-engagement buttons (`Patient accepts`, `Site confirms`); `Perform`
  enables once booked.
- While `performing`, the current visit expands to a Task checklist: each Task tickable
  individually, `Complete visit` always enabled and sweeping the remainder.
- Ambiguous-transition choice UI unchanged (applies at proposal-materialization time).
- `types.ts` gains the phase/participant/task types; `client.ts` gains the promotion,
  schedule/respond, and task-completion calls.

## Section 5 — Error handling & testing

- Promotion guards in `activity_flow.py` (including perform-requires-booked);
  optimistic locking via `If-Match` as today.
- Unit tests (respx): proposal materialization (visit + activities), each promotion,
  cascade behaviour, wrong-phase guard, appointment booking on full acceptance,
  declined-response handling, individual task completion, completion sweep,
  withdrawal revocation/cancellation, schedule-state derivation from mixed chains.
- Golden-path integration test extends to: enroll → proposal exists → plan → order →
  schedule → both responses → booked → perform (Encounter + Tasks) → tick one Task →
  complete (sweep writes remaining Procedures) → next proposal materialized.
- Playwright E2E updated to click through the gates, responses, and one Task tick on
  the dashboard.

## Out of scope

- CPG profile conformance / R4 compatibility.
- `RequestOrchestration` grouping (`ServiceRequest.requisition` + the visit request anchor the group).
- Two-step prepare/initiate promotion endpoints.
- Activity-level individual gates in the UI (Tasks are tickable, but request promotion
  stays at visit level).
- `Observation` generation from ObservationDefinitions (stretch, later).
- Suspend/resume (`on-hold`) transitions.
- `Schedule`/`Slot` resources (Appointment participants are fixed fixtures; no slot
  discovery).
- `Communication`/`CommunicationRequest` reminders to participants (stretch, later).
- Appointment rebooking/renegotiation after a declined response.
- Recurring or multi-encounter Appointments.
