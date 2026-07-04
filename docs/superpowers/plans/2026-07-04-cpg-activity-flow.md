# CPG Activity Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the CPG activity lifecycle (`proposal → plan → order → schedule/book → perform → complete`) for study visits and their in-visit activities, with Appointment/AppointmentResponse engagement and Task checklists, per `docs/superpowers/specs/2026-07-04-cpg-activity-flow-design.md`.

**Architecture:** A new backend module `activity_flow.py` owns the request lifecycle: each phase is a **new** FHIR resource (`ServiceRequest` per intent, then `Appointment`, then `Encounter` + `Task`s, then `Procedure`s), linked by `basedOn` and all carrying the existing action-tag identifier. The SoA engine still decides *which* visit comes next; `activity_flow` decides *how* it progresses. The BFF exposes one endpoint per lifecycle gate; the SPA renders a phase stepper per visit.

**Tech Stack:** Python 3.11+/FastAPI/httpx/respx backend (raw FHIR dicts, no typed models), React 18/TypeScript/Vitest frontend, Aidbox FHIR R6 ballot3, Playwright e2e.

## Global Constraints

- FHIR R6 ballot3 shapes: `ServiceRequest.code` is a **CodeableReference** (`{"concept": {...}}`); `Encounter.status` has no `finished` (use `completed`); Encounter `class` is a list of CodeableConcepts.
- Action-tag identifier system is `urn:vulcan-soa:plan-action` (existing). Visit tag value: `<pdId>#<actionId>`. Activity tag value: `<pdId>#<actionId>#<activityAdId>`. The tag goes on every chain resource.
- Group identifier system: `urn:vulcan-soa:promotion`, value `<pdId>#<actionId>:<intent>`.
- Only `definitionUri` values starting `ActivityDefinition/` become in-visit activities. `Questionnaire/...` refs and actions without `definitionUri` are skipped (CPG collect-information is out of scope).
- Site staff participant is `Practitioner/site-coordinator-demo` (constant `SITE_PRACTITIONER_ID`).
- Backend tests run from `backend/`: `source .venv/bin/activate && pytest <path> -v` (or `task backend:test` for all). Frontend: `cd frontend && npx vitest run <path>`.
- All new backend code uses the existing style: module-level async functions taking `client: FhirClient` first, raw dicts in/out, `If-Match` on updates via `meta.versionId`.
- Commit after every task (git identity already configured; end commit messages with the Claude co-author line used in this repo).

**Verification baseline before starting:** `cd backend && source .venv/bin/activate && pytest -q` → 84 passed, 1 skipped. `cd frontend && npx vitest run` → 21 passed.

---

### Task 1: Graph parser — dual extension bases and `definitionUri`

The WIP PhUSE IG uses extension URLs under `http://example.org/br-and-r/soa/StructureDefinition/` instead of the published `http://hl7.org/fhir/uv/vulcan-schedule/StructureDefinition/`. Visit actions also carry `definitionUri` pointing at their visit-level PlanDefinition.

**Files:**
- Modify: `backend/src/vulcan_soa/soa_engine/graph.py`
- Test: `backend/tests/soa_engine/test_graph.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `VisitNode` gains field `definition_uri: str | None = None`. `graph.py` exports `SOA_EXTENSION_BASES: tuple[str, ...]`. `_find_extension(extensions, name)` now takes the bare extension *name* (`"soaTransition"`), not a full URL.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/soa_engine/test_graph.py`:

```python
def test_parses_transitions_with_brandr_extension_base():
    plan_definition = {
        "resourceType": "PlanDefinition",
        "id": "usdm-plan",
        "action": [
            {
                "id": "E1",
                "title": "Screening 1",
                "definitionUri": "PlanDefinition/H2Q-MC-LZZT-E1-USDM",
                "action": [
                    {
                        "extension": [
                            {
                                "url": "http://example.org/br-and-r/soa/StructureDefinition/soaTransition",
                                "extension": [
                                    {"url": "soaTargetId", "valueString": "E2"},
                                    {"url": "soaTransitionType", "valueString": "SS"},
                                ],
                            }
                        ]
                    }
                ],
            },
            {"id": "E2", "title": "Screening 2", "definitionUri": "PlanDefinition/H2Q-MC-LZZT-E2-USDM"},
        ],
    }

    graph = parse_protocol_graph(plan_definition)

    assert graph.root_ids == ("E1",)
    assert graph.nodes["E1"].transitions[0].target_id == "E2"
    assert graph.nodes["E1"].definition_uri == "PlanDefinition/H2Q-MC-LZZT-E1-USDM"


def test_definition_uri_defaults_to_none():
    plan_definition = {
        "resourceType": "PlanDefinition",
        "id": "plan-1",
        "action": [{"id": "screening-1", "title": "Screening"}],
    }

    graph = parse_protocol_graph(plan_definition)

    assert graph.nodes["screening-1"].definition_uri is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source .venv/bin/activate && pytest tests/soa_engine/test_graph.py -v`
Expected: the two new tests FAIL (`AttributeError: 'VisitNode' object has no attribute 'definition_uri'` / transition not found); existing tests still pass.

- [ ] **Step 3: Implement**

In `backend/src/vulcan_soa/soa_engine/graph.py`, replace the two URL constants with:

```python
SOA_EXTENSION_BASES = (
    "http://hl7.org/fhir/uv/vulcan-schedule/StructureDefinition/",
    "http://example.org/br-and-r/soa/StructureDefinition/",
)
```

Change `_find_extension` to match by extension name under any base:

```python
def _find_extension(extensions: list[dict], name: str) -> dict | None:
    for ext in extensions:
        url = ext.get("url", "")
        for base in SOA_EXTENSION_BASES:
            if url == base + name:
                return ext
    return None
```

Update the call site in `_parse_transition` (it currently passes `SOA_TRANSITION_URL`):

```python
    soa_transition = _find_extension(transition_action.get("extension", []), "soaTransition")
```

Delete the now-unused `SOA_TIMEPOINT_URL`/`SOA_TRANSITION_URL` constants (grep for other usages first: `grep -rn "SOA_TRANSITION_URL\|SOA_TIMEPOINT_URL" backend/`; update any to the new form).

Add `definition_uri` to `VisitNode` and `_parse_node`:

```python
@dataclass(frozen=True)
class VisitNode:
    action_id: str
    title: str
    transitions: tuple[Transition, ...]
    definition_uri: str | None = None
```

```python
def _parse_node(action: dict) -> VisitNode:
    transitions = tuple(_parse_transition(child) for child in action.get("action", []))
    return VisitNode(
        action_id=action["id"],
        title=action.get("title", action["id"]),
        transitions=transitions,
        definition_uri=action.get("definitionUri"),
    )
```

- [ ] **Step 4: Run the full backend suite**

Run: `pytest -q`
Expected: all pass (any test importing the deleted URL constants must be updated to use `SOA_EXTENSION_BASES[0] + "soaTransition"` style).

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/soa_engine/graph.py backend/tests/soa_engine/test_graph.py
git commit -m "Accept br-and-r extension base and parse definitionUri into VisitNode"
```

---

### Task 2: Chain model — tags, phase derivation, context, schedule payload shape

Pure functions and the `VisitChain` dataclass in a new `activity_flow.py`, plus the `visits` field on `schedule_response`.

**Files:**
- Create: `backend/src/vulcan_soa/activity_flow.py`
- Modify: `backend/src/vulcan_soa/scheduling.py` (extend `schedule_response`)
- Test: `backend/tests/test_activity_flow_chains.py`

**Interfaces:**
- Consumes: `SubjectContext` from `soa_engine.conditions`, `ScheduleState` from `soa_engine.engine`.
- Produces (used by every later task):
  - `ACTION_TAG_SYSTEM = "urn:vulcan-soa:plan-action"`, `GROUP_ID_SYSTEM = "urn:vulcan-soa:promotion"`, `SITE_PRACTITIONER_ID = "site-coordinator-demo"`
  - `visit_tag(plan_definition_id, action_id) -> dict`, `activity_tag(plan_definition_id, action_id, activity_id) -> dict`, `group_identifier(plan_definition_id, action_id, intent) -> dict`
  - `parse_tag(value, plan_definition_id) -> tuple[str, str | None] | None`
  - `class PhaseError(Exception)`
  - `@dataclass VisitChain` with fields `action_id: str`, `requests: dict[str, dict]` (intent → visit SR), `activities: dict[str, dict[str, dict]]` (activity id → intent → SR), `appointment: dict | None`, `encounter: dict | None`, `tasks: list[dict]`, and property `phase -> str` returning one of `proposed|planned|ordered|scheduled|booked|performing|completed`
  - `context_from_chains(research_subject, chains) -> SubjectContext`
  - `visit_details(chains) -> dict[str, dict]`
  - `if_match_header(resource) -> str | None`
  - `schedule_response(state, visits=None)` (in `scheduling.py`) now returns a `"visits"` key.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_activity_flow_chains.py`:

