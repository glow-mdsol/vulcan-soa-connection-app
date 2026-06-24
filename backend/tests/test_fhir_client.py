import httpx
import pytest
import respx

from vulcan_soa.fhir_client import FhirClient


def make_client(respx_mock) -> FhirClient:
    transport = httpx.MockTransport(respx_mock.handler) if False else None
    return FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")


def test_requires_access_token_or_basic_auth():
    with pytest.raises(ValueError):
        FhirClient(base_url="http://aidbox.test/fhir")


@respx.mock
async def test_read_sends_bearer_and_returns_json():
    route = respx.get("http://aidbox.test/fhir/Patient/p1").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    result = await client.read("Patient", "p1")
    await client.close()

    assert result == {"resourceType": "Patient", "id": "p1"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer tok-123"


@respx.mock
async def test_search_extracts_bundle_entries():
    respx.get("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {"resource": {"resourceType": "Patient", "id": "p1"}},
                    {"resource": {"resourceType": "Patient", "id": "p2"}},
                ],
            },
        )
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    results = await client.search("Patient", {"name": "demo"})
    await client.close()

    assert [r["id"] for r in results] == ["p1", "p2"]


@respx.mock
async def test_search_with_no_entries_returns_empty_list():
    respx.get("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    results = await client.search("Patient", {})
    await client.close()

    assert results == []


@respx.mock
async def test_create_posts_resource():
    route = respx.post("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(201, json={"resourceType": "Patient", "id": "new-1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    result = await client.create("Patient", {"resourceType": "Patient"})
    await client.close()

    assert result["id"] == "new-1"
    assert route.calls.last.request.content


@respx.mock
async def test_update_sends_if_match_header():
    route = respx.put("http://aidbox.test/fhir/Patient/p1").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    await client.update("Patient", "p1", {"resourceType": "Patient", "id": "p1"}, if_match="W/\"3\"")
    await client.close()

    assert route.calls.last.request.headers["If-Match"] == 'W/"3"'


@respx.mock
async def test_conditional_create_returns_existing_when_found():
    respx.get("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "Patient", "id": "existing-1"}}],
            },
        )
    )
    create_route = respx.post("http://aidbox.test/fhir/Patient")
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    result = await client.conditional_create(
        "Patient", {"resourceType": "Patient"}, {"identifier": "x"}
    )
    await client.close()

    assert result["id"] == "existing-1"
    assert not create_route.called


@respx.mock
async def test_conditional_create_creates_when_not_found():
    respx.get("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    respx.post("http://aidbox.test/fhir/Patient").mock(
        return_value=httpx.Response(201, json={"resourceType": "Patient", "id": "new-1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    result = await client.conditional_create(
        "Patient", {"resourceType": "Patient"}, {"identifier": "x"}
    )
    await client.close()

    assert result["id"] == "new-1"


@respx.mock
async def test_put_by_id_uses_basic_auth_when_configured():
    route = respx.put("http://aidbox.test/fhir/Patient/p1").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})
    )
    client = FhirClient(
        base_url="http://aidbox.test/fhir", basic_auth=("client-id", "client-secret")
    )
    await client.put_by_id("Patient", "p1", {"resourceType": "Patient", "id": "p1"})
    await client.close()

    auth_header = route.calls.last.request.headers["Authorization"]
    assert auth_header.startswith("Basic ")


@respx.mock
async def test_raises_on_http_error():
    respx.get("http://aidbox.test/fhir/Patient/missing").mock(return_value=httpx.Response(404))
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok-123")
    with pytest.raises(httpx.HTTPStatusError):
        await client.read("Patient", "missing")
    await client.close()
