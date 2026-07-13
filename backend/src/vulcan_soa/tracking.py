import datetime
import logging


from vulcan_soa.activity_flow import revoke_open_workflow
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"
# THO 7.2.0 ValueSet/research-subject-state (code system v1.0.1)
RESEARCH_SUBJECT_STATES = frozenset(
    {
        "candidate",
        "eligible",
        "follow-up",
        "ineligible",
        "not-registered",
        "off-study",
        "on-study",
        "on-study-intervention",
        "on-study-observation",
        "pending-on-study",
        "potential-candidate",
        "screening",
        "withdrawn",
    }
)
# NCI Thesaurus — milestone codes come from the CDISC protocol milestone list
MILESTONE_SYSTEM = "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl"


def _today() -> str:
    return datetime.date.today().isoformat()


def _if_match(resource: dict) -> str | None:
    version_id = resource.get("meta", {}).get("versionId")
    return f'W/"{version_id}"' if version_id else None


def subject_state_of(subject: dict) -> str | None:
    states = subject.get("subjectState", [])
    if not states:
        return None
    codings = states[-1].get("code", {}).get("coding", [])
    for coding in codings:
        if coding.get("system") == RESEARCH_SUBJECT_STATE_SYSTEM:
            return coding.get("code")
    return codings[0].get("code") if codings else None


def milestones_of(subject: dict) -> list[dict]:
    entries = []
    for entry in subject.get("subjectMilestone", []):
        codings = entry.get("milestone", {}).get("coding", [])
        code = codings[0].get("code") if codings else None
        if code:
            entries.append(
                {
                    "milestone": code,
                    "display": codings[0].get("display"),
                    "date": entry.get("date"),
                }
            )
    return entries


async def record_milestone(
    client: FhirClient,
    subject_id: str,
    milestone: str,
    date: str | None = None,
    display: str | None = None,
) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    existing = subject.get("subjectMilestone", [])
    coding = {"system": MILESTONE_SYSTEM, "code": milestone}
    if display:
        coding["display"] = display
    logger.info("Setting milestone %s for ResearchSubject/%s: %s", milestone, subject_id, date)
    if existing: 
        logger.info("Existing milestones: %s", [e.get("milestone", {}).get("coding", [{}])[0].get("code") for e in existing])
    # R6 ResearchSubject.subjectMilestone: {milestone: CodeableConcept (1..1), date: dateTime}
    subject["subjectMilestone"] = existing + [
        {
            "milestone": {"coding": [coding]},
            "date": date or _today(),
        }
    ]
    updated = await client.update(
        "ResearchSubject", subject_id, subject, if_match=_if_match(subject)
    )
    return {"researchSubjectId": updated["id"], "milestones": milestones_of(updated)}


async def withdraw_subject(client: FhirClient, subject_id: str) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    _, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]

    existing_states = subject.get("subjectState", [])
    subject["status"] = "retired"
    subject["subjectState"] = existing_states + [
        {
            "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "withdrawn"}]},
            "startDate": _today(),
        }
    ]
    updated = await client.update(
        "ResearchSubject", subject_id, subject, if_match=_if_match(subject)
    )
    await revoke_open_workflow(client, patient_id, plan_definition_id)
    return {"id": updated["id"], "subjectState": "withdrawn"}


async def delete_enrollment(client: FhirClient, subject_id: str) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    _, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]

    await revoke_open_workflow(client, patient_id, plan_definition_id)
    await client.delete("ResearchSubject", subject_id)
    return {"id": subject_id, "deleted": True}
