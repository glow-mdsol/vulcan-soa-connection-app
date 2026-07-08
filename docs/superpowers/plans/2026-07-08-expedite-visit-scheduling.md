# Expedite Visit Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One batched action that walks a visit from its current early phase (`proposed`/`planned`/`ordered`) to `scheduled`, alongside — not replacing — the existing single-step gate buttons, per `docs/superpowers/specs/2026-07-08-expedite-visit-scheduling-design.md`.

**Architecture:** `expedite()` in `activity_flow.py` composes the existing `promote`/`schedule_visit` functions (each step stays its own atomic unit; every intermediate `ServiceRequest` still lands, preserving the CPG chain). A mirrored `/expedite` route, an `expediteVisit` client function, and a secondary "Schedule now" button on `proposed`/`planned` visit cards.

**Tech Stack:** FastAPI + httpx (backend, pytest/respx/monkeypatch), React 18 + TS (frontend, vitest/@testing-library).

## Global Constraints

- Batching is UX/API only: `expedite` MUST call the existing `promote`/`schedule_visit` — no reimplementation of their logic, no shared-workspace refactor.
- Phase dispatch is exactly: `proposed → ("plan", "order", "schedule")`, `planned → ("order", "schedule")`, `ordered → ("schedule",)`; any other phase raises `PhaseError`; unmaterialized action id raises `ValueError` (the `_guarded` route wrapper maps these to 409/404).
- Frontend: "Schedule now" (`btn-secondary`, disabled while `busy`) appears ONLY in `proposed` and `planned` phases, next to the existing primary button in a `.btn-row`; `ordered` and later phases are unchanged. Existing accessible names/roles untouched; existing tests pass with only the additive `onExpedite` noop in the shared `noopHandlers()` helper.
- Dashboard failure copy: `Could not fast-forward this visit.`
- No new dependencies; only existing CSS classes.

---

## Task 1: Backend — `expedite()` + route

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py` (add after `schedule_visit`, ~line 340)
- Modify: `backend/src/vulcan_soa/api/research_subjects.py` (import + route after `schedule_route`)
- Create: `backend/tests/test_activity_flow_expedite.py`
- Modify: `backend/tests/api/test_research_subjects.py` (two route tests, appended)

**Interfaces:**
- Consumes: `promote(client, subject_id, action_id, to_intent) -> dict`, `schedule_visit(client, subject_id, action_id) -> dict`, `_load_workspace(client, subject_id) -> _SubjectWorkspace`, `PhaseError`, `_guarded` — all existing.
- Produces: `expedite(client: FhirClient, subject_id: str, action_id: str) -> dict` (returns the last gate's schedule payload) and `POST /api/research-subjects/{subject_id}/visits/{action_id}/expedite`. Task 2's `expediteVisit` posts to this route.

- [x] **Step 1: Write the failing unit tests**

`backend/tests/test_activity_flow_expedite.py`:
```python
from types import SimpleNamespace

import pytest

from vulcan_soa import activity_flow
from vulcan_soa.activity_flow import PhaseError, expedite


def fake_workspace(phase: str | None):
    chains = {} if phase is None else {"E1": SimpleNamespace(phase=phase)}
    return SimpleNamespace(chains=chains)


def install_fakes(monkeypatch, phase: str | None):
    calls: list[tuple] = []

    async def fake_load_workspace(client, subject_id):
        return fake_workspace(phase)

    async def fake_promote(client, subject_id, action_id, to_intent):
        calls.append(("promote", to_intent))
        return {"payload": f"after-{to_intent}"}

    async def fake_schedule_visit(client, subject_id, action_id):
        calls.append(("schedule",))
        return {"payload": "after-schedule"}

    monkeypatch.setattr(activity_flow, "_load_workspace", fake_load_workspace)
    monkeypatch.setattr(activity_flow, "promote", fake_promote)
    monkeypatch.setattr(activity_flow, "schedule_visit", fake_schedule_visit)
    return calls


async def test_expedite_from_proposed_runs_all_three_gates_in_order(monkeypatch):
    calls = install_fakes(monkeypatch, "proposed")
    result = await expedite(None, "subj-1", "E1")
    assert calls == [("promote", "plan"), ("promote", "order"), ("schedule",)]
    assert result == {"payload": "after-schedule"}


async def test_expedite_from_planned_skips_plan(monkeypatch):
    calls = install_fakes(monkeypatch, "planned")
    await expedite(None, "subj-1", "E1")
    assert calls == [("promote", "order"), ("schedule",)]


async def test_expedite_from_ordered_only_schedules(monkeypatch):
    calls = install_fakes(monkeypatch, "ordered")
    result = await expedite(None, "subj-1", "E1")
    assert calls == [("schedule",)]
    assert result == {"payload": "after-schedule"}


async def test_expedite_from_scheduled_raises_phase_error(monkeypatch):
    calls = install_fakes(monkeypatch, "scheduled")
    with pytest.raises(PhaseError):
        await expedite(None, "subj-1", "E1")
    assert calls == []


