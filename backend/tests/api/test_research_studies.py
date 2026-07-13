import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.research_studies import router as research_studies_router
from vulcan_soa.enrollment import EnrollmentConflict
from vulcan_soa.fhir_client import FhirClient


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(research_studies_router)
    return app


def _app_client() -> TestClient:
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    return TestClient(app)


@respx.mock
def test_list_research_studies_returns_id_and_title():
    respx.get("https://aidbox.test/fhir/ResearchStudy").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "ResearchStudy",
                            "id": "study-1",
                            "title": "UC1 Demo Study",
                        }
                    }
                ],
            },
        )
    )
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-studies")

    assert response.status_code == 200
    assert response.json() == [{"id": "study-1", "title": "UC1 Demo Study"}]


@respx.mock
def test_enroll_patient_calls_enrollment_and_returns_schedule():
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ResearchStudy",
                "id": "study-1",
                "protocol": [{"reference": "PlanDefinition/plan-1"}],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "PlanDefinition",
                "id": "plan-1",
                "action": [{"id": "screening-1", "title": "Screening"}],
            },
        )
    )
    respx.get("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    respx.post("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            201,
            json={
                "resourceType": "ResearchSubject",
                "id": "subj-1",
                "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
            },
        )
    )
    respx.post("https://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    test_client = _app_client()

    response = test_client.post(
        "/api/research-studies/study-1/enroll",
        json={"patientId": "patient-1", "subjectIdentifier": "SUBJ-001"},
    )

    assert response.status_code == 200
    assert response.json()["researchSubjectId"] == "subj-1"


def test_enroll_route_maps_conflict_to_409(monkeypatch):
    async def raise_conflict(client, study_id, patient_id, subject_identifier, plan_definition_id=None):
        raise EnrollmentConflict("subject identifier 'SUBJ-001' is already in use in this study")

    monkeypatch.setattr("vulcan_soa.api.research_studies.enroll", raise_conflict)
    test_client = _app_client()
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


@respx.mock
def test_get_research_study_returns_study_details():
    respx.get("https://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ResearchStudy",
                "id": "study-1",
                "title": "UC1 Demo Study",
                "status": "active",
                "protocol": [{"reference": "PlanDefinition/plan-1"}],
            },
        )
    )
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-studies/study-1")

    assert response.status_code == 200
    assert response.json() == {
        "id": "study-1",
        "title": "UC1 Demo Study",
        "status": "active",
        "protocolReferences": ["PlanDefinition/plan-1"],
    }


@respx.mock
def test_list_study_subjects_maps_summaries():
    respx.get("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "ResearchSubject",
                            "id": "subj-1",
                            "status": "active",
                            "subject": {"reference": "Patient/patient-1"},
                            "identifier": [
                                {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}
                            ],
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "ResearchSubject",
                            "id": "subj-2",
                            "status": "retired",
                            "subject": {"reference": "Patient/patient-2"},
                        }
                    },
                ],
            },
        )
    )
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

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


@respx.mock
def test_list_study_subjects_returns_empty_list():
    respx.get("https://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.get("/api/research-studies/study-1/subjects")

    assert response.status_code == 200
    assert response.json() == []
