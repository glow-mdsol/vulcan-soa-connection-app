import httpx
import respx

from scripts.validate_protocol import validate
from vulcan_soa.fhir_client import FhirClient

PROTOCOL = {
    "resourceType": "PlanDefinition",
    "id": "proto-1",
    "action": [
        {"id": "E1", "title": "Visit 1", "definitionUri": "PlanDefinition/visit-1"},
        {"title": "orphan without id"},
    ],
}
VISIT_PD = {
    "resourceType": "PlanDefinition",
    "id": "visit-1",
    "action": [
        {"title": "Consent", "definitionUri": "ActivityDefinition/act-ok"},
        {"title": "Missing", "definitionUri": "ActivityDefinition/act-missing"},
        {"title": "Questionnaire ref is skipped", "definitionUri": "Questionnaire/q-1"},
    ],
}


@respx.mock
async def test_validate_reports_missing_ids_and_unresolvable_definitions():
    respx.get("http://aidbox.test/fhir/PlanDefinition/proto-1").mock(
        return_value=httpx.Response(200, json=PROTOCOL)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/visit-1").mock(
        return_value=httpx.Response(200, json=VISIT_PD)
    )
    respx.get("http://aidbox.test/fhir/ActivityDefinition/act-ok").mock(
        return_value=httpx.Response(200, json={"resourceType": "ActivityDefinition", "id": "act-ok"})
    )
    respx.get("http://aidbox.test/fhir/ActivityDefinition/act-missing").mock(
        return_value=httpx.Response(404, json={"resourceType": "OperationOutcome"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    errors = await validate(client, "proto-1")
    await client.close()

    assert any("without id" in e for e in errors)
    assert any("act-missing" in e for e in errors)
    assert not any("q-1" in e for e in errors)
    assert not any("act-ok" in e for e in errors)
