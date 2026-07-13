from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request

from vulcan_soa.auth import Session
from vulcan_soa.cache import TTLCache
from vulcan_soa.config import Settings
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.store import InMemoryStore

SESSION_COOKIE_NAME = "vulcan_soa_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_store(request: Request) -> InMemoryStore:
    return request.app.state.session_store


def get_pending_launch_store(request: Request) -> InMemoryStore:
    return request.app.state.pending_launch_store


def get_definitional_cache(request: Request) -> TTLCache:
    return request.app.state.definitional_cache


def get_current_session(
    request: Request, session_store: InMemoryStore = Depends(get_session_store)
) -> Session:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session = session_store.get(session_id) if session_id else None
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return session


async def get_fhir_client(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
    definitional_cache: TTLCache = Depends(get_definitional_cache),
) -> AsyncIterator[FhirClient]:
    client = FhirClient(
        base_url=settings.fhir_base_url,
        access_token=session.access_token,
        definitional_cache=definitional_cache,
    )
    try:
        yield client
    finally:
        await client.close()