async def test_expedite_unmaterialized_action_raises_value_error(monkeypatch):
    install_fakes(monkeypatch, None)
    with pytest.raises(ValueError):
        await expedite(None, "subj-1", "E1")
```

- [x] **Step 2: Run to verify failure**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_activity_flow_expedite.py -v`
Expected: FAIL — `ImportError: cannot import name 'expedite'`.

- [x] **Step 3: Implement `expedite`**

In `backend/src/vulcan_soa/activity_flow.py`, directly after `schedule_visit`:
```python
_EXPEDITE_STEPS = {
    "proposed": ("plan", "order", "schedule"),
    "planned": ("order", "schedule"),
    "ordered": ("schedule",),
}


async def expedite(client: FhirClient, subject_id: str, action_id: str) -> dict:
    """Walk a visit through its remaining gates to `scheduled` in one call.

    Composes the single-step gates, so every intermediate ServiceRequest is
    still created and completed; a mid-batch failure leaves the visit in a
    valid intermediate phase recoverable via the individual gate buttons.
    """
    workspace = await _load_workspace(client, subject_id)
    chain = workspace.chains.get(action_id)
    if chain is None:
        raise ValueError(f"No materialized visit found for action {action_id}")
    steps = _EXPEDITE_STEPS.get(chain.phase)
    if steps is None:
        raise PhaseError(
            f"visit {action_id} is in phase '{chain.phase}', "
            f"expected one of {sorted(_EXPEDITE_STEPS)}"
        )

    payload: dict = {}
    for step in steps:
        if step == "schedule":
            payload = await schedule_visit(client, subject_id, action_id)
        else:
            payload = await promote(client, subject_id, action_id, step)
    return payload
```

Note: `promote`/`schedule_visit` are looked up as module attributes at call time inside `expedite` — the tests' `monkeypatch.setattr(activity_flow, ...)` relies on this; do not import them into local names.

- [x] **Step 4: Unit tests pass**

Run: `cd backend && pytest tests/test_activity_flow_expedite.py -v`
Expected: `5 passed`

- [x] **Step 5: Add the route + route tests (failing first)**

Append to `backend/tests/api/test_research_subjects.py` (mirror the file's existing `_EMPTY_SCHEDULE`/`_app_client_with_dummy_fhir_client` helpers — read the file's existing `test_schedule_route_happy_path` first and copy its structure):
```python
def test_expedite_route_happy_path(monkeypatch):
    captured = {}

    async def fake_expedite(client, subject_id, action_id):
        captured["args"] = (subject_id, action_id)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.expedite", fake_expedite)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/expedite")

    assert response.status_code == 200
    assert response.json() == _EMPTY_SCHEDULE
    assert captured["args"] == ("subj-1", "E1")


def test_expedite_route_returns_conflict_on_phase_error(monkeypatch):
    async def raise_phase_error(client, subject_id, action_id):
        raise PhaseError("wrong phase")

    monkeypatch.setattr("vulcan_soa.api.research_subjects.expedite", raise_phase_error)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/expedite")

    assert response.status_code == 409
```
(`PhaseError` is already imported in that test file if the existing 409 test uses it; otherwise import it from `vulcan_soa.activity_flow`.)

Run to verify both fail (404 route missing / import error), then add to `backend/src/vulcan_soa/api/research_subjects.py`: `expedite` in the existing `from vulcan_soa.activity_flow import (...)` list, and after `schedule_route`:
```python
@router.post("/{subject_id}/visits/{action_id}/expedite")
async def expedite_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(expedite(client, subject_id, action_id))
```

- [x] **Step 6: Full backend suite**

Run: `cd backend && pytest`
Expected: all pass (baseline 139 passed, 2 skipped; +7 new).

