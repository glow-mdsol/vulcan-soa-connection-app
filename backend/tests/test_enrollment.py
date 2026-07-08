import json

import httpx
import pytest
import respx

from vulcan_soa.enrollment import EnrollmentConflict, enroll, subject_identifier_of
from vulcan_soa.fhir_client import FhirClient

STUDY = {
    "resourceType": "ResearchStudy",
    "id": "uc1-demo-research-study",
    "protocol": [{"reference": "PlanDefinition/plan-1"}],
}
PLAN_DEFINITION = {
    "resourceType": "PlanDefinition",
    "id": "plan-1",
    "action": [{"id": "screening-1", "title": "Screening"}],
}


def _mock_protocol():
    respx.get("http://aidbox.test/fhir/ResearchStudy/uc1-demo-research-study").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )


def _subject_bundle(*resources):
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


@respx.mock
async def test_enroll_creates_subject_and_materializes_root_visit():
    _mock_protocol()
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    create_subject_route = respx.post("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            201,
            json={
                "resourceType": "ResearchSubject",
                "id": "subj-1",
                "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
            },
        )
    )
    create_service_request_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()

    assert result["researchSubjectId"] == "subj-1"
    assert result["schedule"]["nextSteps"] == []  # the root visit is materialized, not "next"
    assert result["schedule"]["visits"] == {"screening-1": {"phase": "proposed"}}
    assert create_subject_route.called
    assert create_service_request_route.called
    proposal_payload = json.loads(create_service_request_route.calls.last.request.content)
    assert proposal_payload["intent"] == "proposal"
    assert proposal_payload["identifier"] == [
        {"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}
    ]
    subject_payload = json.loads(create_subject_route.calls.last.request.content)
    assert subject_payload["identifier"] == [
        {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}
    ]


@respx.mock
async def test_enroll_is_idempotent_via_conditional_create():
    _mock_protocol()
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json=_subject_bundle(
                {
                    "resourceType": "ResearchSubject",
                    "id": "subj-existing",
                    "subject": {"reference": "Patient/patient-1"},
                    "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
                }
            ),
        )
    )
    create_subject_route = respx.post("http://aidbox.test/fhir/ResearchSubject")
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()

    assert result["researchSubjectId"] == "subj-existing"
    assert not create_subject_route.called


@respx.mock
async def test_enroll_conflicts_when_identifier_taken_by_another_patient():
    _mock_protocol()
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json=_subject_bundle(
                {
                    "resourceType": "ResearchSubject",
                    "id": "subj-other",
                    "subject": {"reference": "Patient/someone-else"},
                    "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
                }
            ),
        )
    )
    create_route = respx.post("http://aidbox.test/fhir/ResearchSubject")

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(EnrollmentConflict):
        await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()
    assert not create_route.called


@respx.mock
async def test_reenroll_same_patient_same_identifier_is_idempotent(monkeypatch):
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-existing",
        "subject": {"reference": "Patient/patient-1"},
        "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/ResearchSubject/subj-existing")

    # Spy on the reconciliation's identifier lookup so this test fails (not just
    # vacuously passes) if the post-conditional-create reconciliation is removed.
    reconciled_subjects: list[dict] = []

    def spy_subject_identifier_of(subject: dict) -> str | None:
        reconciled_subjects.append(subject)
        return subject_identifier_of(subject)

    monkeypatch.setattr(
        "vulcan_soa.enrollment.subject_identifier_of", spy_subject_identifier_of
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-001")
    await client.close()

    assert result["researchSubjectId"] == "subj-existing"
    assert not update_route.called
    # Positive proof the no-op path ran: reconciliation examined the existing
    # subject and saw the matching identifier (hence no update, no conflict).
    assert any(
        subject.get("id") == "subj-existing" and subject_identifier_of(subject) == "SUBJ-001"
        for subject in reconciled_subjects
    ), "reconciliation never examined the existing subject's identifier"


@respx.mock
async def test_reenroll_same_patient_different_identifier_conflicts():
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-existing",
        "subject": {"reference": "Patient/patient-1"},
        "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-001"}],
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(EnrollmentConflict):
        await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-002")
    await client.close()


@respx.mock
async def test_legacy_subject_without_identifier_gains_one_via_update():
    _mock_protocol()
    existing = {
        "resourceType": "ResearchSubject",
        "id": "subj-legacy",
        "meta": {"versionId": "3"},
        "subject": {"reference": "Patient/patient-1"},
    }
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json=_subject_bundle(existing))
    )
    update_route = respx.put("http://aidbox.test/fhir/ResearchSubject/subj-legacy").mock(
        return_value=httpx.Response(
            200,
            json={**existing, "identifier": [{"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-009"}]},
        )
    )
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1", "SUBJ-009")
    await client.close()

    assert result["researchSubjectId"] == "subj-legacy"
    assert update_route.called
    update_payload = json.loads(update_route.calls.last.request.content)
    assert update_payload["identifier"] == [
        {"system": "urn:vulcan-soa:subject-id", "value": "SUBJ-009"}
    ]
    assert update_route.calls.last.request.headers["If-Match"] == 'W/"3"'
