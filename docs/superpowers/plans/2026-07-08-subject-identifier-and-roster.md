# Subject Identifier + Study Roster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Required, manually-assigned subject identifiers at enrollment (with collision rules), surfaced on the dashboard title and a new enrolled-subjects roster on the study-details card, per `docs/superpowers/specs/2026-07-08-subject-identifier-and-roster-design.md`.

**Architecture:** `ResearchSubject.identifier` gains a `urn:vulcan-soa:subject-id` entry. `enroll()` gains a required parameter with four collision rules and a new `EnrollmentConflict` → 409. A roster route maps `ResearchSubject?study=` to summaries. Frontend: required input on Enroll, identifier in the dashboard title, roster section in `ResearchStudyDetails`.

**Tech Stack:** FastAPI + httpx/respx/pytest (backend), React 18 + TS + vitest (frontend), Playwright (one fill step).

## Global Constraints

- Identifier system EXACTLY `urn:vulcan-soa:subject-id`; collision search uses token form `urn:vulcan-soa:subject-id|<value>`.
- Collision rules (spec §Backend): (1) identifier used by different patient in study → `EnrollmentConflict`; (2) same patient + same identifier → idempotent success; (3) same patient + different identifier → `EnrollmentConflict`; (4) existing subject with no identifier → add via `If-Match` update.
- `EnrollRequest.subjectIdentifier: str` with `min_length=1`; enroll route maps `EnrollmentConflict` → HTTP 409 with the exception message as detail.
- Frontend label EXACTLY `Subject identifier`; Enroll button disabled until BOTH patient and non-blank identifier; on a 409 the server's detail message is shown in the existing `role="alert"` paragraph.
- Dashboard title: `Subject {subjectIdentifier}` when present (FHIR id in the existing `.meta` span), unchanged fallback otherwise. Only `GET /schedule` carries `subjectIdentifier` — gate responses don't; the dashboard must not lose it when gate responses replace the schedule state.
- Roster rows: identifier (fallback: first 8 chars of `researchSubjectId`), patient id as `.meta`, `Withdrawn` badge when `status === "retired"`, link to `/subjects/{researchSubjectId}`; empty state copy EXACTLY `No subjects enrolled yet.`
- Existing CSS classes only; no new dependencies.
- e2e golden path and both live integration tests updated for the new required argument (deliberate spec-sanctioned change); everything else passes unmodified.

## File Structure

```
backend/src/vulcan_soa/enrollment.py            # SUBJECT_ID_SYSTEM, EnrollmentConflict, subject_identifier_of, enroll(+param)
backend/src/vulcan_soa/api/models.py            # EnrollRequest.subjectIdentifier
backend/src/vulcan_soa/api/research_studies.py  # 409 mapping; GET /{study_id}/subjects
backend/src/vulcan_soa/api/research_subjects.py # get_schedule adds subjectIdentifier
backend/tests/test_enrollment.py                # updated + collision-rule tests
backend/tests/api/test_research_studies.py      # 409/422 route tests + roster tests
backend/tests/api/test_research_subjects.py     # schedule payload test
backend/tests/test_golden_path_integration.py   # enroll call updated
backend/tests/test_cpg_flow_integration.py      # enroll call updated
frontend/src/api/types.ts                       # StudySubjectSummary; Schedule.subjectIdentifier
frontend/src/api/client.ts                      # enrollPatient(+arg), listStudySubjects, 409 detail surfacing
frontend/src/views/Enroll/Enroll.tsx            # required identifier input; 409 copy
frontend/src/views/Enroll/Enroll.test.tsx       # gating + body tests
frontend/src/views/Enroll/ResearchStudyDetails.tsx       # roster section
frontend/src/views/Enroll/ResearchStudyDetails.test.tsx  # roster tests (create if absent)
frontend/src/views/SubjectDashboard/SubjectDashboard.tsx # title uses identifier
frontend/src/views/SubjectDashboard/SubjectDashboard.test.tsx # title test (additive)
frontend/e2e/golden-path.spec.ts                # one fill step
```

---

## Task 1: Backend — identifier at enroll, collision rules, 409 route

**Files:**
- Modify: `backend/src/vulcan_soa/enrollment.py`
- Modify: `backend/src/vulcan_soa/api/models.py`
- Modify: `backend/src/vulcan_soa/api/research_studies.py:34-38` (enroll route only)
- Test: `backend/tests/test_enrollment.py`, `backend/tests/api/test_research_studies.py`