```python
from vulcan_soa.activity_flow import (
    VisitChain,
    activity_tag,
    context_from_chains,
    group_identifier,
    parse_tag,
    visit_details,
    visit_tag,
)
from vulcan_soa.scheduling import schedule_response
from vulcan_soa.soa_engine.engine import ScheduleState


def test_tag_helpers_produce_identifier_dicts():
    assert visit_tag("pd-1", "E1") == {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
    assert activity_tag("pd-1", "E1", "act-1") == {
        "system": "urn:vulcan-soa:plan-action",
        "value": "pd-1#E1#act-1",
    }
    assert group_identifier("pd-1", "E1", "plan") == {
        "system": "urn:vulcan-soa:promotion",
        "value": "pd-1#E1:plan",
    }


def test_parse_tag_splits_action_and_activity():
    assert parse_tag("pd-1#E1", "pd-1") == ("E1", None)
    assert parse_tag("pd-1#E1#act-1", "pd-1") == ("E1", "act-1")
    assert parse_tag("other-pd#E1", "pd-1") is None


def test_phase_derivation_walks_the_lifecycle():
    chain = VisitChain(action_id="E1")
    assert chain.phase == "proposed"

    chain.requests["plan"] = {"resourceType": "ServiceRequest", "intent": "plan"}
    assert chain.phase == "planned"

    chain.requests["order"] = {"resourceType": "ServiceRequest", "intent": "order"}
    assert chain.phase == "ordered"

    chain.appointment = {"resourceType": "Appointment", "status": "proposed"}
    assert chain.phase == "scheduled"

    chain.appointment["status"] = "booked"
    assert chain.phase == "booked"

    chain.encounter = {"resourceType": "Encounter", "status": "in-progress"}
    assert chain.phase == "performing"

    chain.encounter["status"] = "completed"
    assert chain.phase == "completed"


def test_context_from_chains_derives_visited_and_completed():
    chains = {
        "E1": VisitChain(action_id="E1", encounter={"status": "completed"}),
        "E2": VisitChain(action_id="E2", requests={"proposal": {}}),
    }
    subject = {"resourceType": "ResearchSubject", "status": "active"}

    context = context_from_chains(subject, chains)

    assert context.visited_action_ids == frozenset({"E1", "E2"})
    assert context.completed_action_ids == frozenset({"E1"})
    assert context.withdrawn is False

    retired = context_from_chains({"status": "retired"}, chains)
    assert retired.withdrawn is True


def test_visit_details_reports_phase_participants_and_tasks():
    chain = VisitChain(
        action_id="E1",
        requests={"proposal": {}, "plan": {}, "order": {}},
        appointment={
            "status": "proposed",
            "participant": [
                {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
                {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
            ],
        },
        tasks=[{"id": "t-1", "description": "Vital signs", "status": "ready"}],
    )

    details = visit_details({"E1": chain})

    assert details["E1"]["phase"] == "scheduled"
    assert details["E1"]["participants"] == [
        {"role": "patient", "status": "accepted"},
        {"role": "site", "status": "needs-action"},
    ]
    assert details["E1"]["tasks"] == [{"id": "t-1", "description": "Vital signs", "status": "ready"}]


def test_schedule_response_includes_visits():
    state = ScheduleState(
        completed_action_ids=frozenset(), current_action_ids=frozenset(), next_steps=()
    )
    assert schedule_response(state)["visits"] == {}
    assert schedule_response(state, visits={"E1": {"phase": "proposed"}})["visits"] == {
        "E1": {"phase": "proposed"}
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_activity_flow_chains.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vulcan_soa.activity_flow'`.

- [ ] **Step 3: Implement**

Create `backend/src/vulcan_soa/activity_flow.py`:

```python
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
```

In `backend/src/vulcan_soa/scheduling.py`, change `schedule_response`:

```python
def schedule_response(state: ScheduleState, visits: dict[str, dict] | None = None) -> dict:
    return {
        "completed": sorted(state.completed_action_ids),
        "current": sorted(state.current_action_ids),
        "nextSteps": [
            {"actionId": s.action_id, "title": s.title, "transitionType": s.transition_type}
            for s in state.next_steps
        ],
        "ambiguous": len(state.next_steps) > 1,
        "visits": visits or {},
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_chains.py -v && pytest -q`
Expected: new tests PASS. Any existing test asserting the exact `schedule_response` dict (e.g. in `tests/test_scheduling.py`, `tests/api/`) needs `"visits": {}` added to its expected payload — update those assertions.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/src/vulcan_soa/scheduling.py backend/tests
git commit -m "Add activity_flow chain model with phase derivation and visits payload"
```

---

### Task 3: `load_chains` — one pass over tagged resources

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_chains.py` (append)

**Interfaces:**
- Consumes: `FhirClient.search`.
- Produces: `async load_chains(client, patient_id, plan_definition_id) -> dict[str, VisitChain]`. Search strategy: `ServiceRequest` and `Encounter` by `subject=Patient/{id}` + `identifier={system}|`; `Appointment` and `Task` by `identifier={system}|` only, filtered client-side to this patient (their patient linkage lives in `participant.actor` / `for`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_activity_flow_chains.py`:

```python
import httpx
import respx

from vulcan_soa.activity_flow import load_chains
from vulcan_soa.fhir_client import FhirClient


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


@respx.mock
async def test_load_chains_groups_resources_by_action_and_activity():
    tag = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
    activity = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1#act-1"}
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "ServiceRequest", "id": "sr-1", "intent": "proposal",
                 "status": "completed", "identifier": [tag]},
                {"resourceType": "ServiceRequest", "id": "sr-2", "intent": "plan",
                 "status": "active", "identifier": [tag]},
                {"resourceType": "ServiceRequest", "id": "sr-3", "intent": "proposal",
                 "status": "active", "identifier": [activity]},
                {"resourceType": "ServiceRequest", "id": "sr-x", "intent": "proposal",
                 "status": "active",
                 "identifier": [{"system": "urn:vulcan-soa:plan-action", "value": "other-pd#Z"}]},
            ),
        )
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "Appointment", "id": "appt-1", "status": "proposed",
                 "identifier": [tag],
                 "participant": [{"actor": {"reference": "Patient/p-1"}, "status": "needs-action"}]},
                {"resourceType": "Appointment", "id": "appt-other", "status": "proposed",
                 "identifier": [tag],
                 "participant": [{"actor": {"reference": "Patient/p-2"}, "status": "needs-action"}]},
            ),
        )
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "Task", "id": "t-1", "status": "ready",
                 "for": {"reference": "Patient/p-1"}, "identifier": [activity]},
                {"resourceType": "Task", "id": "t-other", "status": "ready",
                 "for": {"reference": "Patient/p-2"}, "identifier": [activity]},
            ),
        )
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    chains = await load_chains(client, "p-1", "pd-1")
    await client.close()

    assert set(chains) == {"E1"}
    chain = chains["E1"]
    assert chain.requests["proposal"]["id"] == "sr-1"
    assert chain.requests["plan"]["id"] == "sr-2"
    assert chain.activities["act-1"]["proposal"]["id"] == "sr-3"
    assert chain.appointment["id"] == "appt-1"
    assert [t["id"] for t in chain.tasks] == ["t-1"]
    assert chain.phase == "planned"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_chains.py -v`
Expected: FAIL with `ImportError: cannot import name 'load_chains'`.

- [ ] **Step 3: Implement**

Append to `backend/src/vulcan_soa/activity_flow.py` (add `from vulcan_soa.fhir_client import FhirClient` to imports):

```python
async def load_chains(
    client: FhirClient, patient_id: str, plan_definition_id: str
) -> dict[str, VisitChain]:
    chains: dict[str, VisitChain] = {}
    patient_reference = f"Patient/{patient_id}"

    def chain_for(action_id: str) -> VisitChain:
        if action_id not in chains:
            chains[action_id] = VisitChain(action_id=action_id)
        return chains[action_id]

    def parsed_tag(resource: dict) -> tuple[str, str | None] | None:
        return parse_tag(tag_value(resource) or "", plan_definition_id)

    tagged = {"identifier": f"{ACTION_TAG_SYSTEM}|"}

    for request in await client.search("ServiceRequest", {"subject": patient_reference, **tagged}):
        parsed = parsed_tag(request)
        if parsed is None:
            continue
        action_id, activity_id = parsed
        chain = chain_for(action_id)
        if activity_id is None:
            chain.requests[request.get("intent", "")] = request
        else:
            chain.activities.setdefault(activity_id, {})[request.get("intent", "")] = request

    # Appointment and Task have no subject search param on all servers; filter client-side.
    for appointment in await client.search("Appointment", tagged):
        parsed = parsed_tag(appointment)
        if parsed is None:
            continue
        actors = [p.get("actor", {}).get("reference") for p in appointment.get("participant", [])]
        if patient_reference not in actors:
            continue
        chain_for(parsed[0]).appointment = appointment

    for encounter in await client.search("Encounter", {"subject": patient_reference, **tagged}):
        parsed = parsed_tag(encounter)
        if parsed is None:
            continue
        chain_for(parsed[0]).encounter = encounter

    for task in await client.search("Task", tagged):
        parsed = parsed_tag(task)
        if parsed is None:
            continue
        if task.get("for", {}).get("reference") != patient_reference:
            continue
        chain_for(parsed[0]).tasks.append(task)

    return chains
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_chains.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_chains.py
git commit -m "Add load_chains grouping tagged workflow resources per visit"
```

---

### Task 4: `materialize_proposal` — visit + activity proposals

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_requests.py` (create)

**Interfaces:**
- Consumes: `VisitNode` (with `definition_uri`) from Task 1, tag helpers from Task 2.
- Produces: `async materialize_proposal(client, patient_id, plan_definition_id, node) -> dict` (returns the created visit-level ServiceRequest). Creates: one visit SR (`intent=proposal`, `status=active`, `code.concept.text` = node title, `instantiatesUri=[node.definition_uri]` when present) and one activity SR per `ActivityDefinition/` ref in the visit PlanDefinition (`basedOn` the visit SR, `code.concept` from `ActivityDefinition.code`, `instantiatesUri=["ActivityDefinition/<id>"]`). All share the proposal `groupIdentifier`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_activity_flow_requests.py`:

```python
import json

import httpx
import respx

from vulcan_soa.activity_flow import materialize_proposal
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_requests.py -v`
Expected: FAIL with `ImportError: cannot import name 'materialize_proposal'`.

- [ ] **Step 3: Implement**

Append to `activity_flow.py` (add `from vulcan_soa.soa_engine.graph import VisitNode` to imports):

```python
async def materialize_proposal(
    client: FhirClient, patient_id: str, plan_definition_id: str, node: VisitNode
) -> dict:
    group = group_identifier(plan_definition_id, node.action_id, "proposal")
    visit_request = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": "proposal",
        "subject": {"reference": f"Patient/{patient_id}"},
        "identifier": [visit_tag(plan_definition_id, node.action_id)],
        "groupIdentifier": group,
        "code": {"concept": {"text": node.title}},
    }
    if node.definition_uri:
        visit_request["instantiatesUri"] = [node.definition_uri]
    created_visit = await client.create("ServiceRequest", visit_request)

    for definition in await _load_activity_definitions(client, node):
        activity_request = {
            "resourceType": "ServiceRequest",
            "status": "active",
            "intent": "proposal",
            "subject": {"reference": f"Patient/{patient_id}"},
            "identifier": [activity_tag(plan_definition_id, node.action_id, definition["id"])],
            "groupIdentifier": group,
            "instantiatesUri": [f"ActivityDefinition/{definition['id']}"],
            "basedOn": [{"reference": f"ServiceRequest/{created_visit['id']}"}],
            "code": {"concept": definition.get("code") or {"text": definition.get("title", definition["id"])}},
        }
        await client.create("ServiceRequest", activity_request)
    return created_visit


