# Expedite Visit Scheduling (proposal → scheduled in one action) — Design

**Problem:** Walking a visit from `proposed` to `scheduled` takes three separate
UI round-trips (Accept proposal → Authorize → Schedule), each a single CPG
intent transition. For routine planned encounters this is friction — especially
mid-demo. The user wants the intermediary state changes batched into one action.

**Decision:** A batched **fast-path** that sits *alongside* the individual gate
buttons (chosen over replacing them — the step-by-step buttons remain for
narrating the CPG lifecycle at the connectathon booth). Batching is a UX/API
convenience only: every intermediate `ServiceRequest` is still created and its
predecessor completed in order, so the CPG `basedOn`/`requisition` chain the
demo exists to prove is byte-identical to the manual path.

## Backend

- New `expedite(client: FhirClient, subject_id: str, action_id: str) -> dict`
  in `backend/src/vulcan_soa/activity_flow.py`. It reads the visit's current
  phase (via the loaded chains) and sequentially awaits the EXISTING functions
  for the remaining gates:
  - `proposed` → `promote(..., "plan")`, `promote(..., "order")`, `schedule_visit(...)`
  - `planned` → `promote(..., "order")`, `schedule_visit(...)`
  - `ordered` → `schedule_visit(...)`
  - any other phase (or unmaterialized action id) → the same `PhaseError` /
    `ValueError` the individual gates raise.
  It returns the LAST step's schedule payload. Each step remains the same
  atomic unit as today: a mid-batch failure leaves the visit in a valid
  intermediate phase, recoverable through the normal single-step buttons. No
  data-model changes.
- Rejected alternative: refactoring `promote`/`schedule_visit` to share one
  `_SubjectWorkspace` load (saves ~6 reads per batch). Not worth opening up
  well-tested internals at demo scale.
- New route `POST /api/research-subjects/{subject_id}/visits/{action_id}/expedite`
  in `backend/src/vulcan_soa/api/research_subjects.py`, using the existing
  `_guarded` wrapper (PhaseError→409, ValueError→404) and returning the
  schedule payload like every other gate route.

## Frontend

- `frontend/src/api/client.ts`: `expediteVisit(subjectId, actionId): Promise<Schedule>`
  posting to the new route (same shape as `scheduleVisit`).
- `VisitCard` gains `onExpedite: () => void`. In phases `proposed` and
  `planned` it renders the existing primary gate button PLUS a secondary
  button labelled **`Schedule now`** (`btn-secondary`, disabled while `busy`,
  inside a `.btn-row` with the primary). `ordered` keeps only its existing
  `Schedule` button (expedite would be identical). No other phases change.
- `SubjectDashboard` wires `onExpedite` through the existing `runGate` helper
  with failure copy `Could not fast-forward this visit.`

## Testing

- Backend: new `backend/tests/test_activity_flow_expedite.py` asserts
  expedite's own contract — phase dispatch and gate sequencing — with
  monkeypatched `promote`/`schedule_visit`/`_load_workspace` (from `proposed`:
  plan, order, schedule in order, last payload returned; from `planned`: two
  steps; from `ordered`: one; from `scheduled`/missing: PhaseError/ValueError).
  The resource cascade itself is already covered per-gate by
  `test_activity_flow_requests.py`/`test_activity_flow_appointments.py` —
  not duplicated. Route tests mirror the existing monkeypatch style in
  `backend/tests/api/test_research_subjects.py` (happy path + 409). A live
  expedite run against local Aidbox verifies the real cascade end-to-end.
- Frontend: `VisitCard` tests — `proposed` and `planned` phases render both
  buttons, clicking `Schedule now` fires `onExpedite`, `ordered` does NOT show
  it; existing tests pass unmodified apart from the required new `onExpedite`
  noop handler in the shared `noopHandlers()` helper.
- E2E golden path unchanged — it deliberately narrates the single-step
  lifecycle.

## Out of scope

- Batching past `scheduled` (participant accept → booked stays interactive).
- Calendar/slot integration (placeholder appointment window stays).
- Any change to the ambiguous-transition decision flow.
