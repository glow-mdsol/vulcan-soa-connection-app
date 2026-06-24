import json

import httpx
import respx

from scripts.load_fixtures import load_directory
from vulcan_soa.fhir_client import FhirClient


def write_json(path, data):
    path.write_text(json.dumps(data))


@respx.mock
async def test_loads_valid_resource(tmp_path):
    write_json(tmp_path / "patient.json", {"resourceType": "Patient", "id": "p1"})
    respx.put("http://aidbox.test/fhir/Patient/p1").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "p1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    results = await load_directory(client, tmp_path)
    await client.close()

    assert results == [(tmp_path / "patient.json", "OK")]


@respx.mock
async def test_skips_non_dict_json(tmp_path):
    write_json(tmp_path / "list.json", ["not", "a", "resource"])
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    results = await load_directory(client, tmp_path)
    await client.close()

    assert results[0][1].startswith("SKIP")


@respx.mock
async def test_skips_dict_without_resource_type(tmp_path):
    write_json(tmp_path / "manifest.json", {"some": "manifest", "id": "x"})
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    results = await load_directory(client, tmp_path)
    await client.close()

    assert results[0][1].startswith("SKIP")


@respx.mock
async def test_skips_invalid_json(tmp_path):
    (tmp_path / "broken.json").write_text("{not valid json")
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    results = await load_directory(client, tmp_path)
    await client.close()

    assert results[0][1].startswith("SKIP")


@respx.mock
async def test_records_failure_without_stopping(tmp_path):
    write_json(tmp_path / "a_bad.json", {"resourceType": "Patient", "id": "bad"})
    write_json(tmp_path / "b_good.json", {"resourceType": "Patient", "id": "good"})
    respx.put("http://aidbox.test/fhir/Patient/bad").mock(return_value=httpx.Response(422))
    respx.put("http://aidbox.test/fhir/Patient/good").mock(
        return_value=httpx.Response(200, json={"resourceType": "Patient", "id": "good"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    results = await load_directory(client, tmp_path)
    await client.close()

    outcomes = dict((p.name, outcome) for p, outcome in results)
    assert outcomes["a_bad.json"].startswith("FAIL")
    assert outcomes["b_good.json"] == "OK"