async def _load_activity_definitions(client: FhirClient, node: VisitNode) -> list[dict]:
    if not node.definition_uri or not node.definition_uri.startswith("PlanDefinition/"):
        return []
    visit_pd = await client.read("PlanDefinition", node.definition_uri.split("/", 1)[1])
    definitions = []
    for action in visit_pd.get("action", []):
        uri = action.get("definitionUri", "")
        # Only ActivityDefinition-backed activities; Questionnaire refs are out of scope.
        if uri.startswith("ActivityDefinition/"):
            definitions.append(await client.read("ActivityDefinition", uri.split("/", 1)[1]))
    return definitions
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_requests.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_requests.py
git commit -m "Add materialize_proposal creating visit and activity proposal requests"
```

---

### Task 5: `promote` — proposal→plan and plan→order with cascade and guards

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_requests.py` (append)

**Interfaces:**
- Consumes: `load_chains`, `if_match_header`, `visit_details`, `context_from_chains`; `load_protocol_graph_for_subject` and `schedule_response` from `scheduling.py`; `resolve_schedule_state` from the engine.
- Produces:
  - `async promote(client, subject_id, action_id, to_intent) -> dict` where `to_intent ∈ {"plan","order"}`; returns the refreshed schedule payload dict.
  - Internal helpers reused by Tasks 6–9: `@dataclass _SubjectWorkspace(subject, graph, plan_definition_id, patient_id, chains)`, `async _load_workspace(client, subject_id) -> _SubjectWorkspace`, `_require_phase(chain, action_id, expected) -> VisitChain` (raises `ValueError` if chain is None, `PhaseError` on phase mismatch), `async _complete_request(client, request)`, `async schedule_payload(client, workspace) -> dict` (reloads chains, recomputes state, returns `schedule_response(state, visits=visit_details(chains))`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_activity_flow_requests.py`:

```python
import pytest

from vulcan_soa.activity_flow import PhaseError, promote

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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_requests.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'promote'`.

- [ ] **Step 3: Implement**

Append to `activity_flow.py` (extend imports):

```python
from dataclasses import dataclass, field  # already present; shown for context

from vulcan_soa.scheduling import load_protocol_graph_for_subject, schedule_response
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.soa_engine.graph import ProtocolGraph, VisitNode
```

```python
_PROMOTIONS = {"plan": ("proposed", "proposal"), "order": ("planned", "plan")}


@dataclass
class _SubjectWorkspace:
    subject: dict
    graph: ProtocolGraph
    plan_definition_id: str
    patient_id: str
    chains: dict[str, VisitChain]


async def _load_workspace(client: FhirClient, subject_id: str) -> _SubjectWorkspace:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]
    chains = await load_chains(client, patient_id, plan_definition_id)
    return _SubjectWorkspace(subject, graph, plan_definition_id, patient_id, chains)


def _require_phase(chain: VisitChain | None, action_id: str, expected: str) -> VisitChain:
    if chain is None:
        raise ValueError(f"No materialized visit found for action {action_id}")
    if chain.phase != expected:
        raise PhaseError(f"visit {action_id} is in phase '{chain.phase}', expected '{expected}'")
    return chain


async def _complete_request(client: FhirClient, request: dict) -> None:
    request["status"] = "completed"
    await client.update("ServiceRequest", request["id"], request, if_match=if_match_header(request))


async def schedule_payload(client: FhirClient, workspace: _SubjectWorkspace) -> dict:
    chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    state = resolve_schedule_state(workspace.graph, context_from_chains(workspace.subject, chains))
    return schedule_response(state, visits=visit_details(chains))


def _next_request(previous: dict, intent: str, group: dict, based_on: list[dict]) -> dict:
    request = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": intent,
        "subject": previous["subject"],
        "identifier": previous["identifier"],
        "groupIdentifier": group,
        "basedOn": [{"reference": f"ServiceRequest/{r['id']}"} for r in based_on],
        "code": previous.get("code"),
    }
    if previous.get("instantiatesUri"):
        request["instantiatesUri"] = previous["instantiatesUri"]
    return request


async def promote(client: FhirClient, subject_id: str, action_id: str, to_intent: str) -> dict:
    required_phase, previous_intent = _PROMOTIONS[to_intent]
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, required_phase)

    group = group_identifier(workspace.plan_definition_id, action_id, to_intent)
    previous_visit = chain.requests[previous_intent]
    created_visit = await client.create(
        "ServiceRequest", _next_request(previous_visit, to_intent, group, based_on=[previous_visit])
    )
    await _complete_request(client, previous_visit)

    for by_intent in chain.activities.values():
        previous_activity = by_intent.get(previous_intent)
        if previous_activity is None:
            continue
        await client.create(
            "ServiceRequest",
            _next_request(previous_activity, to_intent, group, based_on=[previous_activity, created_visit]),
        )
        await _complete_request(client, previous_activity)

    return await schedule_payload(client, workspace)
```

Note: `load_protocol_graph_for_subject` and `schedule_response` are imported from `scheduling.py`, which does **not** import `activity_flow` — no cycle.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_requests.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_requests.py
git commit -m "Add promote with activity cascade, predecessor completion, and phase guards"
```

---

### Task 6: `schedule_visit` and `respond` — Appointment and AppointmentResponse

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_appointments.py` (create)

**Interfaces:**
- Consumes: workspace helpers from Task 5.
- Produces:
  - `async schedule_visit(client, subject_id, action_id) -> dict` — requires phase `ordered`; creates Appointment (`status=proposed`, `basedOn` order, tag identifier, two participants with `status: needs-action`).
  - `async respond(client, subject_id, action_id, participant, response) -> dict` — `participant ∈ {"patient","site"}`, `response ∈ {"accepted","declined"}`; requires phase `scheduled`; creates AppointmentResponse, updates the participant status on the Appointment, sets Appointment `status=booked` when every participant is `accepted`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_activity_flow_appointments.py`:

```python
import json

import httpx
import respx

from vulcan_soa.activity_flow import respond, schedule_visit
from vulcan_soa.fhir_client import FhirClient

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
ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [VISIT_TAG],
    "code": {"concept": {"text": "Screening 1"}},
}
PROPOSAL = dict(ORDER, id="sr-proposal", intent="proposal", status="completed")
PLAN = dict(ORDER, id="sr-plan", intent="plan", status="completed")


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
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(PROPOSAL, PLAN, ORDER))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )


@respx.mock
async def test_schedule_visit_creates_proposed_appointment_with_participants():
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    create_route = respx.post("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(201, json={"resourceType": "Appointment", "id": "appt-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await schedule_visit(client, "subj-1", "E1")
    await client.close()

    payload = json.loads(create_route.calls.last.request.content)
    assert payload["status"] == "proposed"
    assert payload["basedOn"] == [{"reference": "ServiceRequest/sr-order"}]
    assert payload["identifier"] == [VISIT_TAG]
    assert payload["participant"] == [
        {"actor": {"reference": "Patient/p-1"}, "status": "needs-action"},
        {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
    ]


@respx.mock
async def test_respond_accepts_participant_and_books_when_all_accepted():
    _mock_subject_reads()
    appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG], "meta": {"versionId": "3"},
        "participant": [
            {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
            {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
        ],
    }
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(appointment))
    )
    response_route = respx.post("http://aidbox.test/fhir/AppointmentResponse").mock(
        return_value=httpx.Response(201, json={"resourceType": "AppointmentResponse", "id": "ar-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=dict(appointment, status="booked"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await respond(client, "subj-1", "E1", "site", "accepted")
    await client.close()

    response_payload = json.loads(response_route.calls.last.request.content)
    assert response_payload["appointment"] == {"reference": "Appointment/appt-1"}
    assert response_payload["actor"] == {"reference": "Practitioner/site-coordinator-demo"}
    assert response_payload["participantStatus"] == "accepted"

    appointment_payload = json.loads(update_route.calls.last.request.content)
    assert appointment_payload["status"] == "booked"
    assert appointment_payload["participant"][1]["status"] == "accepted"
    assert update_route.calls.last.request.headers["If-Match"] == 'W/"3"'


@respx.mock
async def test_respond_declined_keeps_appointment_proposed():
    _mock_subject_reads()
    appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG],
        "participant": [
            {"actor": {"reference": "Patient/p-1"}, "status": "needs-action"},
            {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
        ],
    }
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(appointment))
    )
    respx.post("http://aidbox.test/fhir/AppointmentResponse").mock(
        return_value=httpx.Response(201, json={"resourceType": "AppointmentResponse", "id": "ar-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=appointment)
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await respond(client, "subj-1", "E1", "patient", "declined")
    await client.close()

    payload = json.loads(update_route.calls.last.request.content)
    assert payload["status"] == "proposed"
    assert payload["participant"][0]["status"] == "declined"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_appointments.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `activity_flow.py`:

```python
async def schedule_visit(client: FhirClient, subject_id: str, action_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "ordered")
    order = chain.requests["order"]
    await client.create(
        "Appointment",
        {
            "resourceType": "Appointment",
            "status": "proposed",
            "identifier": [visit_tag(workspace.plan_definition_id, action_id)],
            "basedOn": [{"reference": f"ServiceRequest/{order['id']}"}],
            "participant": [
                {"actor": {"reference": f"Patient/{workspace.patient_id}"}, "status": "needs-action"},
                {"actor": {"reference": f"Practitioner/{SITE_PRACTITIONER_ID}"}, "status": "needs-action"},
            ],
        },
    )
    return await schedule_payload(client, workspace)


