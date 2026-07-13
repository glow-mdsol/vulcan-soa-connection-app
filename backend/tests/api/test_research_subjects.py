import json

import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.activity_flow import PhaseError
from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.research_subjects import router as research_subjects_router
from vulcan_soa.fhir_client import FhirClient

SUBJECT = {
    "resourceType": "ResearchSubject",
    "id": "subj-1",
    # R6: status (PublicationStatus) — "active" for an active subject
    "status": "active",
    "study": {"reference": "ResearchStudy/study-1"},
    "subject": {"reference": "Patient/patient-1"},
    "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
    "subjectState": [
        {
            "code": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/research-subject-state",
                        "code": "candidate",
                    }
                ]
            },
            "startDate": "2026-07-01",
        },
        {
            "code": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/research-subject-state",
                        "code": "eligible",
                    }
                ]
            },
            "startDate": "2026-07-02",
        },
    ],
    "subjectMilestone": [
        {
            "milestone": {
                "coding": [
                    {
                        "system": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl",
                        "code": "C16735",
                        "display": "Informed Consent",
                    }
                ]
            },
            "date": "2026-07-01",
        }
    ],
}
STUDY = {
    "resourceType": "ResearchStudy",
    "id": "study-1",
    "protocol": [{"reference": "PlanDefinition/plan-1"}],
}
PLAN_DEFINITION = {
    "resourceType": "PlanDefinition",
    "id": "plan-1",
    "action": [{"id": "screening-1", "title": "Screening"}],
}
VISIT_TAG = {"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}
VISIT_ORDER = {
    "resourceType": "ServiceRequest",
    "id": "sr-visit-order",
    "intent": "order",
    "status": "active",
    "subject": {"reference": "Patient/patient-1"},
    "identifier": [VISIT_TAG],
    "code": {"concept": {"text": "Screening"}},
}
BOOKED_APPOINTMENT = {
    "resourceType": "Appointment",
    "id": "appt-1",
    "status": "booked",
    "identifier": [VISIT_TAG],
    "participant": [
        {"actor": {"reference": "Patient/patient-1"}, "status": "accepted"},
        {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "accepted"},
    ],
}
IN_PROGRESS_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-1",
    "status": "in-progress",
    "meta": {"versionId": "2"},
    "subject": {"reference": "Patient/patient-1"},
    "identifier": [VISIT_TAG],
}


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(research_subjects_router)
    return app


@respx.mock
def test_get_schedule_returns_resolved_state():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    for resource_type in ("ServiceRequest", "Appointment", "Encounter", "Task"):
        respx.get(f"https://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json=_bundle())
        )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/schedule")

    assert response.status_code == 200
    body = response.json()
    assert body["nextSteps"] == [
        {"actionId": "screening-1", "title": "Screening", "transitionType": None}
    ]
    assert body["visits"] == {}
    assert body["subjectIdentifier"] == "SUBJ-001"
    assert body["subjectStatus"] == "active"
    assert body["subjectState"] == "eligible"
    assert body["milestones"] == [
        {"milestone": "C16735", "display": "Informed Consent", "date": "2026-07-01"}
    ]
    assert body["studyId"] == "study-1"
    assert body["planDefinitionId"] == "plan-1"


@respx.mock
def test_record_milestone_appends_to_subject_milestones():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=dict(SUBJECT, meta={"versionId": "3"}))
    )
    updated = dict(
        SUBJECT,
        subjectMilestone=SUBJECT["subjectMilestone"]
        + [
            {
                "milestone": {
                    "coding": [
                        {
                            "system": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl",
                            "code": "C114209",
                            "display": "Subject is Randomized",
                        }
                    ]
                },
                "date": "2026-07-08",
            }
        ],
    )
    put_route = respx.put("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=updated)
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/milestones",
        json={"milestone": "C114209", "display": "Subject is Randomized", "date": "2026-07-08"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "researchSubjectId": "subj-1",
        "milestones": [
            {"milestone": "C16735", "display": "Informed Consent", "date": "2026-07-01"},
            {"milestone": "C114209", "display": "Subject is Randomized", "date": "2026-07-08"},
        ],
    }
    sent = put_route.calls.last.request
    assert sent.headers["If-Match"] == 'W/"3"'
    sent_milestones = json.loads(sent.content)["subjectMilestone"]
    assert sent_milestones[-1]["milestone"]["coding"] == [
        {
            "system": "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl",
            "code": "C114209",
            "display": "Subject is Randomized",
        }
    ]


def test_record_milestone_rejects_empty_milestone():
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/milestones", json={"milestone": ""}
    )

    assert response.status_code == 422