- [x] **Step 7: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/src/vulcan_soa/api/research_subjects.py backend/tests/test_activity_flow_expedite.py backend/tests/api/test_research_subjects.py
git commit -m "Add expedite gate batching proposal->scheduled"
```

---

## Task 2: Frontend — client function, "Schedule now" button, dashboard wiring

**Files:**
- Modify: `frontend/src/api/client.ts` (one function after `scheduleVisit`)
- Modify: `frontend/src/views/SubjectDashboard/VisitCard.tsx`
- Modify: `frontend/src/views/SubjectDashboard/VisitCard.test.tsx` (noop handler + 3 new tests)
- Modify: `frontend/src/views/SubjectDashboard/SubjectDashboard.tsx` (one prop)

**Interfaces:**
- Consumes: Task 1's route; existing `Schedule` type; classes `.btn`, `.btn-secondary`, `.btn-row`.
- Produces: `expediteVisit(subjectId: string, actionId: string): Promise<Schedule>`; `VisitCardProps` gains required `onExpedite: () => void`.

- [x] **Step 1: Write the failing VisitCard tests**

In `VisitCard.test.tsx`: add `onExpedite: vi.fn(),` to `noopHandlers()`, then append:
```tsx
  it("shows Schedule now beside the primary gate while proposed and fires onExpedite", async () => {
    const handlers = noopHandlers();
    render(<VisitCard actionId="E1" detail={{ phase: "proposed" }} {...handlers} />);

    expect(screen.getByRole("button", { name: "Accept proposal" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Schedule now" }));
    expect(handlers.onExpedite).toHaveBeenCalled();
  });

  it("shows Schedule now while planned", () => {
    const handlers = noopHandlers();
    render(<VisitCard actionId="E1" detail={{ phase: "planned" }} {...handlers} />);

    expect(screen.getByRole("button", { name: "Authorize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Schedule now" })).toBeInTheDocument();
  });

  it("does not show Schedule now once ordered", () => {
    const handlers = noopHandlers();
    render(<VisitCard actionId="E1" detail={{ phase: "ordered" }} {...handlers} />);

    expect(screen.queryByRole("button", { name: "Schedule now" })).not.toBeInTheDocument();
  });
```

Run: `cd frontend && npx vitest run src/views/SubjectDashboard/VisitCard.test.tsx` — expect the first two to FAIL (no such button; TS error on unknown prop is also an acceptable red).

- [x] **Step 2: Implement**

`frontend/src/api/client.ts`, after `scheduleVisit` (mirror its exact fetch/post helper style — read it first):
```ts
export function expediteVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return post(`/api/research-subjects/${subjectId}/visits/${actionId}/expedite`);
}
```
(If the file uses a different internal helper than `post`, follow the file's own pattern for `scheduleVisit` exactly.)

`VisitCard.tsx`: add `onExpedite: () => void;` to `VisitCardProps` (after `onSchedule`), destructure it, and change the two early-phase branches to:
```tsx
      {phase === "proposed" && (
        <div className="btn-row">
          <button className="btn" onClick={onPlan} disabled={busy}>
            Accept proposal
          </button>
          <button className="btn-secondary" onClick={onExpedite} disabled={busy}>
            Schedule now
          </button>
        </div>
      )}
      {phase === "planned" && (
        <div className="btn-row">
          <button className="btn" onClick={onOrder} disabled={busy}>
            Authorize
          </button>
          <button className="btn-secondary" onClick={onExpedite} disabled={busy}>
            Schedule now
          </button>
        </div>
      )}
```
The `ordered` branch stays exactly as it is.

`SubjectDashboard.tsx`: import `expediteVisit` alongside the other client functions and add to the `VisitCard` call site (after `onSchedule`):
```tsx
                  onExpedite={() =>
                    runGate(() => expediteVisit(subjectId!, actionId), "Could not fast-forward this visit.")
                  }
```

- [x] **Step 3: Full frontend suite + build**

Run: `cd frontend && npm test && npm run build`
Expected: 38 passed (35 + 3), build clean.

- [x] **Step 4: Commit**

```bash
git add frontend/src/api/client.ts frontend/src/views/SubjectDashboard/VisitCard.tsx frontend/src/views/SubjectDashboard/VisitCard.test.tsx frontend/src/views/SubjectDashboard/SubjectDashboard.tsx
git commit -m "Add Schedule now fast-path to proposed and planned visit cards"
```

---

## Task 3: Live verification

**Files:** none (verification only; fix-forward smallest-change if something fails).

- [x] **Step 1: Both suites**

Run: `cd backend && source .venv/bin/activate && pytest -q && cd ../frontend && npm test`
Expected: backend 146 passed / 2 skipped; frontend 38 passed.

- [x] **Step 2: Live cascade check against local Aidbox**

With local Aidbox up and fixtures loaded, run from `backend/` (venv active, `ENV_FILE=.env.local`):
```bash
python - <<'EOF'
import asyncio
from vulcan_soa.activity_flow import expedite, load_chains
from vulcan_soa.config import Settings
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient


async def main():
    settings = Settings()
    client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    try:
        # Fresh patient so the golden-path demo data is untouched.
        patient = await client.create(
            "Patient", {"resourceType": "Patient", "name": [{"family": "Expedite", "given": ["Check"]}]}
        )
        result = await enroll(client, "uc1-demo-research-study", patient["id"])
        subject_id = result["researchSubjectId"]
        schedule = result["schedule"]
        action_id = schedule["current"][0]
        assert schedule["visits"][action_id]["phase"] == "proposed", schedule["visits"]

        payload = await expedite(client, subject_id, action_id)
        phase = payload["visits"][action_id]["phase"]
        print(f"expedite: {action_id} -> phase {phase}")
        assert phase == "scheduled", payload["visits"]
        print("LIVE EXPEDITE OK")
    finally:
        await client.close()


asyncio.run(main())
EOF
```
Expected output ends with `LIVE EXPEDITE OK`. (Check `enroll`'s actual signature/return keys in `backend/src/vulcan_soa/enrollment.py` before running; adjust the driver if they differ — the assertion targets, not the driver, are the requirement.)

- [x] **Step 3: No commit needed unless a fix was required**

```bash
git status --short   # expect clean
```