async def respond(
    client: FhirClient, subject_id: str, action_id: str, participant: str, response: str
) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "scheduled")
    appointment = chain.appointment
    actor_reference = (
        f"Patient/{workspace.patient_id}"
        if participant == "patient"
        else f"Practitioner/{SITE_PRACTITIONER_ID}"
    )
    await client.create(
        "AppointmentResponse",
        {
            "resourceType": "AppointmentResponse",
            "appointment": {"reference": f"Appointment/{appointment['id']}"},
            "actor": {"reference": actor_reference},
            "participantStatus": response,
        },
    )
    for slot in appointment.get("participant", []):
        if slot.get("actor", {}).get("reference") == actor_reference:
            slot["status"] = response
    if all(slot.get("status") == "accepted" for slot in appointment.get("participant", [])):
        appointment["status"] = "booked"
    await client.update(
        "Appointment", appointment["id"], appointment, if_match=if_match_header(appointment)
    )
    return await schedule_payload(client, workspace)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_appointments.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_appointments.py
git commit -m "Add appointment scheduling and participant responses with booking"
```

---

### Task 7: `perform` — Encounter plus a Task per activity order

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_events.py` (create)

**Interfaces:**
- Consumes: workspace helpers; chain with a booked Appointment and activity orders.
- Produces: `async perform(client, subject_id, action_id) -> dict` — requires phase `booked`; creates Encounter (`status=in-progress`, `class` AMB, `appointment` ref, `basedOn` order, visit tag) and one Task per activity order (`status=ready`, `intent=order`, activity tag, `basedOn`+`focus` → activity order SR, `for` → Patient, `encounter` → new Encounter, `description` from the SR's `code.concept` text/display).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_activity_flow_events.py`:

```python
import json

import httpx
import respx

from vulcan_soa.activity_flow import perform
from vulcan_soa.fhir_client import FhirClient

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
VISIT_ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-visit-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [VISIT_TAG],
    "code": {"concept": {"text": "Screening 1"}},
}
ACTIVITY_ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-act-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [ACTIVITY_TAG],
    "code": {"concept": {"coding": [{"display": "Informed Consent"}]}},
}
BOOKED_APPOINTMENT = {
    "resourceType": "Appointment", "id": "appt-1", "status": "booked",
    "identifier": [VISIT_TAG],
    "participant": [
        {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
        {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "accepted"},
    ],
}


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


@respx.mock
async def test_perform_creates_encounter_and_ready_tasks():
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER, ACTIVITY_ORDER))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    encounter_route = respx.post("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "enc-1"})
    )
    task_route = respx.post("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(201, json={"resourceType": "Task", "id": "t-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await perform(client, "subj-1", "E1")
    await client.close()

    encounter_payload = json.loads(encounter_route.calls.last.request.content)
    assert encounter_payload["status"] == "in-progress"
    assert encounter_payload["appointment"] == [{"reference": "Appointment/appt-1"}]
    assert encounter_payload["basedOn"] == [{"reference": "ServiceRequest/sr-visit-order"}]
    assert encounter_payload["identifier"] == [VISIT_TAG]

    task_payload = json.loads(task_route.calls.last.request.content)
    assert task_payload["status"] == "ready"
    assert task_payload["intent"] == "order"
    assert task_payload["identifier"] == [ACTIVITY_TAG]
    assert task_payload["basedOn"] == [{"reference": "ServiceRequest/sr-act-order"}]
    assert task_payload["focus"] == {"reference": "ServiceRequest/sr-act-order"}
    assert task_payload["for"] == {"reference": "Patient/p-1"}
    assert task_payload["encounter"] == {"reference": "Encounter/enc-1"}
    assert task_payload["description"] == "Informed Consent"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_events.py -v`
Expected: FAIL with `ImportError: cannot import name 'perform'`.

- [ ] **Step 3: Implement**

Append to `activity_flow.py`:

```python
def _request_text(request: dict) -> str:
    concept = request.get("code", {}).get("concept", {})
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return tag_value(request) or ""


async def perform(client: FhirClient, subject_id: str, action_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "booked")
    order = chain.requests["order"]
    created_encounter = await client.create(
        "Encounter",
        {
            "resourceType": "Encounter",
            "status": "in-progress",
            "class": [
                {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}]}
            ],
            "subject": {"reference": f"Patient/{workspace.patient_id}"},
            "appointment": [{"reference": f"Appointment/{chain.appointment['id']}"}],
            "basedOn": [{"reference": f"ServiceRequest/{order['id']}"}],
            "identifier": [visit_tag(workspace.plan_definition_id, action_id)],
        },
    )

    for activity_id, by_intent in chain.activities.items():
        activity_order = by_intent.get("order")
        if activity_order is None:
            continue
        await client.create(
            "Task",
            {
                "resourceType": "Task",
                "status": "ready",
                "intent": "order",
                "identifier": [activity_tag(workspace.plan_definition_id, action_id, activity_id)],
                "basedOn": [{"reference": f"ServiceRequest/{activity_order['id']}"}],
                "focus": {"reference": f"ServiceRequest/{activity_order['id']}"},
                "for": {"reference": f"Patient/{workspace.patient_id}"},
                "encounter": {"reference": f"Encounter/{created_encounter['id']}"},
                "description": _request_text(activity_order),
            },
        )
    return await schedule_payload(client, workspace)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_events.py
git commit -m "Add perform creating the encounter and per-activity ready tasks"
```

---

### Task 8: `complete_task` and `complete` — Procedures, sweep, next proposal

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`
- Test: `backend/tests/test_activity_flow_events.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `async complete_task(client, subject_id, action_id, task_id) -> dict` — requires phase `performing`; raises `ValueError` for unknown task id; completes the Task and writes its Procedure (`status=completed`, `code` from the activity order's `code.concept`, `basedOn` the activity order, `encounter` from the Task, same activity tag), referenced from `Task.output`.
  - `async complete(client, subject_id, action_id, transition_choice) -> dict` — requires phase `performing`; sweeps remaining Tasks (skipping `completed`/`cancelled`), completes all still-`active` chain ServiceRequests, completes the Encounter, re-reads the subject, resolves schedule state, materializes the next proposal (single next step, or `transition_choice` when ambiguous), and returns `schedule_response(state, visits=...)` where `state` is the **pre-materialization** state (this keeps the ambiguous-decision UI contract from the old `complete_visit`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_activity_flow_events.py`:

```python
import pytest

from vulcan_soa.activity_flow import complete, complete_task

READY_TASK = {
    "resourceType": "Task", "id": "t-1", "status": "ready", "intent": "order",
    "identifier": [ACTIVITY_TAG], "meta": {"versionId": "1"},
    "basedOn": [{"reference": "ServiceRequest/sr-act-order"}],
    "focus": {"reference": "ServiceRequest/sr-act-order"},
    "for": {"reference": "Patient/p-1"},
    "encounter": {"reference": "Encounter/enc-1"},
    "description": "Informed Consent",
}
IN_PROGRESS_ENCOUNTER = {
    "resourceType": "Encounter", "id": "enc-1", "status": "in-progress",
    "meta": {"versionId": "2"}, "identifier": [VISIT_TAG],
    "subject": {"reference": "Patient/p-1"},
}


def _mock_performing_chain(*, tasks=(READY_TASK,)):
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER, ACTIVITY_ORDER))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER))
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle(*tasks))
    )


@respx.mock
async def test_complete_task_writes_procedure_and_completes_task():
    _mock_performing_chain()
    procedure_route = respx.post("http://aidbox.test/fhir/Procedure").mock(
        return_value=httpx.Response(201, json={"resourceType": "Procedure", "id": "proc-1"})
    )
    task_update = respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(READY_TASK, status="completed"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await complete_task(client, "subj-1", "E1", "t-1")
    await client.close()

    procedure_payload = json.loads(procedure_route.calls.last.request.content)
    assert procedure_payload["status"] == "completed"
    assert procedure_payload["code"] == {"coding": [{"display": "Informed Consent"}]}
    assert procedure_payload["subject"] == {"reference": "Patient/p-1"}
    assert procedure_payload["encounter"] == {"reference": "Encounter/enc-1"}
    assert procedure_payload["basedOn"] == [{"reference": "ServiceRequest/sr-act-order"}]
    assert procedure_payload["identifier"] == [ACTIVITY_TAG]

    task_payload = json.loads(task_update.calls.last.request.content)
    assert task_payload["status"] == "completed"
    assert task_payload["output"] == [
        {"type": {"text": "procedure"}, "valueReference": {"reference": "Procedure/proc-1"}}
    ]


@respx.mock
async def test_complete_task_unknown_id_raises_value_error():
    _mock_performing_chain()

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(ValueError):
        await complete_task(client, "subj-1", "E1", "t-missing")
    await client.close()


@respx.mock
async def test_complete_sweeps_tasks_completes_requests_and_encounter():
    _mock_performing_chain()
    procedure_route = respx.post("http://aidbox.test/fhir/Procedure").mock(
        return_value=httpx.Response(201, json={"resourceType": "Procedure", "id": "proc-1"})
    )
    respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(READY_TASK, status="completed"))
    )
    visit_order_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    activity_order_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-act-order").mock(
        return_value=httpx.Response(200, json=dict(ACTIVITY_ORDER, status="completed"))
    )
    encounter_update = respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await complete(client, "subj-1", "E1", None)
    await client.close()

    assert procedure_route.called
    assert json.loads(visit_order_update.calls.last.request.content)["status"] == "completed"
    assert json.loads(activity_order_update.calls.last.request.content)["status"] == "completed"
    assert json.loads(encounter_update.calls.last.request.content)["status"] == "completed"
    assert result["completed"] == ["E1"]
```

Note on the last assertion: `PROTOCOL_PD` has a single action `E1` with no transitions, so after completion there is no next step to materialize and `completed == ["E1"]` (the second `Encounter` search returns the stale in-progress encounter from the mock, so add a `side_effect` returning the completed encounter on the final search):

```python
    # replace the Encounter GET mock inside this test with:
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
        ]
    )