@respx.mock
def test_assign_identifier_sets_identifier_on_unassigned_subject():
    unassigned = {k: v for k, v in SUBJECT.items() if k != "identifier"}
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=dict(unassigned, meta={"versionId": "1"}))
    )
    respx.get("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    put_route = respx.put("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/identifier", json={"subjectIdentifier": "SUBJ-001"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "researchSubjectId": "subj-1",
        "subjectIdentifier": "SUBJ-001",
        "patientId": "patient-1",
        "status": "active",
    }
    sent = put_route.calls.last.request
    assert sent.headers["If-Match"] == 'W/"1"'


@respx.mock
def test_assign_identifier_is_idempotent_for_same_value():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    put_route = respx.put("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/identifier", json={"subjectIdentifier": "SUBJ-001"}
    )

    assert response.status_code == 200
    assert response.json()["subjectIdentifier"] == "SUBJ-001"
    assert not put_route.called


@respx.mock
def test_assign_identifier_rejects_subject_with_different_identifier():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/identifier", json={"subjectIdentifier": "SUBJ-002"}
    )

    assert response.status_code == 409
    assert "already has identifier 'SUBJ-001'" in response.json()["detail"]


@respx.mock
def test_assign_identifier_rejects_value_taken_by_another_subject():
    unassigned = {k: v for k, v in SUBJECT.items() if k != "identifier"}
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=unassigned)
    )
    respx.get("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {
                    "resourceType": "ResearchSubject",
                    "id": "subj-other",
                    "identifier": [
                        {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-002"}
                    ],
                }
            ),
        )
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/identifier", json={"subjectIdentifier": "SUBJ-002"}
    )

    assert response.status_code == 409
    assert "already in use" in response.json()["detail"]


def test_assign_identifier_rejects_empty_value():
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/identifier", json={"subjectIdentifier": ""}
    )

    assert response.status_code == 422


@respx.mock
def test_withdraw_route_updates_subject_state():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=dict(SUBJECT, meta={"versionId": "1"}))
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    for resource_type in ("ServiceRequest", "Appointment", "Encounter", "Task"):
        respx.get(f"https://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json={"resourceType": "Bundle"})
        )
    respx.put("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ResearchSubject",
                "id": "subj-1",
                # R6: withdrawn subjects get status "retired"
                "status": "retired",
            },
        )
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post("/api/research-subjects/subj-1/withdraw")

    assert response.status_code == 200
    assert response.json() == {"id": "subj-1", "subjectState": "withdrawn"}


@respx.mock
def test_complete_visit_route_marks_finished_and_returns_schedule():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    respx.get("https://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER))
    )
    respx.get("https://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("https://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("https://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
        ]
    )
    respx.put("https://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    respx.put("https://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-subjects/subj-1/visits/screening-1/complete", json={"transitionChoice": None}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["completed"] == ["screening-1"]
    assert body["visits"]["screening-1"]["phase"] == "completed"


def _app_client_with_dummy_fhir_client() -> TestClient:
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    return TestClient(app)


_EMPTY_SCHEDULE = {"completed": [], "current": [], "nextSteps": [], "ambiguous": False, "visits": {}}


def test_plan_route_returns_conflict_on_phase_error(monkeypatch):
    async def raise_phase_error(client, subject_id, action_id, to_intent):
        raise PhaseError("visit E1 is in phase 'ordered', expected 'proposed'")

    monkeypatch.setattr("vulcan_soa.api.research_subjects.promote", raise_phase_error)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/plan")

    assert response.status_code == 409
    assert "phase" in response.json()["detail"]


def test_order_route_happy_path(monkeypatch):
    captured = {}

    async def fake_promote(client, subject_id, action_id, to_intent):
        captured["args"] = (subject_id, action_id, to_intent)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.promote", fake_promote)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/order")

    assert response.status_code == 200
    assert response.json() == _EMPTY_SCHEDULE
    assert captured["args"] == ("subj-1", "E1", "order")


def test_schedule_route_happy_path(monkeypatch):
    captured = {}

    async def fake_schedule_visit(client, subject_id, action_id):
        captured["args"] = (subject_id, action_id)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.schedule_visit", fake_schedule_visit)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/schedule")

    assert response.status_code == 200
    assert response.json() == _EMPTY_SCHEDULE
    assert captured["args"] == ("subj-1", "E1")


