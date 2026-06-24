import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from vulcan_soa.config import Settings


@dataclass(frozen=True)
class PendingLaunch:
    code_verifier: str
    launch: str | None


@dataclass(frozen=True)
class Session:
    access_token: str
    patient_id: str | None
    research_study_id: str | None


def generate_pkce_pair() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def build_authorize_url(
    settings: Settings, pending_launch: PendingLaunch, *, state: str, code_challenge: str
) -> str:
    scope = "openid fhirUser patient/*.read"
    if pending_launch.launch is not None:
        scope = f"{scope} launch"

    params = {
        "response_type": "code",
        "client_id": settings.smart_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "aud": settings.fhir_base_url,
    }
    if pending_launch.launch is not None:
        params["launch"] = pending_launch.launch

    return f"{settings.oauth_authorize_url}?{urlencode(params)}"


async def exchange_code_for_token(
    settings: Settings, http_client: httpx.AsyncClient, code: str, code_verifier: str
) -> dict:
    response = await http_client.post(
        settings.oauth_token_url,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.smart_client_id,
            "code_verifier": code_verifier,
        },
        auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    response.raise_for_status()
    return response.json()


def parse_research_study_id(fhir_context: list[dict] | None) -> str | None:
    if not fhir_context:
        return None
    for entry in fhir_context:
        reference = entry.get("reference", "")
        if reference.startswith("ResearchStudy/"):
            return reference.split("/", 1)[1]
    return None


def session_from_token_response(token_response: dict) -> Session:
    return Session(
        access_token=token_response["access_token"],
        patient_id=token_response.get("patient"),
        research_study_id=parse_research_study_id(token_response.get("fhirContext")),
    )
