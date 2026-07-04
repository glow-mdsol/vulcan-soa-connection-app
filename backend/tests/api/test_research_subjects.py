import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
    respx.get("https://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-subjects/subj-1/schedule")

    assert response.status_code == 200
    assert response.json()["nextSteps"] == [
        {"actionId": "screening-1", "title": "Screening", "transitionType": None}
    ]


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
    encounter = {
        "resourceType": "Encounter",
        "id": "enc-1",
        "status": "planned",
        "identifier": [{"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}],
    }
    finished_encounter = dict(encounter, status="completed")
    respx.get("https://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": encounter}]}),
            httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": finished_encounter}]}),
        ]
    )
    respx.put("https://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=finished_encounter)
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
    assert response.json()["completed"] == ["screening-1"]