**Interfaces:**
- Consumes: `if_match_header` from `vulcan_soa.activity_flow` (line 55); existing `conditional_create`.
- Produces: `SUBJECT_ID_SYSTEM = "urn:vulcan-soa:subject-id"`, `class EnrollmentConflict(Exception)`, `subject_identifier_of(subject: dict) -> str | None`, `enroll(client, study_id, patient_id, subject_identifier: str) -> dict` — all in `vulcan_soa.enrollment`. Tasks 2 and 4 import `subject_identifier_of`/`EnrollmentConflict`.

- [ ] **Step 1: Update the two existing enrollment tests and add collision tests**

In `backend/tests/test_enrollment.py`: both existing tests call `enroll(client, "uc1-demo-research-study", "patient-1")` — add the argument `"SUBJ-001"`. The existing bare `respx.get("http://aidbox.test/fhir/ResearchSubject")` mock now serves BOTH the collision search and conditional-create search (respx matches ignoring params by default), so the existing tests keep working with one mock. Extend the first test with an identifier assertion, and append the new tests:

```python
def _mock_protocol():
    respx.get("http://aidbox.test/fhir/ResearchStudy/uc1-demo-research-study").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )


def _subject_bundle(*resources):
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}
```

In `test_enroll_creates_subject_and_materializes_root_visit`, after the existing `proposal_payload` asserts, add:
```python
    subject_payload = json.loads(create_subject_route.calls.last.request.content)
    assert subject_payload["identifier"] == [
        {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}
    ]
```

Refactor the two existing tests to use `_mock_protocol()` in place of their duplicated study/plan mocks (behavior unchanged), then append:

```python
@respx.mock
async def test_enroll_conflicts_when_identifier_taken_by_another_patient():
    _mock_protocol()
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json=_subject_bundle(
                {
                    "resourceType": "ResearchSubject",
                    "id": "subj-other",
                    "subject": {"reference": "Patient/someone-else"},
                    "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
                }
            ),
        )
    )
    create_route = respx.post("http://aidbox.test/fhir/ResearchSubject")

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(EnrollmentConflict):
        await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()
    assert not create_route.called


@respx.mock
async def test_reenroll_same_patient_same_identifier_is_idempotent():
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-existing",
        "subject": {"reference": "Patient/patient-1"},
        "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/ResearchSubject/subj-existing")

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()

    assert result["researchSubjectId"] == "subj-existing"
    assert not update_route.called


@respx.mock
async def test_reenroll_same_patient_different_identifier_conflicts():
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-existing",
        "subject": {"reference": "Patient/patient-1"},
        "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(EnrollmentConflict):
        await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-002")
    await client.close()


@respx.mock
async def test_legacy_subject_without_identifier_gains_one_via_update():
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-legacy",
        "meta": {"versionId": "3"},
        "subject": {"reference": "Patient/patient-1"},
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )
    update_route = respx.put("http://aidbox.test/fhir/ResearchSubject/subj-legacy").mock(
        return_value=httpx.Response(
            200,
            json={**existing, "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-009"}]},
        )
    )
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-009")
    await client.close()

    assert result["researchSubjectId"] == "subj-legacy"
    assert update_route.called
    update_payload = json.loads(update_route.calls.last.request.content)
    assert update_payload["identifier"] == [
        {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-009"}
    ]
    assert update_route.calls.last.request.headers["If-Match"] == 'W/"3"'
```

Add the imports the new tests need: `import pytest` and `from vulcan_soa.enrollment import EnrollmentConflict, enroll`.

NOTE on the collision-search vs conditional-create interplay: with one shared GET mock, a bundle containing a subject for a DIFFERENT patient exercises rule 1 (conflict, because the identifier search "finds" it), while a bundle for the SAME patient flows through to conditional-create's search, which returns the same subject (rules 2-4). One subtlety: in rule-1's test the same bundle would also be returned to conditional-create, but `enroll` raises before reaching it — asserted via `create_route` not called.

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && source .venv/bin/activate && pytest tests/test_enrollment.py -v`
Expected: FAIL — `ImportError: cannot import name 'EnrollmentConflict'` (and TypeErrors on the extra argument once imports are fixed piecemeal).

- [ ] **Step 3: Implement in `enrollment.py`**

Add after the existing `RESEARCH_SUBJECT_STATE_SYSTEM` constant, and extend `enroll`:

```python
SUBJECT_ID_SYSTEM = "urn:vulcan-soa:subject-id"


