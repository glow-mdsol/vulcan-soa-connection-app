import httpx

from vulcan_soa.cache import DEFINITIONAL_RESOURCE_TYPES, TTLCache

FHIR_JSON = "application/fhir+json"


class FhirClient:
    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        basic_auth: tuple[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        definitional_cache: TTLCache | None = None,
    ) -> None:
        if not access_token and not basic_auth:
            raise ValueError("FhirClient requires either access_token or basic_auth")

        self._base_url = base_url.rstrip("/")
        self._cache = definitional_cache
        headers = {"Content-Type": FHIR_JSON, "Accept": FHIR_JSON}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        if http_client is not None:
            self._client = http_client
        else:
            auth = httpx.BasicAuth(*basic_auth) if basic_auth else None
            self._client = httpx.AsyncClient(auth=auth, headers=headers)

    async def read(self, resource_type: str, resource_id: str) -> dict:
        cache = self._cache if resource_type in DEFINITIONAL_RESOURCE_TYPES else None
        if cache is not None:
            cached = cache.get(resource_type, resource_id)
            if cached is not None:
                return cached

        response = await self._client.get(f"{self._base_url}/{resource_type}/{resource_id}")
        response.raise_for_status()
        resource = response.json()

        if cache is not None:
            cache.set(resource_type, resource_id, resource)
        return resource

    async def search(self, resource_type: str, params: dict[str, str]) -> list[dict]:
        # Request a large page and follow Bundle.link[next] so callers see every
        # match, not just the server's default first page.
        merged = {"_count": "200", **params}
        response = await self._client.get(f"{self._base_url}/{resource_type}", params=merged)
        response.raise_for_status()
        bundle = response.json()

        resources: list[dict] = []
        while True:
            for entry in bundle.get("entry", []):
                if "resource" in entry:
                    resources.append(entry["resource"])
            next_url = next(
                (link.get("url") for link in bundle.get("link", []) if link.get("relation") == "next"),
                None,
            )
            if not next_url:
                return resources
            response = await self._client.get(next_url)
            response.raise_for_status()
            bundle = response.json()

    async def create(self, resource_type: str, resource: dict) -> dict:
        response = await self._client.post(f"{self._base_url}/{resource_type}", json=resource)
        response.raise_for_status()
        return response.json()

    async def update(
        self, resource_type: str, resource_id: str, resource: dict, if_match: str | None = None
    ) -> dict:
        headers = {"If-Match": if_match} if if_match else {}
        response = await self._client.put(
            f"{self._base_url}/{resource_type}/{resource_id}", json=resource, headers=headers
        )
        response.raise_for_status()
        return response.json()

    async def delete(self, resource_type: str, resource_id: str) -> None:
        response = await self._client.delete(f"{self._base_url}/{resource_type}/{resource_id}")
        response.raise_for_status()

    async def conditional_create(
        self, resource_type: str, resource: dict, search_params: dict[str, str]
    ) -> dict:
        existing = await self.search(resource_type, search_params)
        if existing:
            return existing[0]
        return await self.create(resource_type, resource)

    async def put_by_id(self, resource_type: str, resource_id: str, resource: dict) -> dict:
        response = await self._client.put(
            f"{self._base_url}/{resource_type}/{resource_id}", json=resource
        )
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()
