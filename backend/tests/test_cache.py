from vulcan_soa.cache import DEFINITIONAL_RESOURCE_TYPES, TTLCache


def test_get_returns_none_for_a_missing_key():
    cache = TTLCache(ttl_seconds=600)
    assert cache.get("PlanDefinition", "plan-1") is None


def test_set_then_get_returns_the_cached_value():
    cache = TTLCache(ttl_seconds=600)
    cache.set("PlanDefinition", "plan-1", {"resourceType": "PlanDefinition", "id": "plan-1"})

    assert cache.get("PlanDefinition", "plan-1") == {
        "resourceType": "PlanDefinition",
        "id": "plan-1",
    }


def test_entries_expire_after_the_ttl(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("vulcan_soa.cache.time.monotonic", lambda: now)
    cache = TTLCache(ttl_seconds=600)
    cache.set("PlanDefinition", "plan-1", {"id": "plan-1"})

    now += 599
    assert cache.get("PlanDefinition", "plan-1") == {"id": "plan-1"}

    now += 2
    assert cache.get("PlanDefinition", "plan-1") is None


def test_expired_entry_is_evicted_from_the_underlying_store(monkeypatch):
    now = 1000.0
    monkeypatch.setattr("vulcan_soa.cache.time.monotonic", lambda: now)
    cache = TTLCache(ttl_seconds=600)
    cache.set("PlanDefinition", "plan-1", {"id": "plan-1"})

    now += 601
    cache.get("PlanDefinition", "plan-1")

    assert len(cache) == 0


def test_cache_keys_are_scoped_by_both_resource_type_and_id():
    cache = TTLCache(ttl_seconds=600)
    cache.set("PlanDefinition", "shared-id", {"id": "shared-id", "kind": "plan"})
    cache.set("ActivityDefinition", "shared-id", {"id": "shared-id", "kind": "activity"})

    assert cache.get("PlanDefinition", "shared-id") == {"id": "shared-id", "kind": "plan"}
    assert cache.get("ActivityDefinition", "shared-id") == {"id": "shared-id", "kind": "activity"}


def test_clear_empties_the_cache_and_returns_the_count_cleared():
    cache = TTLCache(ttl_seconds=600)
    cache.set("PlanDefinition", "plan-1", {"id": "plan-1"})
    cache.set("ActivityDefinition", "act-1", {"id": "act-1"})

    cleared = cache.clear()

    assert cleared == 2
    assert len(cache) == 0
    assert cache.get("PlanDefinition", "plan-1") is None


def test_clear_on_an_empty_cache_returns_zero():
    cache = TTLCache(ttl_seconds=600)
    assert cache.clear() == 0


def test_definitional_resource_types_cover_protocol_content_only():
    assert DEFINITIONAL_RESOURCE_TYPES == {
        "ResearchStudy",
        "PlanDefinition",
        "ActivityDefinition",
        "Questionnaire",
        "ObservationDefinition",
    }
    # Subject-instance data must never be cached process-wide across sessions.
    assert "ResearchSubject" not in DEFINITIONAL_RESOURCE_TYPES
    assert "Patient" not in DEFINITIONAL_RESOURCE_TYPES