def test_respond_route_validates_participant(monkeypatch):
    captured = {}

    async def fake_respond(client, subject_id, action_id, participant, resp):
        captured["args"] = (subject_id, action_id, participant, resp)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.respond", fake_respond)

    test_client = _app_client_with_dummy_fhir_client()
    ok = test_client.post(
        "/api/research-subjects/subj-1/visits/E1/respond",
        json={"participant": "patient", "response": "accepted"},
    )
    assert ok.status_code == 200
    assert captured["args"] == ("subj-1", "E1", "patient", "accepted")

    bad = test_client.post(
        "/api/research-subjects/subj-1/visits/E1/respond",
        json={"participant": "sponsor", "response": "accepted"},
    )
    assert bad.status_code == 422


def test_perform_route_happy_path(monkeypatch):
    captured = {}

    async def fake_perform(client, subject_id, action_id):
        captured["args"] = (subject_id, action_id)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.perform", fake_perform)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/perform")

    assert response.status_code == 200
    assert response.json() == _EMPTY_SCHEDULE
    assert captured["args"] == ("subj-1", "E1")


def test_complete_task_route_happy_path(monkeypatch):
    captured = {}

    async def fake_complete_task(client, subject_id, action_id, task_id):
        captured["args"] = (subject_id, action_id, task_id)
        return _EMPTY_SCHEDULE

    monkeypatch.setattr("vulcan_soa.api.research_subjects.complete_task", fake_complete_task)

    test_client = _app_client_with_dummy_fhir_client()
    response = test_client.post("/api/research-subjects/subj-1/visits/E1/tasks/task-1/complete")

    assert response.status_code == 200
    assert response.json() == _EMPTY_SCHEDULE
    assert captured["args"] == ("subj-1", "E1", "task-1")


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


@respx.mock
def test_visit_activities_lists_observations_and_activity_types():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "PlanDefinition",
                "id": "plan-1",
                "action": [
                    {
                        "id": "screening-1",
                        "title": "Screening",
                        "definitionCanonical": "http://example.org/PlanDefinition/visit-screening",
                    }
                ],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/visit-screening").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "PlanDefinition",
                "id": "visit-screening",
                "action": [
                    {
                        "title": "Vital Signs and Temperature",
                        "definitionUri": "ActivityDefinition/act-vitals",
                    },
                    {
                        "title": "ADAS-Cog",
                        "definitionCanonical": "http://example.org/soa/Questionnaire/q-adas-cog",
                    },
                    {"title": "No definition here"},
                ],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ActivityDefinition/act-vitals").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ActivityDefinition",
                "id": "act-vitals",
                "status": "active",
                "observationResultRequirement": [
                    "ObservationDefinition/od-bp-panel",
                    "ObservationDefinition/od-temperature",
                ],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ObservationDefinition/od-bp-panel").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ObservationDefinition",
                "id": "od-bp-panel",
                "code": {"text": "Blood pressure panel"},
                "hasMember": [
                    {"reference": "ObservationDefinition/od-systolic"},
                    {"reference": "ObservationDefinition/od-diastolic"},
                ],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ObservationDefinition/od-systolic").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ObservationDefinition",
                "id": "od-systolic",
                "code": {"coding": [{"code": "8480-6", "display": "Systolic blood pressure"}]},
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ObservationDefinition/od-diastolic").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ObservationDefinition",
                "id": "od-diastolic",
                "code": {"coding": [{"code": "8462-4"}]},
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ObservationDefinition/od-temperature").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ObservationDefinition",
                "id": "od-temperature",
                "code": {"coding": [{"code": "8310-5", "display": "Body temperature"}]},
            },
        )
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/visits/screening-1/activities")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "act-vitals",
            "title": "Vital Signs and Temperature",
            "type": "ActivityDefinition",
            "observations": [
                {
                    "id": "od-bp-panel",
                    "display": "Blood pressure panel",
                    "members": [
                        {
                            "id": "od-systolic",
                            "display": "Systolic blood pressure",
                            "members": [],
                        },
                        {"id": "od-diastolic", "display": "8462-4", "members": []},
                    ],
                },
                {"id": "od-temperature", "display": "Body temperature", "members": []},
            ],
        },
        {
            "id": "q-adas-cog",
            "title": "ADAS-Cog",
            "type": "Questionnaire",
            "observations": [],
        },
    ]


@respx.mock
def test_visit_activities_unknown_action_returns_404():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/visits/nope-9/activities")

    assert response.status_code == 404


