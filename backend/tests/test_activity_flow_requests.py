import json

import httpx
import pytest
import respx

from vulcan_soa.activity_flow import PhaseError, materialize_proposal, promote
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.soa_engine.graph import VisitNode

VISIT_PD = {
    "resourceType": "PlanDefinition",
    "id": "E1-USDM",
    "action": [
        {"title": "no definition"},
        {"title": "Informed Consent", "definitionUri": "ActivityDefinition/act-consent"},
        {"title": "ADAS-Cog", "definitionUri": "Questionnaire/act-adas-cog"},
    ],
}
CONSENT_AD = {
    "resourceType": "ActivityDefinition",
    "id": "act-consent",
    "title": "Informed Consent",
    "kind": "ServiceRequest",
    "code": {"coding": [{"system": "http://www.cdisc.org", "code": "C16735", "display": "Informed Consent"}]},
}


@respx.mock
async def test_materialize_proposal_creates_visit_and_activity_requests():
    respx.get("http://aidbox.test/fhir/PlanDefinition/E1-USDM").mock(
        return_value=httpx.Response(200, json=VISIT_PD)
    )
    respx.get("http://aidbox.test/fhir/ActivityDefinition/act-consent").mock(
        return_value=httpx.Response(200, json=CONSENT_AD)
    )
    create_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        side_effect=[
            httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-visit"}),
            httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-act"}),
        ]
    )

    node = VisitNode(
        action_id="E1", title="Screening 1", transitions=(), definition_uri="PlanDefinition/E1-USDM"
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    created = await materialize_proposal(client, "p-1", "pd-1", node)
    await client.close()

    assert created["id"] == "sr-visit"
    assert create_route.call_count == 2

    visit_payload = json.loads(create_route.calls[0].request.content)
    assert visit_payload["intent"] == "proposal"
    assert visit_payload["status"] == "active"
    assert visit_payload["identifier"] == [{"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}]
    assert visit_payload["groupIdentifier"] == {"system": "urn:vulcan-soa:promotion", "value": "pd-1#E1:proposal"}
    assert visit_payload["instantiatesUri"] == ["PlanDefinition/E1-USDM"]
    assert visit_payload["code"] == {"concept": {"text": "Screening 1"}}
    assert visit_payload["subject"] == {"reference": "Patient/p-1"}

    activity_payload = json.loads(create_route.calls[1].request.content)
    assert activity_payload["identifier"] == [
        {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1#act-consent"}
    ]
    assert activity_payload["basedOn"] == [{"reference": "ServiceRequest/sr-visit"}]
    assert activity_payload["instantiatesUri"] == ["ActivityDefinition/act-consent"]
    assert activity_payload["code"] == {"concept": CONSENT_AD["code"]}


@respx.mock
async def test_materialize_proposal_without_definition_uri_creates_only_visit_request():
    create_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-visit"})
    )

    node = VisitNode(action_id="screening-1", title="Screening", transitions=())
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await materialize_proposal(client, "p-1", "pd-1", node)
    await client.close()

    assert create_route.call_count == 1
    payload = json.loads(create_route.calls[0].request.content)
    assert "instantiatesUri" not in payload


SUBJECT = {
    "resourceType": "ResearchSubject",
    "id": "subj-1",
    "status": "active",
    "study": {"reference": "ResearchStudy/study-1"},
    "subject": {"reference": "Patient/p-1"},
}
STUDY = {
    "resourceType": "ResearchStudy",
    "id": "study-1",
    "protocol": [{"reference": "PlanDefinition/pd-1"}],
}
PROTOCOL_PD = {
    "resourceType": "PlanDefinition",
    "id": "pd-1",
    "action": [{"id": "E1", "title": "Screening 1"}],
}
VISIT_TAG = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
ACTIVITY_TAG = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1#act-consent"}


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


def _mock_subject_reads():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/pd-1").mock(
        return_value=httpx.Response(200, json=PROTOCOL_PD)
    )


def _mock_empty_searches(*resource_types: str):
    for resource_type in resource_types:
        respx.get(f"http://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json=_bundle())
        )


@respx.mock
async def test_promote_to_plan_creates_new_requests_and_completes_predecessors():
    _mock_subject_reads()
    visit_proposal = {
        "resourceType": "ServiceRequest", "id": "sr-visit-proposal", "intent": "proposal",
        "status": "active", "subject": {"reference": "Patient/p-1"},
        "identifier": [VISIT_TAG], "meta": {"versionId": "1"},
        "instantiatesUri": ["PlanDefinition/E1-USDM"], "code": {"concept": {"text": "Screening 1"}},
    }
    activity_proposal = {
        "resourceType": "ServiceRequest", "id": "sr-act-proposal", "intent": "proposal",
        "status": "active", "subject": {"reference": "Patient/p-1"},
        "identifier": [ACTIVITY_TAG], "meta": {"versionId": "1"},
        "instantiatesUri": ["ActivityDefinition/act-consent"],
        "code": {"concept": {"text": "Informed Consent"}},
    }
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(visit_proposal, activity_proposal))
    )
    _mock_empty_searches("Appointment", "Encounter", "Task")
    create_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        side_effect=[
            httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-visit-plan"}),
            httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-act-plan"}),
        ]
    )
    update_visit = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-proposal").mock(
        return_value=httpx.Response(200, json=dict(visit_proposal, status="completed"))
    )
    update_activity = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-act-proposal").mock(
        return_value=httpx.Response(200, json=dict(activity_proposal, status="completed"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await promote(client, "subj-1", "E1", "plan")
    await client.close()

    visit_payload = json.loads(create_route.calls[0].request.content)
    assert visit_payload["intent"] == "plan"
    assert visit_payload["basedOn"] == [{"reference": "ServiceRequest/sr-visit-proposal"}]
    assert visit_payload["identifier"] == [VISIT_TAG]
    assert visit_payload["groupIdentifier"] == {"system": "urn:vulcan-soa:promotion", "value": "pd-1#E1:plan"}

    activity_payload = json.loads(create_route.calls[1].request.content)
    assert activity_payload["intent"] == "plan"
    assert activity_payload["basedOn"] == [
        {"reference": "ServiceRequest/sr-act-proposal"},
        {"reference": "ServiceRequest/sr-visit-plan"},
    ]

    assert json.loads(update_visit.calls.last.request.content)["status"] == "completed"
    assert json.loads(update_activity.calls.last.request.content)["status"] == "completed"
    assert "visits" in result


@respx.mock
async def test_promote_to_order_from_proposed_phase_raises_phase_error():
    _mock_subject_reads()
    visit_proposal = {
        "resourceType": "ServiceRequest", "id": "sr-1", "intent": "proposal",
        "status": "active", "subject": {"reference": "Patient/p-1"}, "identifier": [VISIT_TAG],
    }
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(visit_proposal))
    )
    _mock_empty_searches("Appointment", "Encounter", "Task")

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(PhaseError):
        await promote(client, "subj-1", "E1", "order")
    await client.close()


@respx.mock
async def test_promote_unknown_action_raises_value_error():
    _mock_subject_reads()
    _mock_empty_searches("ServiceRequest", "Appointment", "Encounter", "Task")

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(ValueError):
        await promote(client, "subj-1", "E1", "plan")
    await client.close()
