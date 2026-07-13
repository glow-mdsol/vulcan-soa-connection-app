from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vulcan_soa.api.cache import router as cache_router
from vulcan_soa.api.context import router as context_router
from vulcan_soa.api.launch import router as launch_router
from vulcan_soa.api.research_studies import router as research_studies_router
from vulcan_soa.api.research_subjects import router as research_subjects_router
from vulcan_soa.api.patients import router as patient_router
from vulcan_soa.cache import TTLCache
from vulcan_soa.config import Settings
from vulcan_soa.store import InMemoryStore


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Vulcan SoA")
    app.state.settings = settings or Settings()
    app.state.session_store = InMemoryStore()
    app.state.pending_launch_store = InMemoryStore()
    # Shared across every request/session: definitional (protocol) resources
    # only, 10-minute TTL. See vulcan_soa.cache and api/cache.py (flush route).
    app.state.definitional_cache = TTLCache()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[app.state.settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(launch_router)
    app.include_router(context_router)
    app.include_router(research_studies_router)
    app.include_router(research_subjects_router)
    app.include_router(patient_router)
    app.include_router(cache_router)

    return app


try:
    app = create_app()
except Exception:  # noqa: BLE001 - module-level app requires .env.local; tests use create_app(settings=...)
    app = None  # type: ignore[assignment]