```

(`_mock_performing_chain()` still mocks the other resource types; call it first, then override the Encounter route as above.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_events.py -v`
Expected: new tests FAIL with `ImportError`.

- [ ] **Step 3: Implement**

Append to `activity_flow.py`:

```python
def _activity_order_for_task(chain: VisitChain, task: dict) -> dict:
    value = tag_value(task) or ""
    activity_id = value.rpartition("#")[2]
    return chain.activities.get(activity_id, {}).get("order", {})


async def _complete_task_resource(client: FhirClient, patient_id: str, chain: VisitChain, task: dict) -> None:
    if task.get("status") in ("completed", "cancelled"):
        return
    order = _activity_order_for_task(chain, task)
    procedure = {
        "resourceType": "Procedure",
        "status": "completed",
        "code": order.get("code", {}).get("concept") or {"text": task.get("description", "")},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": task.get("encounter"),
        "identifier": task.get("identifier", []),
    }
    if order.get("id"):
        procedure["basedOn"] = [{"reference": f"ServiceRequest/{order['id']}"}]
    created = await client.create("Procedure", procedure)
    task["status"] = "completed"
    task["output"] = [
        {"type": {"text": "procedure"}, "valueReference": {"reference": f"Procedure/{created['id']}"}}
    ]
    await client.update("Task", task["id"], task, if_match=if_match_header(task))


async def complete_task(client: FhirClient, subject_id: str, action_id: str, task_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "performing")
    task = next((t for t in chain.tasks if t["id"] == task_id), None)
    if task is None:
        raise ValueError(f"No task {task_id} found for action {action_id}")
    await _complete_task_resource(client, workspace.patient_id, chain, task)
    return await schedule_payload(client, workspace)


def _all_requests(chain: VisitChain) -> list[dict]:
    activity_requests = [
        request for by_intent in chain.activities.values() for request in by_intent.values()
    ]
    return [*chain.requests.values(), *activity_requests]


async def complete(
    client: FhirClient, subject_id: str, action_id: str, transition_choice: str | None
) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "performing")

    for task in chain.tasks:
        await _complete_task_resource(client, workspace.patient_id, chain, task)
    for request in _all_requests(chain):
        if request.get("status") == "active":
            await _complete_request(client, request)

    encounter = chain.encounter
    encounter["status"] = "completed"
    await client.update("Encounter", encounter["id"], encounter, if_match=if_match_header(encounter))

    # Re-read subject so we pick up any withdrawal that happened between visits.
    subject = await client.read("ResearchSubject", subject_id)
    chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    state = resolve_schedule_state(workspace.graph, context_from_chains(subject, chains))

    if len(state.next_steps) == 1:
        node = workspace.graph.nodes[state.next_steps[0].action_id]
        await materialize_proposal(client, workspace.patient_id, workspace.plan_definition_id, node)
    elif len(state.next_steps) > 1 and transition_choice is not None:
        chosen = next((s for s in state.next_steps if s.action_id == transition_choice), None)
        if chosen is not None:
            node = workspace.graph.nodes[chosen.action_id]
            await materialize_proposal(client, workspace.patient_id, workspace.plan_definition_id, node)

    final_chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    return schedule_response(state, visits=visit_details(final_chains))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_events.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/tests/test_activity_flow_events.py
git commit -m "Add task completion with procedures and visit completion with sweep"
```

---

### Task 9: Withdrawal revokes the open workflow

**Files:**
- Modify: `backend/src/vulcan_soa/activity_flow.py`, `backend/src/vulcan_soa/tracking.py`
- Test: `backend/tests/test_activity_flow_events.py` (append), `backend/tests/test_tracking.py` (update)

**Interfaces:**
- Consumes: `load_chains`, `if_match_header`.
- Produces: `async revoke_open_workflow(client, patient_id, plan_definition_id) -> None` — sets `active` ServiceRequests → `revoked`, `proposed`/`booked` Appointments → `cancelled`, `ready`/`in-progress` Tasks → `cancelled`. `tracking.withdraw_subject` calls it after retiring the subject (it must resolve `plan_definition_id` via `load_protocol_graph_for_subject` and `patient_id` from the subject reference **before** updating the subject).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_activity_flow_events.py`:

```python
from vulcan_soa.activity_flow import revoke_open_workflow


