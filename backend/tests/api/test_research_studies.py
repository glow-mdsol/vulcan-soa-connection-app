import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.research_studies import router as research_studies_router
from vulcan_soa.fhir_client import FhirClient


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(research_studies_router)
    return app


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
        return_value=httpx.Response(201, json={"resourceType": "ResearchSubject", "id": "subj-1"})
    )
    respx.post("https://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "enc-1"})
    )

    app = _build_test_app()
    app.dependency_overrides[get_fhir_client] = lambda: FhirClient(
        base_url="https://aidbox.test/fhir", access_token="tok-1"
    )
    test_client = TestClient(app)

    response = test_client.post(
        "/api/research-studies/study-1/enroll", json={"patientId": "patient-1"}
    )

    assert response.status_code == 200
    assert response.json()["researchSubjectId"] == "subj-1"
