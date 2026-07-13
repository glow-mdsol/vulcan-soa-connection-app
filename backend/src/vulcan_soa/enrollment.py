import datetime

from vulcan_soa.activity_flow import if_match_header, materialize_proposal
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import (
    PLAN_DEFINITION_TAG_SYSTEM,
    load_protocol_graph,
    schedule_response,
)
from vulcan_soa.soa_engine.conditions import SubjectContext
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.tracking import RESEARCH_SUBJECT_STATES

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"
SUBJECT_ID_SYSTEM = "urn:vulcan-soa:subject-id"


class EnrollmentConflict(Exception):
    """The requested subject identifier cannot be assigned."""


def subject_identifier_of(subject: dict) -> str | None:
    for entry in subject.get("identifier", []):
        if entry.get("system") == SUBJECT_ID_SYSTEM:
            return entry.get("value")
    return None


def subject_summary(subject: dict) -> dict:
    return {
        "researchSubjectId": subject["id"],
        "subjectIdentifier": subject_identifier_of(subject),
        "patientId": subject.get("subject", {}).get("reference", "").split("/", 1)[-1],
        "status": subject.get("status"),
    }


def _today() -> str:
    return datetime.date.today().isoformat()


async def enroll(
    client: FhirClient,
    study_id: str,
    patient_id: str,
    subject_identifier: str,
    plan_definition_id: str | None = None,
) -> dict:
    graph, plan_definition_id = await load_protocol_graph(client, study_id, plan_definition_id)

    taken = await client.search(
        "ResearchSubject",
        {
            "identifier": f"{SUBJECT_ID_SYSTEM}|{subject_identifier}",
            "study": f"ResearchStudy/{study_id}",
        },
    )
    for match in taken:
        if match.get("subject", {}).get("reference") != f"Patient/{patient_id}":
            raise EnrollmentConflict(
                f"subject identifier '{subject_identifier}' is already in use in this study"
            )

    # R6 ResearchSubject:
    #   - status (1..1) is bound to PublicationStatus: "active" | "draft" | "retired" | "unknown"
    #   - subjectState (0..*) is a BackboneElement array: {code: CodeableConcept, startDate: dateTime}
    subject_resource = {
        "resourceType": "ResearchSubject",
        "status": "active",
        "identifier": [
            {"system": SUBJECT_ID_SYSTEM, "value": subject_identifier},
            {"system": PLAN_DEFINITION_TAG_SYSTEM, "value": plan_definition_id},
        ],
        "subjectState": [
            {
                "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "candidate"}]},
                "startDate": _today(),
            },
            {
                "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "eligible"}]},
                "startDate": _today(),
            }
        ],
        "study": {"reference": f"ResearchStudy/{study_id}"},
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    created = await client.conditional_create(
        "ResearchSubject",
        subject_resource,
        {"study": f"ResearchStudy/{study_id}", "subject": f"Patient/{patient_id}"},
    )

    existing_value = subject_identifier_of(created)
    if existing_value != subject_identifier:
        if existing_value is not None:
            raise EnrollmentConflict(
                f"this patient is already enrolled as '{existing_value}'"
            )
        created.setdefault("identifier", []).append(
            {"system": SUBJECT_ID_SYSTEM, "value": subject_identifier}
        )
        created = await client.update(
            "ResearchSubject", created["id"], created, if_match=if_match_header(created)
        )

    initial_context = SubjectContext(
        withdrawn=False, visited_action_ids=frozenset(), completed_action_ids=frozenset()
    )
    initial_state = resolve_schedule_state(graph, initial_context)
    for step in initial_state.next_steps:
        node = graph.nodes[step.action_id]
        await materialize_proposal(client, patient_id, plan_definition_id, node)

    materialized_ids = frozenset(step.action_id for step in initial_state.next_steps)
    post_enroll_state = resolve_schedule_state(
        graph,
        SubjectContext(
            withdrawn=False, visited_action_ids=materialized_ids, completed_action_ids=frozenset()
        ),
    )

    visits = {step.action_id: {"phase": "proposed"} for step in initial_state.next_steps}
    return {
        "researchSubjectId": created["id"],
        "schedule": schedule_response(post_enroll_state, graph, visits=visits),
    }


async def assign_subject_identifier(
    client: FhirClient, subject_id: str, subject_identifier: str
) -> dict:
    subject = await client.read("ResearchSubject", subject_id)

    existing = subject_identifier_of(subject)
    if existing == subject_identifier:
        return subject_summary(subject)
    if existing is not None:
        raise EnrollmentConflict(f"this subject already has identifier '{existing}'")

    taken = await client.search(
        "ResearchSubject",
        {
            "identifier": f"{SUBJECT_ID_SYSTEM}|{subject_identifier}",
            "study": subject.get("study", {}).get("reference", ""),
        },
    )
    for match in taken:
        if match["id"] != subject_id:
            raise EnrollmentConflict(
                f"subject identifier '{subject_identifier}' is already in use in this study"
            )

    subject.setdefault("identifier", []).append(
        {"system": SUBJECT_ID_SYSTEM, "value": subject_identifier}
    )
    updated = await client.update(
        "ResearchSubject", subject_id, subject, if_match=if_match_header(subject)
    )
    return subject_summary(updated)


async def update_subject_state(
    client: FhirClient, study_id: str, subject_id: str, new_state: str
) -> dict:
    """
    Append a new subjectState entry (THO research-subject-state) to a ResearchSubject.
    """
    if new_state not in RESEARCH_SUBJECT_STATES:
        raise ValueError(f"Invalid research subject state: {new_state}")

    subject = await client.read("ResearchSubject", subject_id)
    if subject.get("study", {}).get("reference") != f"ResearchStudy/{study_id}":
        raise ValueError(
            f"ResearchSubject with id {subject_id} does not belong to study {study_id}"
        )

    existing_states = subject.get("subjectState", [])
    subject["subjectState"] = existing_states + [
        {
            "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": new_state}]},
            "startDate": _today(),
        }
    ]
    return await client.update(
        "ResearchSubject", subject_id, subject, if_match=if_match_header(subject)
    )