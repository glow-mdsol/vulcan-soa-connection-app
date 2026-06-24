from urllib.parse import parse_qs, urlparse

import httpx
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.api.deps import SESSION_COOKIE_NAME
from vulcan_soa.api.launch import router as launch_router
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
        frontend_url="https://app.test",
    )
    app.state.pending_launch_store = InMemoryStore()
    app.state.session_store = InMemoryStore()
    app.include_router(launch_router)
    return app


def test_launch_redirects_to_authorize_url_for_trusted_iss():
    client = TestClient(_build_test_app(), follow_redirects=False)

    response = client.get("/launch", params={"iss": "https://aidbox.test/fhir", "launch": "launch-1"})

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("https://aidbox.test/authorize?")
    assert "launch=launch-1" in location


def test_launch_redirects_to_error_page_for_untrusted_iss():
    client = TestClient(_build_test_app(), follow_redirects=False)

    response = client.get("/launch", params={"iss": "https://evil.test/fhir", "launch": "launch-1"})

    assert response.status_code in (302, 307)
    assert response.headers["location"].startswith("https://app.test/launch-error")


def test_launch_standalone_redirects_to_authorize_url_without_launch_param():
    client = TestClient(_build_test_app(), follow_redirects=False)

    response = client.get("/launch/standalone")

    location = response.headers["location"]
    assert location.startswith("https://aidbox.test/authorize?")
    assert "launch=" not in location


@respx.mock
def test_launch_then_callback_round_trip_sets_session_cookie():
    respx.post("https://aidbox.test/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "tok-1",
                "patient": "patient-1",
                "fhirContext": [{"reference": "ResearchStudy/study-1"}],
            },
        )
    )
    app = _build_test_app()
    client = TestClient(app, follow_redirects=False)

    launch_response = client.get(
        "/launch", params={"iss": "https://aidbox.test/fhir", "launch": "launch-1"}
    )
    authorize_location = launch_response.headers["location"]
    state = parse_qs(urlparse(authorize_location).query)["state"][0]

    callback_response = client.get("/callback", params={"code": "code-1", "state": state})

    assert callback_response.status_code in (302, 307)
    assert callback_response.headers["location"] == "https://app.test"
    assert "HttpOnly" in callback_response.headers["set-cookie"]
    session_id = callback_response.cookies[SESSION_COOKIE_NAME]
    session = app.state.session_store.get(session_id)
    assert session.access_token == "tok-1"
    assert session.patient_id == "patient-1"
    assert session.research_study_id == "study-1"


def test_callback_redirects_to_error_page_for_unknown_state():
    client = TestClient(_build_test_app(), follow_redirects=False)

    response = client.get("/callback", params={"code": "code-1", "state": "does-not-exist"})

    assert response.headers["location"].startswith("https://app.test/launch-error")
