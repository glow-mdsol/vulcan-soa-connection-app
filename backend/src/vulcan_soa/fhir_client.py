import httpx

FHIR_JSON = "application/fhir+json"


class FhirClient:
    def __init__(
        self,
        base_url: str,
        *,
        access_token: str | None = None,
        basic_auth: tuple[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not access_token and not basic_auth:
            raise ValueError("FhirClient requires either access_token or basic_auth")

        self._base_url = base_url.rstrip("/")
        headers = {"Content-Type": FHIR_JSON, "Accept": FHIR_JSON}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        if http_client is not None:
            self._client = http_client
        else:
            auth = httpx.BasicAuth(*basic_auth) if basic_auth else None
            self._client = httpx.AsyncClient(auth=auth, headers=headers)

    async def read(self, resource_type: str, resource_id: str) -> dict:
        response = await self._client.get(f"{self._base_url}/{resource_type}/{resource_id}")
        response.raise_for_status()
        return response.json()

    async def search(self, resource_type: str, params: dict[str, str]) -> list[dict]:
        response = await self._client.get(f"{self._base_url}/{resource_type}", params=params)
        response.raise_for_status()
        bundle = response.json()
        return [entry["resource"] for entry in bundle.get("entry", [])]

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
