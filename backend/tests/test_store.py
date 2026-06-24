from vulcan_soa.store import InMemoryStore


def test_create_and_get_roundtrip():
    store: InMemoryStore[str] = InMemoryStore()
    key = store.create("hello")
    assert store.get(key) == "hello"


def test_get_missing_key_returns_none():
    store: InMemoryStore[str] = InMemoryStore()
    assert store.get("nonexistent") is None


def test_pop_removes_item():
    store: InMemoryStore[str] = InMemoryStore()
    key = store.create("hello")
    assert store.pop(key) == "hello"
    assert store.get(key) is None


def test_create_generates_unique_keys():
    store: InMemoryStore[str] = InMemoryStore()
    key1 = store.create("a")
    key2 = store.create("b")
    assert key1 != key2
