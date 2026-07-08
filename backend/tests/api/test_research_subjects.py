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