@respx.mock
def test_request_event_tree_builds_full_lineage_for_active_visit():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )

    visit_tag = {"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}
    activity_tag = {
        "system": "urn:vulcan-soa:plan-action",
        "value": "plan-1#screening-1#act-vitals",
    }
    service_requests = _bundle(
        {
            "resourceType": "ServiceRequest",
            "id": "sr-visit-proposal",
            "intent": "proposal",
            "status": "completed",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [visit_tag],
            "code": {"concept": {"text": "Screening"}},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "sr-visit-plan",
            "intent": "plan",
            "status": "completed",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [visit_tag],
            "code": {"concept": {"text": "Screening"}},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "sr-visit-order",
            "intent": "order",
            "status": "active",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [visit_tag],
            "code": {"concept": {"text": "Screening"}},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "sr-act-proposal",
            "intent": "proposal",
            "status": "completed",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [activity_tag],
            "code": {"concept": {"text": "Vital Signs"}},
        },
        {
            "resourceType": "ServiceRequest",
            "id": "sr-act-order",
            "intent": "order",
            "status": "active",
            "subject": {"reference": "Patient/patient-1"},
            "identifier": [activity_tag],
            "code": {"concept": {"text": "Vital Signs"}},
        },
    )
    respx.get("https://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=service_requests)
    )
    respx.get("https://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {
                    "resourceType": "Appointment",
                    "id": "appt-1",
                    "status": "booked",
                    "identifier": [visit_tag],
                    "participant": [
                        {"actor": {"reference": "Patient/patient-1"}, "status": "accepted"},
                        {
                            "actor": {"reference": "Practitioner/site-coordinator-demo"},
                            "status": "accepted",
                        },
                    ],
                }
            ),
        )
    )
    respx.get("https://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {
                    "resourceType": "Encounter",
                    "id": "enc-1",
                    "status": "in-progress",
                    "subject": {"reference": "Patient/patient-1"},
                    "identifier": [visit_tag],
                }
            ),
        )
    )
    respx.get("https://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {
                    "resourceType": "Task",
                    "id": "task-1",
                    "status": "completed",
                    "for": {"reference": "Patient/patient-1"},
                    "identifier": [activity_tag],
                    "description": "Vital Signs",
                    "encounter": {"reference": "Encounter/enc-1"},
                    "output": [
                        {
                            "type": {"text": "procedure"},
                            "valueReference": {"reference": "Procedure/proc-1"},
                        }
                    ],
                }
            ),
        )
    )
    respx.get("https://aidbox.test/fhir/Procedure/proc-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Procedure",
                "id": "proc-1",
                "status": "completed",
                "code": {"text": "Vital Signs"},
            },
        )
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/request-event-tree")

    assert response.status_code == 200
    assert response.json() == {
        "id": "subj-1",
        "type": "ResearchSubject",
        "label": "SUBJ-001",
        "children": [
            {
                "id": "sr-visit-proposal",
                "type": "ServiceRequest",
                "label": "Screening — proposal · completed",
                "children": [
                    {
                        "id": "sr-act-proposal",
                        "type": "ServiceRequest",
                        "label": "Vital Signs — proposal · completed",
                        "children": [
                            {
                                "id": "sr-act-order",
                                "type": "ServiceRequest",
                                "label": "Vital Signs — order · active",
                                "children": [
                                    {
                                        "id": "task-1",
                                        "type": "Task",
                                        "label": "Vital Signs — completed",
                                        "children": [
                                            {
                                                "id": "proc-1",
                                                "type": "Procedure",
                                                "label": "Vital Signs — completed",
                                                "children": [],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "id": "sr-visit-plan",
                        "type": "ServiceRequest",
                        "label": "Screening — plan · completed",
                        "children": [
                            {
                                "id": "sr-visit-order",
                                "type": "ServiceRequest",
                                "label": "Screening — order · active",
                                "children": [
                                    {
                                        "id": "appt-1",
                                        "type": "Appointment",
                                        "label": "Appointment — booked",
                                        "children": [
                                            {
                                                "id": "enc-1",
                                                "type": "Encounter",
                                                "label": "Encounter — in-progress",
                                                "children": [],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ],
    }


@respx.mock
def test_request_event_tree_is_empty_for_a_subject_with_no_materialized_visits():
    respx.get("https://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    for resource_type in ("ServiceRequest", "Appointment", "Encounter", "Task"):
        respx.get(f"https://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json={"resourceType": "Bundle"})
        )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/request-event-tree")

    assert response.status_code == 200
    assert response.json() == {
        "id": "subj-1",
        "type": "ResearchSubject",
        "label": "SUBJ-001",
        "children": [],
    }
