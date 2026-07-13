from fastapi import APIRouter, Depends

from vulcan_soa.api.deps import get_current_session, get_definitional_cache
from vulcan_soa.auth import Session
from vulcan_soa.cache import TTLCache

router = APIRouter(prefix="/api/cache")


@router.post("/flush")
async def flush_definitional_cache(
    _session: Session = Depends(get_current_session),
    cache: TTLCache = Depends(get_definitional_cache),
) -> dict:
    return {"cleared": cache.clear()}