class EnrollmentConflict(Exception):
    """The requested subject identifier cannot be assigned."""


def subject_identifier_of(subject: dict) -> str | None:
    for entry in subject.get("identifier", []):
        if entry.get("system") == SUBJECT_ID_SYSTEM:
            return entry.get("value")
    return None
```

Add `from vulcan_soa.activity_flow import if_match_header, materialize_proposal` (replacing the existing `materialize_proposal` import line). Then change `enroll`:

```python
async def enroll(
    client: FhirClient, study_id: str, patient_id: str, subject_identifier: str
) -> dict:
    graph, plan_definition_id = await load_protocol_graph(client, study_id)

    taken = await client.search(
        "ResearchSubject",
        {
            "identifier": f"{SUBJECT_ID_SYSTEM}|{subject_identifier}",
            "study": f"ResearchStudy/{study_id}",
        },
    )
    for match in taken:
        if match.get("subject", {}).get("reference") != f"Patient/{patient_id}":
            raise EnrollmentConflict(
                f"subject identifier '{subject_identifier}' is already in use in this study"
            )
```

In the `subject_resource` dict, add after `"status": "active",`:
```python
        "identifier": [{"system": SUBJECT_ID_SYSTEM, "value": subject_identifier}],
```

After the `created = await client.conditional_create(...)` call, add:
```python
    existing_value = subject_identifier_of(created)
    if existing_value != subject_identifier:
        if existing_value is not None:
            raise EnrollmentConflict(
                f"this patient is already enrolled as '{existing_value}'"
            )
        created.setdefault("identifier", []).append(
            {"system": SUBJECT_ID_SYSTEM, "value": subject_identifier}
        )
        created = await client.update(
            "ResearchSubject", created["id"], created, if_match=if_match_header(created)
        )
```
(When conditional-create actually created the resource, it echoes our identifier back, so `existing_value == subject_identifier` and this block is a no-op — no created-vs-found flag needed.)

- [ ] **Step 4: Enrollment tests pass**

Run: `cd backend && pytest tests/test_enrollment.py -v`
Expected: `6 passed` (2 updated + 4 new).

- [ ] **Step 5: Model + route (tests first)**

In `backend/tests/api/test_research_studies.py`, read the existing enroll-route test (`test_enroll_patient_calls_enrollment_and_returns_schedule`, ~line 49) first; update its posted JSON to include `"subjectIdentifier": "SUBJ-001"` and its fake-enroll signature to accept the new argument. Then append (mirroring the file's app/client helpers):

```python
def test_enroll_route_maps_conflict_to_409(monkeypatch):
    async def raise_conflict(client, study_id, patient_id, subject_identifier):
        raise EnrollmentConflict("subject identifier 'SUBJ-001' is already in use in this study")

    monkeypatch.setattr("vulcan_soa.api.research_studies.enroll", raise_conflict)
    test_client = _app_client()  # use the file's actual helper name
    response = test_client.post(
        "/api/research-studies/study-1/enroll",
        json={"patientId": "patient-1", "subjectIdentifier": "SUBJ-001"},
    )
    assert response.status_code == 409
    assert "already in use" in response.json()["detail"]


def test_enroll_route_rejects_missing_subject_identifier():
    test_client = _app_client()
    response = test_client.post(
        "/api/research-studies/study-1/enroll", json={"patientId": "patient-1"}
    )
    assert response.status_code == 422
```
(Import `EnrollmentConflict` from `vulcan_soa.enrollment` in the test file; use the file's real helper for building the test client — if it's named differently than `_app_client`, use that name in both tests.)

Run to verify failures, then implement:

`backend/src/vulcan_soa/api/models.py`:
```python
from pydantic import BaseModel, Field


class EnrollRequest(BaseModel):
    patientId: str
    subjectIdentifier: str = Field(min_length=1)
