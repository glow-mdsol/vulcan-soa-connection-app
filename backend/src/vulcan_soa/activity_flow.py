"""CPG activity-flow lifecycle: proposal → plan → order → schedule/book → perform → complete.

Each phase of a visit is a distinct FHIR resource linked by basedOn, per the CPG
activity flow (https://hl7.org/fhir/uv/cpg/activityflow.html). Chain membership is
tracked by the shared action-tag identifier on every resource in the chain.
"""

from dataclasses import dataclass, field

from vulcan_soa.soa_engine.conditions import SubjectContext

ACTION_TAG_SYSTEM = "urn:vulcan-soa:plan-action"
GROUP_ID_SYSTEM = "urn:vulcan-soa:promotion"
SITE_PRACTITIONER_ID = "site-coordinator-demo"

_PARTICIPANT_ROLES = {"Patient": "patient", "Practitioner": "site"}


class PhaseError(Exception):
    """A lifecycle gate was attempted from the wrong phase."""


def visit_tag(plan_definition_id: str, action_id: str) -> dict:
    return {"system": ACTION_TAG_SYSTEM, "value": f"{plan_definition_id}#{action_id}"}


def activity_tag(plan_definition_id: str, action_id: str, activity_id: str) -> dict:
    return {"system": ACTION_TAG_SYSTEM, "value": f"{plan_definition_id}#{action_id}#{activity_id}"}


def group_identifier(plan_definition_id: str, action_id: str, intent: str) -> dict:
    return {"system": GROUP_ID_SYSTEM, "value": f"{plan_definition_id}#{action_id}:{intent}"}


def parse_tag(value: str, plan_definition_id: str) -> tuple[str, str | None] | None:
    prefix = f"{plan_definition_id}#"
    if not value.startswith(prefix):
        return None
    action_id, _, activity_id = value[len(prefix):].partition("#")
    return action_id, activity_id or None


def tag_value(resource: dict) -> str | None:
    for identifier in resource.get("identifier", []):
        if identifier.get("system") == ACTION_TAG_SYSTEM:
            return identifier.get("value")
    return None


def if_match_header(resource: dict) -> str | None:
    version_id = resource.get("meta", {}).get("versionId")
    return f'W/"{version_id}"' if version_id else None


@dataclass
class VisitChain:
    action_id: str
    requests: dict[str, dict] = field(default_factory=dict)
    activities: dict[str, dict[str, dict]] = field(default_factory=dict)
    appointment: dict | None = None
    encounter: dict | None = None
    tasks: list[dict] = field(default_factory=list)

    @property
    def phase(self) -> str:
        if self.encounter is not None and self.encounter.get("status") == "completed":
            return "completed"
        if self.encounter is not None:
            return "performing"
        if self.appointment is not None and self.appointment.get("status") == "booked":
            return "booked"
        if self.appointment is not None:
            return "scheduled"
        if "order" in self.requests:
            return "ordered"
        if "plan" in self.requests:
            return "planned"
        return "proposed"


def context_from_chains(research_subject: dict, chains: dict[str, VisitChain]) -> SubjectContext:
    return SubjectContext(
        withdrawn=research_subject.get("status") == "retired",
        visited_action_ids=frozenset(chains),
        completed_action_ids=frozenset(
            action_id for action_id, chain in chains.items() if chain.phase == "completed"
        ),
    )


def visit_details(chains: dict[str, VisitChain]) -> dict[str, dict]:
    details: dict[str, dict] = {}
    for action_id, chain in chains.items():
        detail: dict = {"phase": chain.phase}
        if chain.appointment is not None:
            detail["participants"] = [
                {
                    "role": _PARTICIPANT_ROLES.get(
                        participant.get("actor", {}).get("reference", "").split("/", 1)[0], "other"
                    ),
                    "status": participant.get("status", "needs-action"),
                }
                for participant in chain.appointment.get("participant", [])
            ]
        if chain.tasks:
            detail["tasks"] = [
                {
                    "id": task["id"],
                    "description": task.get("description", ""),
                    "status": task.get("status", ""),
                }
                for task in chain.tasks
            ]
        details[action_id] = detail
    return details