@respx.mock
async def test_revoke_open_workflow_revokes_and_cancels():
    active_order = dict(VISIT_ORDER, meta={"versionId": "1"})
    proposed_appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG], "meta": {"versionId": "1"},
        "participant": [{"actor": {"reference": "Patient/p-1"}, "status": "needs-action"}],
    }
    ready_task = dict(READY_TASK)
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(active_order))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(proposed_appointment))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle(ready_task))
    )
    request_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(active_order, status="revoked"))
    )
    appointment_update = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=dict(proposed_appointment, status="cancelled"))
    )
    task_update = respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(ready_task, status="cancelled"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await revoke_open_workflow(client, "p-1", "pd-1")
    await client.close()

    assert json.loads(request_update.calls.last.request.content)["status"] == "revoked"
    assert json.loads(appointment_update.calls.last.request.content)["status"] == "cancelled"
    assert json.loads(task_update.calls.last.request.content)["status"] == "cancelled"
```

In `backend/tests/test_tracking.py`, the withdraw test must now also mock the graph reads and the four chain searches (empty bundles) because `withdraw_subject` calls `revoke_open_workflow`. Add to `test_withdraw_subject_updates_subject_state` (reusing that file's existing `STUDY`/`PLAN_DEFINITION` constants):

```python
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    for resource_type in ("ServiceRequest", "Appointment", "Encounter", "Task"):
        respx.get(f"http://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json={"resourceType": "Bundle"})
        )
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_activity_flow_events.py tests/test_tracking.py -v`
Expected: new test FAILS with `ImportError`; tracking test may still pass until the implementation lands.

- [ ] **Step 3: Implement**

Append to `activity_flow.py`:

```python
async def revoke_open_workflow(client: FhirClient, patient_id: str, plan_definition_id: str) -> None:
    chains = await load_chains(client, patient_id, plan_definition_id)
    for chain in chains.values():
        for request in _all_requests(chain):
            if request.get("status") == "active":
                request["status"] = "revoked"
                await client.update(
                    "ServiceRequest", request["id"], request, if_match=if_match_header(request)
                )
        if chain.appointment is not None and chain.appointment.get("status") in ("proposed", "booked"):
            chain.appointment["status"] = "cancelled"
            await client.update(
                "Appointment",
                chain.appointment["id"],
                chain.appointment,
                if_match=if_match_header(chain.appointment),
            )
        for task in chain.tasks:
            if task.get("status") in ("ready", "in-progress"):
                task["status"] = "cancelled"
                await client.update("Task", task["id"], task, if_match=if_match_header(task))
```

In `backend/src/vulcan_soa/tracking.py`: delete `complete_visit` **later** (Task 11 rewires the route); for now only extend `withdraw_subject`:

```python
from vulcan_soa.activity_flow import revoke_open_workflow
from vulcan_soa.scheduling import load_protocol_graph_for_subject


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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_activity_flow_events.py tests/test_tracking.py -v && pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/activity_flow.py backend/src/vulcan_soa/tracking.py backend/tests
git commit -m "Revoke open requests and cancel appointments and tasks on withdrawal"
```

---

### Task 10: Rewire enrollment and retire the old materialization path

**Files:**
- Modify: `backend/src/vulcan_soa/enrollment.py`, `backend/src/vulcan_soa/scheduling.py`, `backend/src/vulcan_soa/tracking.py`
- Test: `backend/tests/test_enrollment.py`, `backend/tests/test_scheduling.py`, `backend/tests/test_tracking.py` (update)

**Interfaces:**
- Consumes: `materialize_proposal` from Task 4.
- Produces: `enroll()` materializes **proposals**; its response's `schedule.visits` is `{action_id: {"phase": "proposed"}}` for each materialized root. `scheduling.py` loses `materialize_visit`, `load_subject_context`, `tag_for`, `ACTION_TAG_SYSTEM` (all superseded by `activity_flow`); it keeps `load_protocol_graph`, `load_protocol_graph_for_subject`, `schedule_response`. `tracking.py` loses `complete_visit` (superseded by `activity_flow.complete`; the route flips in Task 11 — do both edits in that task if the route would otherwise break the app import graph; `tracking.complete_visit` is deleted here and the route import updated here to keep the suite green: change `api/research_subjects.py` to import `complete` from `activity_flow` and call `await complete(client, subject_id, action_id, body.transitionChoice)`).

- [ ] **Step 1: Update enrollment**

In `backend/src/vulcan_soa/enrollment.py`, replace the `materialize_visit` import with `from vulcan_soa.activity_flow import materialize_proposal`, replace the loop body call with `await materialize_proposal(client, patient_id, plan_definition_id, node)`, and change the return statement to:

```python
    visits = {step.action_id: {"phase": "proposed"} for step in initial_state.next_steps}
    return {
        "researchSubjectId": created["id"],
        "schedule": schedule_response(post_enroll_state, visits=visits),
    }
```

- [ ] **Step 2: Delete the superseded scheduling/tracking code**

- In `scheduling.py`: delete `ACTION_TAG_SYSTEM`, `tag_for`, `materialize_visit`, `load_subject_context` and the now-unused imports (`SubjectContext`, `VisitNode`).
- In `tracking.py`: delete `complete_visit` and its now-unused imports.
- In `api/research_subjects.py`: change the `complete_visit` import to `from vulcan_soa.activity_flow import complete` and the route body to `return await complete(client, subject_id, action_id, body.transitionChoice)`. The `get_schedule` route still imports `load_subject_context` — replace it now with the chain-based version (final form shown in Task 11 Step 3; apply it here).
- Run `grep -rn "materialize_visit\|load_subject_context\|tag_for" backend/` — the only remaining hits must be in tests, which the next step updates.

- [ ] **Step 3: Update the affected tests**

- `tests/test_enrollment.py`: enrollment now creates ServiceRequests, not Encounters — point the create-route mocks at `POST .../ServiceRequest` and assert the proposal payload (`intent == "proposal"`, identifier tag) instead of the Encounter payload; expected schedule gains `"visits": {...}`.
- `tests/test_scheduling.py`: delete tests for `materialize_visit`/`load_subject_context`; keep/adjust `load_protocol_graph` and `schedule_response` tests.
- `tests/test_tracking.py`: delete the two `complete_visit` tests (their behavior is now covered by `tests/test_activity_flow_events.py`).
- `tests/api/test_research_subjects.py`: the schedule/complete route tests must mock the chain searches (`ServiceRequest`/`Appointment`/`Encounter`/`Task`) instead of `load_subject_context`'s single Encounter search; assert the response includes `"visits"`.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "Enroll via proposals and retire the direct-encounter materialization path"
```

---

### Task 11: API — lifecycle routes with phase guards

**Files:**
- Modify: `backend/src/vulcan_soa/api/research_subjects.py`, `backend/src/vulcan_soa/api/models.py`
- Test: `backend/tests/api/test_research_subjects.py` (append)

**Interfaces:**
- Consumes: `promote`, `schedule_visit`, `respond`, `perform`, `complete_task`, `complete`, `load_chains`, `context_from_chains`, `visit_details`, `PhaseError` from `activity_flow`.
- Produces HTTP endpoints (all return the schedule payload):
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/plan`
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/order`
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/schedule`
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/respond` with body `{"participant": "patient"|"site", "response": "accepted"|"declined"}`
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/perform`
  - `POST /api/research-subjects/{subject_id}/visits/{action_id}/tasks/{task_id}/complete`
  - `PhaseError` → HTTP 409; `ValueError` → HTTP 404.
- New model in `api/models.py`:

```python
from typing import Literal


class RespondRequest(BaseModel):
    participant: Literal["patient", "site"]
    response: Literal["accepted", "declined"]
```

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/test_research_subjects.py`, following that file's existing app/client fixture pattern (reuse its session/dependency setup verbatim; only the route mocks differ). Two representative tests:

```python
async def test_plan_route_returns_conflict_on_phase_error(app_client, monkeypatch):
    async def raise_phase_error(client, subject_id, action_id, to_intent):
        raise PhaseError("visit E1 is in phase 'ordered', expected 'proposed'")

    monkeypatch.setattr("vulcan_soa.api.research_subjects.promote", raise_phase_error)

    response = await app_client.post("/api/research-subjects/subj-1/visits/E1/plan")

    assert response.status_code == 409
    assert "phase" in response.json()["detail"]


async def test_respond_route_validates_participant(app_client, monkeypatch):
    captured = {}

    async def fake_respond(client, subject_id, action_id, participant, resp):
        captured["args"] = (subject_id, action_id, participant, resp)
        return {"completed": [], "current": [], "nextSteps": [], "ambiguous": False, "visits": {}}

    monkeypatch.setattr("vulcan_soa.api.research_subjects.respond", fake_respond)

    ok = await app_client.post(
        "/api/research-subjects/subj-1/visits/E1/respond",
        json={"participant": "patient", "response": "accepted"},
    )
    assert ok.status_code == 200
    assert captured["args"] == ("subj-1", "E1", "patient", "accepted")

    bad = await app_client.post(
        "/api/research-subjects/subj-1/visits/E1/respond",
        json={"participant": "sponsor", "response": "accepted"},
    )
    assert bad.status_code == 422
```

(Adapt the fixture name to whatever `tests/api/test_research_subjects.py` actually uses — read that file first and mirror its setup. Import `PhaseError` from `vulcan_soa.activity_flow`.) Add equivalent monkeypatch-based happy-path tests for `order`, `schedule`, `perform`, and `tasks/{task_id}/complete`.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/api/test_research_subjects.py -v`
Expected: new tests FAIL (404 route not found).

- [ ] **Step 3: Implement**

Replace `backend/src/vulcan_soa/api/research_subjects.py` with:

```python
from typing import Awaitable

from fastapi import APIRouter, Depends, HTTPException

from vulcan_soa.activity_flow import (
    PhaseError,
    complete,
    complete_task,
    context_from_chains,
    load_chains,
    perform,
    promote,
    respond,
    schedule_visit,
    visit_details,
)
from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import CompleteVisitRequest, RespondRequest
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject, schedule_response
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.tracking import withdraw_subject

router = APIRouter(prefix="/api/research-subjects")


async def _guarded(coro: Awaitable[dict]) -> dict:
    try:
        return await coro
    except PhaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{subject_id}/schedule")
async def get_schedule(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]
    chains = await load_chains(client, patient_id, plan_definition_id)
    state = resolve_schedule_state(graph, context_from_chains(subject, chains))
    return schedule_response(state, visits=visit_details(chains))


@router.post("/{subject_id}/visits/{action_id}/plan")
async def plan_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(promote(client, subject_id, action_id, "plan"))


@router.post("/{subject_id}/visits/{action_id}/order")
async def order_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(promote(client, subject_id, action_id, "order"))


@router.post("/{subject_id}/visits/{action_id}/schedule")
async def schedule_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(schedule_visit(client, subject_id, action_id))


@router.post("/{subject_id}/visits/{action_id}/respond")
async def respond_route(
    subject_id: str,
    action_id: str,
    body: RespondRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await _guarded(respond(client, subject_id, action_id, body.participant, body.response))


@router.post("/{subject_id}/visits/{action_id}/perform")
async def perform_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(perform(client, subject_id, action_id))


@router.post("/{subject_id}/visits/{action_id}/tasks/{task_id}/complete")
async def complete_task_route(
    subject_id: str, action_id: str, task_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(complete_task(client, subject_id, action_id, task_id))


@router.post("/{subject_id}/visits/{action_id}/complete")
async def complete_visit_route(
    subject_id: str,
    action_id: str,
    body: CompleteVisitRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await _guarded(complete(client, subject_id, action_id, body.transitionChoice))


@router.post("/{subject_id}/withdraw")
async def withdraw_route(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    return await withdraw_subject(client, subject_id)
```

Add `RespondRequest` to `api/models.py` as shown in Interfaces.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/vulcan_soa/api backend/tests/api
git commit -m "Add lifecycle gate endpoints with 409 phase guards"
```

---

### Task 12: Fixtures — demo study, practitioner, WIP-IG loader, drift guard

**Files:**
- Create: `backend/fixtures/research_study_lzzt_usdm.json`, `backend/fixtures/practitioner_site_coordinator.json`, `backend/scripts/validate_protocol.py`
- Modify: `Taskfile.yml`
- Test: `backend/tests/test_validate_protocol.py` (create)

**Interfaces:**
- Produces: `ResearchStudy/lzzt-usdm-demo-study`, `Practitioner/site-coordinator-demo`, `python scripts/validate_protocol.py <protocol-pd-id>` (exit 1 with error lines on drift), Taskfile target `fixtures:load-soa-ig` with var `SOA_IG_RESOURCES_DIR`.

- [ ] **Step 1: Write the fixtures**

`backend/fixtures/research_study_lzzt_usdm.json`:

```json
{
  "resourceType": "ResearchStudy",
  "id": "lzzt-usdm-demo-study",
  "title": "LZZT USDM Demo Study (CPG Activity Flow)",
  "status": "active",
  "protocol": [
    {
      "reference": "PlanDefinition/H2Q-MC-LZZT-ProtocolDesign-USDM"
    }
  ]
}
```

`backend/fixtures/practitioner_site_coordinator.json`:

```json
{
  "resourceType": "Practitioner",
  "id": "site-coordinator-demo",
  "active": true,
  "name": [
    {
      "family": "Coordinator",
      "given": ["Site"],
      "prefix": ["Ms"]
    }
  ]
}
```

- [ ] **Step 2: Write the failing validator test**

Create `backend/tests/test_validate_protocol.py`:

```python
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
```

- [ ] **Step 3: Run to verify failure, then implement**

Run: `pytest tests/test_validate_protocol.py -v` → FAIL (`ModuleNotFoundError`).

Create `backend/scripts/validate_protocol.py`:

```python
"""Drift guard for the WIP SoA IG: fail loudly at load time, not mid-demo."""

import argparse
import asyncio
import sys

import httpx

from vulcan_soa.config import Settings
from vulcan_soa.fhir_client import FhirClient


async def validate(client: FhirClient, protocol_id: str) -> list[str]:
    errors: list[str] = []
    protocol = await client.read("PlanDefinition", protocol_id)
    for action in protocol.get("action", []):
        if not action.get("id"):
            errors.append(f"protocol action without id (title={action.get('title')!r})")
            continue
        uri = action.get("definitionUri", "")
        if not uri.startswith("PlanDefinition/"):
            continue
        try:
            visit_pd = await client.read("PlanDefinition", uri.split("/", 1)[1])
        except httpx.HTTPStatusError:
            errors.append(f"{action['id']}: unresolvable {uri}")
            continue
        for visit_action in visit_pd.get("action", []):
            definition_uri = visit_action.get("definitionUri", "")
            if not definition_uri.startswith("ActivityDefinition/"):
                continue
            try:
                await client.read("ActivityDefinition", definition_uri.split("/", 1)[1])
            except httpx.HTTPStatusError:
                errors.append(f"{uri}: unresolvable {definition_uri}")
    return errors


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol_id", help="PlanDefinition id of the protocol design")
    args = parser.parse_args()

    settings = Settings()
    client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    try:
        errors = await validate(client, args.protocol_id)
    finally:
        await client.close()

    for error in errors:
        print(f"DRIFT: {error}", file=sys.stderr)
    if errors:
        sys.exit(1)
    print(f"OK: {args.protocol_id} and its visit/activity definitions all resolve")


if __name__ == "__main__":
    asyncio.run(main())
```

Run: `pytest tests/test_validate_protocol.py -v` → PASS.

- [ ] **Step 4: Add the Taskfile target**

In `Taskfile.yml`, next to the existing fixture targets (the `vars:` block at the top gets `SOA_IG_RESOURCES_DIR: '{{.SOA_IG_RESOURCES_DIR | default (printf "%s/Documents/Devel/phuseorg/fhir-schedule-of-activities-ig/fsh-generated/resources" .HOME)}}'`):

```yaml
  fixtures:load-soa-ig:
    desc: Load the WIP PhUSE SoA IG (fsh-generated/resources) into Aidbox and validate the USDM protocol.
    dir: "{{.BACKEND_DIR}}"
    cmds:
      - |
        source .venv/bin/activate
        ENV_FILE={{.ENV_FILE}} python scripts/load_fixtures.py "{{.SOA_IG_RESOURCES_DIR}}"
        ENV_FILE={{.ENV_FILE}} python scripts/validate_protocol.py H2Q-MC-LZZT-ProtocolDesign-USDM
    preconditions:
      - sh: test -f .venv/bin/activate
        msg: "Run 'task backend:install' first"
      - sh: test -d "{{.SOA_IG_RESOURCES_DIR}}"
        msg: "Set SOA_IG_RESOURCES_DIR to the WIP IG's fsh-generated/resources directory"
```

Add `fixtures:load-soa-ig` to the `fixtures:load-all` task list (after `fixtures:load-ig`).

- [ ] **Step 5: Verify against live Aidbox and commit**

Run (requires Docker Aidbox up): `task fixtures:load-soa-ig && task fixtures:load-app`
Expected: loader prints `OK` lines; validator prints the final `OK: H2Q-MC-LZZT-ProtocolDesign-USDM ...` line. If the validator reports DRIFT lines, fix the WIP IG or record the gap — do not silence the guard.

```bash
git add backend/fixtures backend/scripts/validate_protocol.py backend/tests/test_validate_protocol.py Taskfile.yml
git commit -m "Add USDM demo fixtures, WIP-IG loader target, and protocol drift guard"
```

---

### Task 13: Frontend — types and API client

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`
- Test: existing test files that mock `Schedule` literals (`frontend/src/views/SubjectDashboard/SubjectDashboard.test.tsx`, `frontend/src/views/Enroll/Enroll.test.tsx` — grep for `ambiguous:` to find them all)

**Interfaces:**
- Produces (consumed by Task 14):

```ts
export type VisitPhase =
  | "proposed" | "planned" | "ordered" | "scheduled" | "booked" | "performing" | "completed";

export interface Participant {
  role: "patient" | "site" | "other";
  status: string;
}

export interface VisitTask {
  id: string;
  description: string;
  status: string;
}

export interface VisitDetail {
  phase: VisitPhase;
  participants?: Participant[];
  tasks?: VisitTask[];
}
```

`Schedule` gains `visits: Record<string, VisitDetail>`. New client functions, all returning `Promise<Schedule>`: `promoteVisit(subjectId, actionId, step: "plan" | "order")`, `scheduleVisit(subjectId, actionId)`, `respondToAppointment(subjectId, actionId, participant: "patient" | "site", response: "accepted" | "declined")`, `performVisit(subjectId, actionId)`, `completeTask(subjectId, actionId, taskId)`.

- [ ] **Step 1: Add the types and client functions**

Append the interfaces above to `frontend/src/api/types.ts` and add `visits: Record<string, VisitDetail>;` to `Schedule`. Append to `frontend/src/api/client.ts`:

```ts
export function promoteVisit(
  subjectId: string,
  actionId: string,
  step: "plan" | "order",
): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/${step}`, undefined);
}

export function scheduleVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/schedule`, undefined);
}

export function respondToAppointment(
  subjectId: string,
  actionId: string,
  participant: "patient" | "site",
  response: "accepted" | "declined",
): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/respond`, {
    participant,
    response,
  });
}

export function performVisit(subjectId: string, actionId: string): Promise<Schedule> {
  return postJson<Schedule>(`/api/research-subjects/${subjectId}/visits/${actionId}/perform`, undefined);
}

export function completeTask(subjectId: string, actionId: string, taskId: string): Promise<Schedule> {
  return postJson<Schedule>(
    `/api/research-subjects/${subjectId}/visits/${actionId}/tasks/${taskId}/complete`,
    undefined,
  );
}
```

(Import `Schedule` is already in scope; add `VisitDetail` etc. to the type re-exports if other modules need them.)

- [ ] **Step 2: Fix the type errors in existing tests**

Run: `cd frontend && npx tsc --noEmit`
Every mocked `Schedule` literal now needs `visits: {}`. Add it in `SubjectDashboard.test.tsx`, `Enroll.test.tsx`, and anywhere else `tsc` complains.

- [ ] **Step 3: Run the frontend suite**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all pass, no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api frontend/src
git commit -m "Add lifecycle client calls and visit-detail types"
```

---

### Task 14: Frontend — VisitCard with phase stepper, gates, and task checklist

**Files:**
- Create: `frontend/src/views/SubjectDashboard/VisitCard.tsx`
- Modify: `frontend/src/views/SubjectDashboard/SubjectDashboard.tsx`
- Test: `frontend/src/views/SubjectDashboard/SubjectDashboard.test.tsx` (append), `frontend/src/views/SubjectDashboard/VisitCard.test.tsx` (create)

**Interfaces:**
- Consumes: types/client from Task 13.
- Produces: `<VisitCard actionId detail onPlan onOrder onSchedule onRespond onPerform onCompleteTask onCompleteVisit />`.

- [ ] **Step 1: Write the failing VisitCard tests**

Create `frontend/src/views/SubjectDashboard/VisitCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VisitDetail } from "../../api/types";
import VisitCard from "./VisitCard";

function noopHandlers() {
  return {
    onPlan: vi.fn(),
    onOrder: vi.fn(),
    onSchedule: vi.fn(),
    onRespond: vi.fn(),
    onPerform: vi.fn(),
    onCompleteTask: vi.fn(),
    onCompleteVisit: vi.fn(),
  };
}

describe("VisitCard", () => {
  it("shows the gate button for the current phase and marks the stepper", () => {
    const handlers = noopHandlers();
    render(<VisitCard actionId="E1" detail={{ phase: "proposed" }} {...handlers} />);

    expect(screen.getByRole("button", { name: "Accept proposal" })).toBeInTheDocument();
    expect(screen.getByText("proposed")).toHaveAttribute("aria-current", "step");
  });

  it("shows participant responses while scheduled and disables an accepted participant", async () => {
    const handlers = noopHandlers();
    const detail: VisitDetail = {
      phase: "scheduled",
      participants: [
        { role: "patient", status: "accepted" },
        { role: "site", status: "needs-action" },
      ],
    };
    render(<VisitCard actionId="E1" detail={detail} {...handlers} />);

    expect(screen.getByRole("button", { name: "Patient accepts" })).toBeDisabled();
    const siteButton = screen.getByRole("button", { name: "Site confirms" });
    await userEvent.click(siteButton);
    expect(handlers.onRespond).toHaveBeenCalledWith("site");
  });

  it("renders the task checklist while performing with Complete visit always enabled", async () => {
    const handlers = noopHandlers();
    const detail: VisitDetail = {
      phase: "performing",
      tasks: [
        { id: "t-1", description: "Vital signs", status: "ready" },
        { id: "t-2", description: "Informed consent", status: "completed" },
      ],
    };
    render(<VisitCard actionId="E1" detail={detail} {...handlers} />);

    await userEvent.click(screen.getByRole("button", { name: "Done: Vital signs" }));
    expect(handlers.onCompleteTask).toHaveBeenCalledWith("t-1");
    expect(screen.queryByRole("button", { name: "Done: Informed consent" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Complete visit" }));
    expect(handlers.onCompleteVisit).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/views/SubjectDashboard/VisitCard.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement VisitCard**

Create `frontend/src/views/SubjectDashboard/VisitCard.tsx`:

```tsx
import type { VisitDetail } from "../../api/types";

const PHASES = ["proposed", "planned", "ordered", "scheduled", "booked", "performing", "completed"] as const;

interface VisitCardProps {
  actionId: string;
  detail: VisitDetail | undefined;
  onPlan: () => void;
  onOrder: () => void;
  onSchedule: () => void;
  onRespond: (participant: "patient" | "site") => void;
  onPerform: () => void;
  onCompleteTask: (taskId: string) => void;
  onCompleteVisit: () => void;
}

export default function VisitCard({
  actionId,
  detail,
  onPlan,
  onOrder,
  onSchedule,
  onRespond,
  onPerform,
  onCompleteTask,
  onCompleteVisit,
}: VisitCardProps) {
  const phase = detail?.phase ?? "proposed";
  const participantStatus = (role: "patient" | "site") =>
    detail?.participants?.find((p) => p.role === role)?.status;

  return (
    <li aria-label={`Visit ${actionId}`}>
      <strong>{actionId}</strong>
      <ol aria-label="Visit phases">
        {PHASES.map((p) => (
          <li key={p} aria-current={p === phase ? "step" : undefined}>
            {p}
          </li>
        ))}
      </ol>

      {phase === "proposed" && <button onClick={onPlan}>Accept proposal</button>}
      {phase === "planned" && <button onClick={onOrder}>Authorize</button>}
      {phase === "ordered" && <button onClick={onSchedule}>Schedule</button>}

      {phase === "scheduled" && (
        <div aria-label="Appointment responses">
          <button onClick={() => onRespond("patient")} disabled={participantStatus("patient") === "accepted"}>
            Patient accepts
          </button>
          <button onClick={() => onRespond("site")} disabled={participantStatus("site") === "accepted"}>
            Site confirms
          </button>
        </div>
      )}

      {phase === "booked" && <button onClick={onPerform}>Perform visit</button>}

      {phase === "performing" && (
        <div>
          <ul aria-label="Visit tasks">
            {detail?.tasks?.map((task) => (
              <li key={task.id}>
                {task.description} — {task.status}
                {task.status !== "completed" && task.status !== "cancelled" && (
                  <button onClick={() => onCompleteTask(task.id)}>Done: {task.description}</button>
                )}
              </li>
            ))}
          </ul>
          <button onClick={onCompleteVisit}>Complete visit</button>
        </div>
      )}
    </li>
  );
}
```

Run: `npx vitest run src/views/SubjectDashboard/VisitCard.test.tsx` → PASS.

- [ ] **Step 4: Wire VisitCard into SubjectDashboard**

In `SubjectDashboard.tsx`:
- Import the new client functions and `VisitCard`.
- Replace the `Current` section's `<li>` body with a `VisitCard`, passing `detail={schedule.visits[actionId]}` and handlers that call the client and `setSchedule(result)` (each handler mirrors `handleComplete`'s try/catch shape; `handleComplete` keeps its ambiguity logic and becomes the `onCompleteVisit` handler):

```tsx
  async function runGate(action: () => Promise<Schedule>, failure: string) {
    try {
      setSchedule(await action());
    } catch {
      setError(failure);
    }
  }
```

```tsx
        <ul>
          {schedule.current.map((actionId) => (
            <VisitCard
              key={actionId}
              actionId={actionId}
              detail={schedule.visits[actionId]}
              onPlan={() => runGate(() => promoteVisit(subjectId!, actionId, "plan"), "Could not accept the proposal.")}
              onOrder={() => runGate(() => promoteVisit(subjectId!, actionId, "order"), "Could not authorize the visit.")}
              onSchedule={() => runGate(() => scheduleVisit(subjectId!, actionId), "Could not schedule the visit.")}
              onRespond={(participant) =>
                runGate(
                  () => respondToAppointment(subjectId!, actionId, participant, "accepted"),
                  "Could not record the response.",
                )
              }
              onPerform={() => runGate(() => performVisit(subjectId!, actionId), "Could not start the visit.")}
              onCompleteTask={(taskId) =>
                runGate(() => completeTask(subjectId!, actionId, taskId), "Could not complete the task.")
              }
              onCompleteVisit={() => handleComplete(actionId)}
            />
          ))}
        </ul>
```

Existing dashboard tests use `"Mark complete"` — the visible completion button is now `"Complete visit"` and only appears in phase `performing`; update those tests' mocked schedules to include `visits: { "treatment-1": { phase: "performing", tasks: [] } }` (etc.) and the button name.

- [ ] **Step 5: Run the frontend suite and commit**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all pass.

```bash
git add frontend/src/views/SubjectDashboard
git commit -m "Render per-visit phase stepper with gates, responses, and task checklist"
```

---

### Task 15: Integration test, Playwright e2e, README

**Files:**
- Create: `backend/tests/test_cpg_flow_integration.py`
- Modify: `frontend/e2e/golden-path.spec.ts`, `README.md`

**Interfaces:** none new — this task proves the whole chain against live Aidbox.

- [ ] **Step 1: Write the integration test**

Create `backend/tests/test_cpg_flow_integration.py` (same gating pattern as `test_golden_path_integration.py`):

```python
import os
from pathlib import Path

import pytest

from scripts.load_fixtures import load_directory
from vulcan_soa.activity_flow import (
    complete,
    complete_task,
    load_chains,
    perform,
    promote,
    respond,
    schedule_visit,
)
from vulcan_soa.config import Settings
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient

SOA_IG_RESOURCES_DIR = Path(
    os.environ.get(
        "SOA_IG_RESOURCES_DIR",
        "/Users/GLW1/Documents/Devel/phuseorg/fhir-schedule-of-activities-ig/fsh-generated/resources",
    )
)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

STUDY_ID = "lzzt-usdm-demo-study"
PATIENT_ID = "uc1-demo-patient"
PROTOCOL_PD_ID = "H2Q-MC-LZZT-ProtocolDesign-USDM"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="requires a real local Aidbox with the WIP SoA IG loaded; set RUN_INTEGRATION_TESTS=1",
)


@pytest.fixture
async def client():
    settings = Settings()
    fhir_client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    await load_directory(fhir_client, SOA_IG_RESOURCES_DIR)
    await load_directory(fhir_client, FIXTURES_DIR)
    yield fhir_client
    await fhir_client.close()


async def test_cpg_lifecycle_for_first_usdm_visit(client):
    enroll_result = await enroll(client, STUDY_ID, PATIENT_ID)
    subject_id = enroll_result["researchSubjectId"]
    visits = enroll_result["schedule"]["visits"]
    assert visits, "enroll should materialize at least one proposal"
    action_id = next(iter(visits))
    assert visits[action_id]["phase"] == "proposed"

    after_plan = await promote(client, subject_id, action_id, "plan")
    assert after_plan["visits"][action_id]["phase"] == "planned"

    after_order = await promote(client, subject_id, action_id, "order")
    assert after_order["visits"][action_id]["phase"] == "ordered"

    after_schedule = await schedule_visit(client, subject_id, action_id)
    assert after_schedule["visits"][action_id]["phase"] == "scheduled"

    await respond(client, subject_id, action_id, "patient", "accepted")
    after_site = await respond(client, subject_id, action_id, "site", "accepted")
    assert after_site["visits"][action_id]["phase"] == "booked"

    after_perform = await perform(client, subject_id, action_id)
    detail = after_perform["visits"][action_id]
    assert detail["phase"] == "performing"
    assert detail["tasks"], "E1 should have activity tasks"

    first_task = detail["tasks"][0]
    after_task = await complete_task(client, subject_id, action_id, first_task["id"])
    ticked = [t for t in after_task["visits"][action_id]["tasks"] if t["id"] == first_task["id"]]
    assert ticked[0]["status"] == "completed"

    after_complete = await complete(client, subject_id, action_id, None)
    assert action_id in after_complete["completed"]

    chains = await load_chains(client, PATIENT_ID, PROTOCOL_PD_ID)
    assert chains[action_id].phase == "completed"
    # basedOn chain is inspectable: order basedOn plan basedOn proposal
    order = chains[action_id].requests["order"]
    assert order["basedOn"][0]["reference"].startswith("ServiceRequest/")
```

Run: `task aidbox:up && task fixtures:load-soa-ig && task fixtures:load-app && cd backend && RUN_INTEGRATION_TESTS=1 pytest tests/test_cpg_flow_integration.py -v`
Expected: PASS. This is the step that catches R6/Aidbox shape mismatches (e.g. `ServiceRequest.code` CodeableReference, Appointment search params) — fix `activity_flow.py` shapes here if Aidbox rejects them, and mirror any fix in the unit-test payloads.

- [ ] **Step 2: Update the Playwright golden path**

In `frontend/e2e/golden-path.spec.ts`, replace the authenticated test body (the uc1 exit-example study now also flows through the gates; its visits have no activities, so no task buttons appear):

```ts
  test("worklist to enroll through the CPG gates to ambiguous decision prompt", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Use Case 1 Demo Study (Exit Example)" }).click();

    await page.getByLabel("Patient FHIR ID").fill("uc1-demo-patient");
    await page.getByRole("button", { name: "Enroll" }).click();

    await expect(page.getByText("0700e721-1f12-4998-89b8-6f4e649b62f7")).toBeVisible();

    const gates = [
      "Accept proposal",
      "Authorize",
      "Schedule",
      "Patient accepts",
      "Site confirms",
      "Perform visit",
    ];
    for (const gate of gates) {
      await page.getByRole("button", { name: gate }).click();
    }
    await page.getByRole("button", { name: "Complete visit" }).click();

    await expect(page.getByText("a1806239-54f3-4762-af3f-edb9d80d29dc")).toBeVisible();

    for (const gate of gates) {
      await page.getByRole("button", { name: gate }).click();
    }
    await page.getByRole("button", { name: "Withdraw subject" }).click();
    await expect(page.getByText("Subject withdrawn from study.")).toBeVisible();

    await page.getByRole("button", { name: "Complete visit" }).click();
    await expect(page.getByText("Decision needed")).toBeVisible();
    await expect(page.getByRole("button", { name: "Day 7" })).toBeVisible();
    await expect(page.getByRole("button", { name: "End of Study" })).toBeVisible();
  });
```

Run (dev servers + Aidbox up, session bootstrapped): `cd frontend && npx playwright test`
Expected: PASS (or skipped when no `.auth/session.json`).

- [ ] **Step 3: Update the README**

In `README.md`: add `activity_flow.py   CPG activity-flow lifecycle: proposal→plan→order→schedule/book→perform→complete` to the module map; add the six new endpoints under the research_subjects line; add a short "CPG activity flow" subsection under Architecture explaining the chain (three sentences, linking the spec), the `fixtures:load-soa-ig` target and `SOA_IG_RESOURCES_DIR`, and the new demo study id. Update the unit-test count line to the new totals from `pytest -q`.

- [ ] **Step 4: Full verification and commit**

Run: `cd backend && pytest -q && cd ../frontend && npx vitest run && npx tsc --noEmit`
Expected: all green.

```bash
git add backend/tests/test_cpg_flow_integration.py frontend/e2e/golden-path.spec.ts README.md
git commit -m "Add CPG lifecycle integration test, e2e gate walk, and README docs"
```

---

## Self-Review (completed)

- **Spec coverage:** resource model (Tasks 4–8), scheduling/engagement layer (Task 6), Task layer hybrid completion (Tasks 7–8, 14), withdrawal revocation (Task 9), groupIdentifier (Tasks 4–5), definitions/fixtures/drift guard (Tasks 1, 12), backend API (Tasks 10–11), frontend (Tasks 13–14), testing (every task + Task 15). Out-of-scope items from the spec are not implemented anywhere. ✓
- **Type consistency:** `VisitChain.requests` keyed by intent, `activities` keyed by activity id then intent — used consistently in Tasks 3, 5–9. `schedule_response(state, visits=None)` — Tasks 2, 5, 8, 10, 11. Client functions in Task 13 match routes in Task 11. ✓
- **Known risk, called out in Task 15 Step 1:** exact R6-ballot3 shapes (`ServiceRequest.code` CodeableReference, Appointment/Task fields) are validated against live Aidbox by the integration test; unit tests encode the same shapes, so any fix discovered there must be mirrored back.