```

`backend/src/vulcan_soa/api/research_studies.py` — imports gain `HTTPException` (fastapi) and `EnrollmentConflict` (vulcan_soa.enrollment); the enroll route becomes:
```python
@router.post("/{study_id}/enroll")
async def enroll_patient(
    study_id: str, body: EnrollRequest, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    try:
        return await enroll(client, study_id, body.patientId, body.subjectIdentifier)
    except EnrollmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

- [ ] **Step 6: Full backend suite EXCEPT integration files**

Run: `cd backend && pytest`
Expected: the two integration files are skip-gated so the suite runs; everything passes EXCEPT nothing — unit suite green (the integration files' `enroll` calls are updated in Task 4; they are not collected without `RUN_INTEGRATION_TESTS=1`, but their import-time code must still parse — they only call `enroll` inside test bodies, so no collection error).

- [ ] **Step 7: Commit**

```bash
git add backend/src/vulcan_soa/enrollment.py backend/src/vulcan_soa/api/models.py backend/src/vulcan_soa/api/research_studies.py backend/tests/test_enrollment.py backend/tests/api/test_research_studies.py
git commit -m "Require a subject identifier at enrollment with collision rules"
```

---

## Task 2: Backend — roster route + schedule payload field

**Files:**
- Modify: `backend/src/vulcan_soa/api/research_studies.py` (new GET route after `get_research_study`)
- Modify: `backend/src/vulcan_soa/api/research_subjects.py:36-43` (`get_schedule`)
- Test: `backend/tests/api/test_research_studies.py`, `backend/tests/api/test_research_subjects.py`

**Interfaces:**
- Consumes: `subject_identifier_of` from `vulcan_soa.enrollment` (Task 1).
- Produces: `GET /api/research-studies/{study_id}/subjects` → `list[{"researchSubjectId", "subjectIdentifier", "patientId", "status"}]`; `GET /api/research-subjects/{subject_id}/schedule` payload gains `"subjectIdentifier": str | None`. Task 3 consumes both shapes.

- [ ] **Step 1: Write the failing route tests**

Append to `backend/tests/api/test_research_studies.py` (again using the file's real test-client helper; the fake client pattern for search follows the file's existing list/get tests — read them first):

```python
def test_list_study_subjects_maps_summaries(monkeypatch_or_fake_client_pattern):
    # Follow the file's existing pattern for stubbing FhirClient.search.
    # The stub returns:
    subjects = [
        {
            "resourceType": "ResearchSubject",
            "id": "subj-1",
            "status": "active",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
        },
        {
            "resourceType": "ResearchSubject",
            "id": "subj-2",
            "status": "retired",
            "subject": {"reference": "Patient/patient-2"},
        },
    ]
    # ... stub search("ResearchSubject", {"study": "ResearchStudy/study-1"}) -> subjects
    response = test_client.get("/api/research-studies/study-1/subjects")
    assert response.status_code == 200
    assert response.json() == [
        {
            "researchSubjectId": "subj-1",
            "subjectIdentifier": "SUBJ-001",
            "patientId": "patient-1",
            "status": "active",
        },
        {
            "researchSubjectId": "subj-2",
            "subjectIdentifier": None,
            "patientId": "patient-2",
            "status": "retired",
        },
    ]
```
The commented lines are where the file's existing stubbing idiom goes — the assertion block is the requirement and must appear verbatim. Also add an empty-list case (search returns `[]` → response `[]`).

In `backend/tests/api/test_research_subjects.py`, extend the existing `get_schedule` test (find it near the top; it stubs the reads/searches) to assert the response JSON includes `"subjectIdentifier"` — with the stubbed subject given an identifier entry `{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}`, assert `response.json()["subjectIdentifier"] == "SUBJ-001"`.

- [ ] **Step 2: Run to verify failures**

Run: `cd backend && pytest tests/api/test_research_studies.py tests/api/test_research_subjects.py -v`
Expected: new tests FAIL (404 route / missing key).

- [ ] **Step 3: Implement**

`backend/src/vulcan_soa/api/research_studies.py` — add import `from vulcan_soa.enrollment import EnrollmentConflict, enroll, subject_identifier_of` (extending Task 1's import) and after `get_research_study`:

```python
@router.get("/{study_id}/subjects")
async def list_study_subjects(
    study_id: str, client: FhirClient = Depends(get_fhir_client)
) -> list[dict]:
    subjects = await client.search(
        "ResearchSubject", {"study": f"ResearchStudy/{study_id}"}
    )
    return [
        {
            "researchSubjectId": subject["id"],
            "subjectIdentifier": subject_identifier_of(subject),
            "patientId": subject.get("subject", {}).get("reference", "").split("/", 1)[-1],
            "status": subject.get("status"),
        }
        for subject in subjects
    ]
```

`backend/src/vulcan_soa/api/research_subjects.py` — add `from vulcan_soa.enrollment import subject_identifier_of` and change `get_schedule`'s return to:
```python
    payload = schedule_response(state, graph, visits=visit_details(chains))
    payload["subjectIdentifier"] = subject_identifier_of(subject)
    return payload
```

- [ ] **Step 4: Suite green**

Run: `cd backend && pytest`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/api/research_studies.py backend/src/vulcan_soa/api/research_subjects.py backend/tests/api/test_research_studies.py backend/tests/api/test_research_subjects.py
git commit -m "Add study roster route and subjectIdentifier in the schedule payload"
```

---

## Task 3: Frontend — enroll input, dashboard title, roster section

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Modify: `frontend/src/views/Enroll/Enroll.tsx`, `frontend/src/views/Enroll/Enroll.test.tsx`
- Modify: `frontend/src/views/Enroll/ResearchStudyDetails.tsx`; Test: `frontend/src/views/Enroll/ResearchStudyDetails.test.tsx` (create if it does not exist; if it exists, append)
- Modify: `frontend/src/views/SubjectDashboard/SubjectDashboard.tsx`, `SubjectDashboard.test.tsx` (additive test)

**Interfaces:**
- Consumes: Task 1/2 API shapes.
- Produces (types.ts):
  ```ts
  export interface StudySubjectSummary {
    researchSubjectId: string;
    subjectIdentifier: string | null;
    patientId: string;
    status: string | null;
  }
  ```
  `Schedule` gains `subjectIdentifier?: string | null;`. client.ts: `enrollPatient(studyId: string, patientId: string, subjectIdentifier: string): Promise<EnrollResult>`; `listStudySubjects(studyId: string): Promise<StudySubjectSummary[]>`.

- [ ] **Step 1: Failing tests**

Read `frontend/src/views/Enroll/Enroll.test.tsx` first (it was reworked by the user; mirror its mock style). Update every existing `enrollPatient` expectation to the 3-arg form and add/extend so these behaviors are covered (write them in the file's idiom):
1. Enroll button disabled when the identifier input is blank even with a patient selected; enabled once `Subject identifier` is typed into.
2. Clicking Enroll posts `enrollPatient(studyId, patientId, "SUBJ-001")`.
3. A rejected `enrollPatient` whose error carries a 409 detail message shows that message in the `role="alert"` paragraph (see client.ts step for the error shape).

`ResearchStudyDetails.test.tsx` (create/extend, mocking `getResearchStudy` + new `listStudySubjects`):
1. Renders a row per subject: identifier text (`SUBJ-001`) with `href="/subjects/subj-1"`; fallback shows first 8 chars of the id when identifier is null.
2. `Withdrawn` badge rendered exactly for `status === "retired"` rows.
3. Empty roster shows `No subjects enrolled yet.`

`SubjectDashboard.test.tsx` (additive only): a schedule mock with `subjectIdentifier: "SUBJ-001"` renders heading text containing `SUBJ-001`; existing three tests (mocks without the field) stay untouched and must keep passing (fallback to the route id).

Run: `cd frontend && npm test` — new/updated assertions fail.

- [ ] **Step 2: Implement**

`types.ts`: add `StudySubjectSummary` (exact shape above) and `subjectIdentifier?: string | null;` on `Schedule`.

`client.ts`: read the existing `postJson`/error idiom first. `enrollPatient` gains the third argument and posts `{ patientId, subjectIdentifier }`. Add `listStudySubjects` GET mirroring `getResearchStudy`'s style. If the shared request helper currently throws a bare `Error`, extend it minimally so callers can read the server detail: throw an `Error` whose `message` is the response JSON's `detail` when present (status 4xx) — keep the change inside the shared helper, no new class unless the file already uses one.

`Enroll.tsx`: add state `const [subjectIdentifier, setSubjectIdentifier] = useState("");` a second labelled field after the patient select:
```tsx
        <label className="form-field">
          Subject identifier
          <input
            value={subjectIdentifier}
            onChange={(event) => setSubjectIdentifier(event.target.value)}
            placeholder="e.g. LZZT-0001"
          />
        </label>
```
Button condition becomes `disabled={status === "enrolling" || !patientId || !subjectIdentifier.trim()}`; `handleEnroll` guards on both and calls `enrollPatient(studyId, patientId, subjectIdentifier.trim())`; the catch shows `error.message` when non-empty, else the existing generic copy.

`SubjectDashboard.tsx`: keep the identifier from the initial load only:
```tsx
  const [subjectLabel, setSubjectLabel] = useState<string | null>(null);
```
In `refresh()`'s `.then`, after `setSchedule(result)`: `setSubjectLabel(result.subjectIdentifier ?? null);` (gate responses never carry the field and never touch `subjectLabel`). Title becomes:
```tsx
      <h2 className="page-title">
        Subject {subjectLabel ?? subjectId} <span className="meta">{subjectLabel ? subjectId : ""}</span>
      </h2>
```

`ResearchStudyDetails.tsx`: fetch the roster alongside the study (extend the existing effect with `listStudySubjects(studyId)` — keep the `active` guard pattern), store `const [subjects, setSubjects] = useState<StudySubjectSummary[]>([]);`, and render after the protocol chips:
```tsx
      <p className="section-title">Enrolled subjects</p>
      {subjects.length === 0 ? (
        <p className="meta">No subjects enrolled yet.</p>
      ) : (
        <ul className="study-list" aria-label="Enrolled subjects">
          {subjects.map((subject) => (
            <li key={subject.researchSubjectId} className="study-card">
              <Link to={`/subjects/${subject.researchSubjectId}`}>
                {subject.subjectIdentifier ?? subject.researchSubjectId.substring(0, 8)}
                <span className="meta"> {subject.patientId}</span>
                {subject.status === "retired" && <span className="badge"> Withdrawn</span>}
              </Link>
            </li>
          ))}
        </ul>
      )}
```
(Requires `import { Link } from "react-router-dom";` and the new client/type imports. A roster fetch failure leaves the empty state — do not add new error copy.)

- [ ] **Step 3: Suite + build green**

Run: `cd frontend && npm test && npm run build`
Expected: all tests pass (existing + new), build clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/views/Enroll/Enroll.tsx frontend/src/views/Enroll/Enroll.test.tsx frontend/src/views/Enroll/ResearchStudyDetails.tsx frontend/src/views/Enroll/ResearchStudyDetails.test.tsx frontend/src/views/SubjectDashboard/SubjectDashboard.tsx frontend/src/views/SubjectDashboard/SubjectDashboard.test.tsx
git commit -m "Collect subject identifiers at enrollment and show the study roster"
```

---

## Task 4: Integration/e2e updates + live verification

**Files:**
- Modify: `backend/tests/test_golden_path_integration.py`, `backend/tests/test_cpg_flow_integration.py` (each `enroll(...)` call gains an identifier argument — grep `enroll(` in both, use `"INT-GP-001"` / `"INT-CPG-001"`)
- Modify: `frontend/e2e/golden-path.spec.ts` (after the patient `selectOption` line: `await page.getByLabel("Subject identifier").fill("E2E-001");`)

- [ ] **Step 1: Update the three files as above**

- [ ] **Step 2: Suites + integration against live Aidbox**

Run: `cd backend && pytest -q` (unit), then with local Aidbox up: `ENV_FILE=.env.local RUN_INTEGRATION_TESTS=1 pytest tests/test_golden_path_integration.py tests/test_cpg_flow_integration.py -v`
Expected: unit suite green; both integration tests pass. NOTE: re-running integration tests against a long-lived Aidbox reuses existing subjects — the legacy-update rule (collision rule 4) makes the first re-run attach the identifier; a subsequent run with the SAME identifier is idempotent. If a previous session's subject already carries a DIFFERENT vulcan-soa subject identifier, the test will 409 — delete that `ResearchSubject` (and its Encounters) or use a fresh identifier value, and note what happened in the task report.

- [ ] **Step 3: Live roster check**

```bash
cd backend && source .venv/bin/activate
ENV_FILE=.env.local python -c "
import asyncio, json
from vulcan_soa.config import Settings
from vulcan_soa.fhir_client import FhirClient

async def main():
    s = Settings()
    c = FhirClient(base_url=s.fhir_base_url, basic_auth=(s.smart_client_id, s.smart_client_secret))
    try:
        subjects = await c.search('ResearchSubject', {'study': 'ResearchStudy/uc1-demo-research-study'})
        for subj in subjects:
            ids = [i['value'] for i in subj.get('identifier', []) if i.get('system') == 'urn:vulcan-soa:subject-id']
            print(subj['id'], subj.get('status'), ids)
    finally:
        await c.close()

asyncio.run(main())
"
```
Expected: at least the integration-test subject prints with its assigned identifier.

- [ ] **Step 4: Playwright compile check + commit**

Run: `cd frontend && npx playwright test --list` (both specs compile).

```bash
git add backend/tests/test_golden_path_integration.py backend/tests/test_cpg_flow_integration.py frontend/e2e/golden-path.spec.ts
git commit -m "Thread subject identifiers through integration and e2e flows"
```
