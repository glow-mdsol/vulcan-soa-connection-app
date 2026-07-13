from dataclasses import dataclass

SOA_EXTENSION_BASES = (
    "http://hl7.org/fhir/uv/vulcan-schedule/StructureDefinition/",
    "http://example.org/br-and-r/soa/StructureDefinition/",
)


@dataclass(frozen=True)
class Transition:
    target_id: str
    transition_type: str
    condition_language: str | None
    condition_expression: str | None


@dataclass(frozen=True)
class VisitNode:
    action_id: str
    title: str
    transitions: tuple[Transition, ...]
    definition_uri: str | None = None


@dataclass(frozen=True)
class ProtocolGraph:
    plan_definition_id: str
    nodes: dict[str, VisitNode]
    root_ids: tuple[str, ...]


def _find_extension(extensions: list[dict], name: str) -> dict | None:
    for ext in extensions:
        url = ext.get("url", "")
        for base in SOA_EXTENSION_BASES:
            if url == base + name:
                return ext
    return None


def _sub_extension_value(extension: dict, sub_url: str) -> object | None:
    for sub in extension.get("extension", []):
        if sub.get("url") == sub_url:
            for key, value in sub.items():
                if key.startswith("value"):
                    return value
    return None


def _parse_transition(transition_action: dict) -> Transition:
    soa_transition = _find_extension(transition_action.get("extension", []), "soaTransition")
    target_id = _sub_extension_value(soa_transition, "soaTargetId") if soa_transition else None
    transition_type = (
        _sub_extension_value(soa_transition, "soaTransitionType") if soa_transition else None
    )

    condition_language = None
    condition_expression = None
    conditions = transition_action.get("condition", [])
    if conditions:
        expression = conditions[0].get("expression", {})
        condition_language = expression.get("language")
        condition_expression = expression.get("expression")

    return Transition(
        target_id=target_id,
        transition_type=transition_type,
        condition_language=condition_language,
        condition_expression=condition_expression,
    )


def _parse_node(action: dict) -> VisitNode:
    transitions = tuple(_parse_transition(child) for child in action.get("action", []))
    return VisitNode(
        action_id=action["id"],
        title=action.get("title", action["id"]),
        transitions=transitions,
        definition_uri=action.get("definitionUri") or action.get("definitionCanonical"),
    )


def parse_protocol_graph(plan_definition: dict) -> ProtocolGraph:
    actions = plan_definition.get("action", [])
    nodes = {action["id"]: _parse_node(action) for action in actions}

    # Root nodes are those not referenced as a target by any transition.
    all_target_ids: set[str] = set()
    for node in nodes.values():
        for transition in node.transitions:
            if transition.target_id:
                all_target_ids.add(transition.target_id)

    root_ids = tuple(
        action["id"] for action in actions if action["id"] not in all_target_ids
    )

    return ProtocolGraph(
        plan_definition_id=plan_definition["id"],
        nodes=nodes,
        root_ids=root_ids,
    )
