import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from vulcan_soa.api.deps import (
    SESSION_COOKIE_NAME,
    get_pending_launch_store,
    get_session_store,
    get_settings,
)
from vulcan_soa.auth import (
    PendingLaunch,
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
    session_from_token_response,
)
from vulcan_soa.config import Settings
from vulcan_soa.store import InMemoryStore

router = APIRouter()


def _start_launch(settings: Settings, pending_launch_store: InMemoryStore, launch: str | None):
    code_verifier, code_challenge = generate_pkce_pair()
    pending = PendingLaunch(code_verifier=code_verifier, launch=launch)
    state = pending_launch_store.create(pending)
    authorize_url = build_authorize_url(settings, pending, state=state, code_challenge=code_challenge)
    return RedirectResponse(authorize_url)


@router.get("/launch")
async def launch(
    iss: str,
    launch: str,
    settings: Settings = Depends(get_settings),
    pending_launch_store: InMemoryStore = Depends(get_pending_launch_store),
):
    if iss != settings.fhir_base_url:
        return RedirectResponse(f"{settings.frontend_url}/launch-error?reason=untrusted_iss")
    return _start_launch(settings, pending_launch_store, launch)


@router.get("/launch/standalone")
async def launch_standalone(
    settings: Settings = Depends(get_settings),
    pending_launch_store: InMemoryStore = Depends(get_pending_launch_store),
):
    return _start_launch(settings, pending_launch_store, None)


@router.get("/callback")
async def callback(
    code: str,
    state: str,
    settings: Settings = Depends(get_settings),
    pending_launch_store: InMemoryStore = Depends(get_pending_launch_store),
    session_store: InMemoryStore = Depends(get_session_store),
):
    pending = pending_launch_store.pop(state)
    if pending is None:
        return RedirectResponse(f"{settings.frontend_url}/launch-error?reason=invalid_state")

    async with httpx.AsyncClient() as http_client:
        token_response = await exchange_code_for_token(
            settings, http_client, code, pending.code_verifier
        )

    session = session_from_token_response(token_response)
    session_id = session_store.create(session)

    response = RedirectResponse(settings.frontend_url)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        samesite="lax",
        secure=settings.frontend_url.startswith("https://"),
    )
    return response
