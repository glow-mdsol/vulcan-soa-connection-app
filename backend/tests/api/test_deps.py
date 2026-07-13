import httpx
import respx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.api.deps import SESSION_COOKIE_NAME, get_current_session, get_fhir_client
from vulcan_soa.auth import Session
from vulcan_soa.cache import TTLCache
from vulcan_soa.config import Settings
from vulcan_soa.store import InMemoryStore


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(
        fhir_base_url="https://aidbox.test/fhir",
        oauth_authorize_url="https://aidbox.test/authorize",
        oauth_token_url="https://aidbox.test/token",
        smart_client_id="client-1",
        smart_client_secret="secret-1",
        redirect_uri="https://app.test/callback",
    )
    app.state.session_store = InMemoryStore()
    app.state.pending_launch_store = InMemoryStore()
    app.state.definitional_cache = TTLCache()

    @app.get("/whoami")
    def whoami(session: Session = Depends(get_current_session)):
        return {"patientId": session.patient_id}

    @app.get("/fhir-patient")
    async def fhir_patient(client=Depends(get_fhir_client)):
        return await client.read("Patient", "patient-1")

    return app


def test_get_current_session_returns_401_without_cookie():
    client = TestClient(_build_test_app())
    response = client.get("/whoami")
    assert response.status_code == 401


def test_get_current_session_returns_401_for_unknown_session_id():
    client = TestClient(_build_test_app())
    response = client.get("/whoami", cookies={SESSION_COOKIE_NAME: "does-not-exist"})
    assert response.status_code == 401


def test_get_current_session_succeeds_for_known_session():
    app = _build_test_app()
    session_id = app.state.session_store.create(
        Session(access_token="tok-1", patient_id="patient-1", research_study_id=None)
    )
    client = TestClient(app)

    response = client.get("/whoami", cookies={SESSION_COOKIE_NAME: session_id})

    assert response.status_code == 200
    assert response.json() == {"patientId": "patient-1"}


@respx.mock
def test_get_fhir_client_authorizes_requests_with_session_access_token():
    app = _build_test_app()
    session_id = app.state.session_store.create(
        Session(access_token="tok-1", patient_id="patient-1", research_study_id=None)
    )
    route = respx.get("https://aidbox.test/fhir/Patient/patient-1").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "patient-1"})
    )
    client = TestClient(app)

    response = client.get("/fhir-patient", cookies={SESSION_COOKIE_NAME: session_id})

    assert response.status_code == 200
    assert response.json() == {"resourceType": "Patient", "id": "patient-1"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok-1"
