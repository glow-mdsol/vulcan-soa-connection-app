import datetime

from vulcan_soa.activity_flow import revoke_open_workflow
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"


def _today() -> str:
    return datetime.date.today().isoformat()


def _if_match(resource: dict) -> str | None:
    version_id = resource.get("meta", {}).get("versionId")
    return f'W/"{version_id}"' if version_id else None


async def withdraw_subject(client: FhirClient, subject_id: str) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    _, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]

    existing_states = subject.get("subjectState", [])
    subject["status"] = "retired"
    subject["subjectState"] = existing_states + [
        {
            "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "off-study"}]},
            "startDate": _today(),
        }
    ]
    updated = await client.update(
        "ResearchSubject", subject_id, subject, if_match=_if_match(subject)
    )
    await revoke_open_workflow(client, patient_id, plan_definition_id)
    return {"id": updated["id"], "subjectState": "withdrawn"}
