import secrets
from typing import Generic, TypeVar

T = TypeVar("T")


class InMemoryStore(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def create(self, item: T) -> str:
        key = secrets.token_urlsafe(32)
        self._items[key] = item
        return key

    def get(self, key: str) -> T | None:
        return self._items.get(key)

    def pop(self, key: str) -> T | None:
        return self._items.pop(key, None)
