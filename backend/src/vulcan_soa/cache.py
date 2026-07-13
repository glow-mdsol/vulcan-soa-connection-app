import time

# Protocol content (ResearchStudy, PlanDefinition, ActivityDefinition, Questionnaire,
# ObservationDefinition) is read-mostly and shared across every subject/session in a
# study, unlike ResearchSubject/ServiceRequest/Appointment/Encounter/Task/Procedure,
# which change on nearly every request. Nothing in this app ever writes to these
# resource types, so a read-through cache with a short TTL is safe.
DEFINITIONAL_RESOURCE_TYPES = frozenset(
    {
        "ResearchStudy",
        "PlanDefinition",
        "ActivityDefinition",
        "Questionnaire",
        "ObservationDefinition",
    }
)

DEFAULT_TTL_SECONDS = 600.0  # 10 minutes


class TTLCache:
    """Process-wide, in-memory TTL cache keyed by (resourceType, id).

    One instance lives on `app.state` for the life of the process and is
    shared across requests (each request gets its own `FhirClient`, but they
    all read through the same cache) — see `api/deps.get_fhir_client`.
    """

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl_seconds = ttl_seconds
        self._entries: dict[tuple[str, str], tuple[float, dict]] = {}

    def get(self, resource_type: str, resource_id: str) -> dict | None:
        key = (resource_type, resource_id)
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            del self._entries[key]
            return None
        return value

    def set(self, resource_type: str, resource_id: str, value: dict) -> None:
        self._entries[(resource_type, resource_id)] = (
            time.monotonic() + self._ttl_seconds,
            value,
        )

    def clear(self) -> int:
        """Flush every cached entry. Returns how many entries were cleared."""
        cleared = len(self._entries)
        self._entries.clear()
        return cleared

    def __len__(self) -> int:
        return len(self._entries)
