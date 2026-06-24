import base64
import hashlib
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from vulcan_soa.auth import (
    PendingLaunch,
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
    parse_research_study_id,
    session_from_token_response,
)
from vulcan_soa.config import Settings

SETTINGS = Settings(
    fhir_base_url="https://aidbox.test/fhir",
    oauth_authorize_url="https://aidbox.test/authorize",
    oauth_token_url="https://aidbox.test/token",
    smart_client_id="client-1",
    smart_client_secret="secret-1",
    redirect_uri="https://app.test/callback",
)


def test_generate_pkce_pair_challenge_matches_verifier():
    code_verifier, code_challenge = generate_pkce_pair()

    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    expected_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    assert code_challenge == expected_challenge
    assert len(code_verifier) >= 43  # RFC 7636 minimum


def test_build_authorize_url_includes_launch_scope_for_ehr_launch():
    pending = PendingLaunch(code_verifier="verifier-1", launch="launch-1")
    url = build_authorize_url(SETTINGS, pending, state="state-1", code_challenge="challenge-1")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "aidbox.test"
    assert parsed.path == "/authorize"
    assert "launch" in query["scope"][0]
    assert query["launch"] == ["launch-1"]
    assert query["state"] == ["state-1"]
    assert query["code_challenge"] == ["challenge-1"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == ["client-1"]
    assert query["redirect_uri"] == ["https://app.test/callback"]


def test_build_authorize_url_omits_launch_for_standalone():
    pending = PendingLaunch(code_verifier="verifier-1", launch=None)
    url = build_authorize_url(SETTINGS, pending, state="state-1", code_challenge="challenge-1")

    query = parse_qs(urlparse(url).query)
    assert "launch" not in query
    assert "launch" not in query["scope"][0]


@respx.mock
async def test_exchange_code_for_token_posts_pkce_verifier_and_basic_auth():
    route = respx.post("https://aidbox.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "patient": "patient-1"})
    )

    async with httpx.AsyncClient() as http_client:
        token_response = await exchange_code_for_token(SETTINGS, http_client, "code-1", "verifier-1")

    assert token_response == {"access_token": "tok-1", "patient": "patient-1"}
    sent = route.calls.last.request
    assert sent.headers["Authorization"].startswith("Basic ")
    body = parse_qs(sent.content.decode("utf-8"))
    assert body["grant_type"] == ["authorization_code"]
    assert body["code"] == ["code-1"]
    assert body["code_verifier"] == ["verifier-1"]
    assert body["redirect_uri"] == ["https://app.test/callback"]


def test_parse_research_study_id_finds_research_study_reference():
    fhir_context = [{"reference": "Patient/patient-1"}, {"reference": "ResearchStudy/study-1"}]
    assert parse_research_study_id(fhir_context) == "study-1"


def test_parse_research_study_id_returns_none_when_absent_or_empty():
    assert parse_research_study_id([{"reference": "Patient/patient-1"}]) is None
    assert parse_research_study_id(None) is None
    assert parse_research_study_id([]) is None


def test_session_from_token_response_extracts_patient_and_research_study():
    token_response = {
        "access_token": "tok-1",
        "patient": "patient-1",
        "fhirContext": [{"reference": "ResearchStudy/study-1"}],
    }
    session = session_from_token_response(token_response)

    assert session.access_token == "tok-1"
    assert session.patient_id == "patient-1"
    assert session.research_study_id == "study-1"


def test_session_from_token_response_handles_missing_context():
    session = session_from_token_response({"access_token": "tok-1"})
    assert session.patient_id is None
    assert session.research_study_id is None
