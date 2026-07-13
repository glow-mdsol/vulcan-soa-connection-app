from fastapi import FastAPI
from fastapi.testclient import TestClient

from vulcan_soa.api.cache import router as cache_router
from vulcan_soa.api.deps import SESSION_COOKIE_NAME
from vulcan_soa.auth import Session
from vulcan_soa.cache import TTLCache
from vulcan_soa.store import InMemoryStore


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.state.session_store = InMemoryStore()
    app.state.definitional_cache = TTLCache()
    app.include_router(cache_router)
    return app


def test_flush_requires_an_authenticated_session():
    app = _build_test_app()
    client = TestClient(app)

    response = client.post("/api/cache/flush")

    assert response.status_code == 401


def test_flush_clears_the_definitional_cache_and_reports_the_count():
    app = _build_test_app()
    app.state.definitional_cache.set("PlanDefinition", "plan-1", {"id": "plan-1"})
    app.state.definitional_cache.set("ActivityDefinition", "act-1", {"id": "act-1"})
    session_id = app.state.session_store.create(
        Session(access_token="tok-1", patient_id=None, research_study_id=None)
    )
    client = TestClient(app)

    response = client.post("/api/cache/flush", cookies={SESSION_COOKIE_NAME: session_id})

    assert response.status_code == 200
    assert response.json() == {"cleared": 2}
    assert app.state.definitional_cache.get("PlanDefinition", "plan-1") is None


def test_flush_on_an_already_empty_cache_reports_zero():
    app = _build_test_app()
    session_id = app.state.session_store.create(
        Session(access_token="tok-1", patient_id=None, research_study_id=None)
    )
    client = TestClient(app)

    response = client.post("/api/cache/flush", cookies={SESSION_COOKIE_NAME: session_id})

    assert response.status_code == 200
    assert response.json() == {"cleared": 0}
