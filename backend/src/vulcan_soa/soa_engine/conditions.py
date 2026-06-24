import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_OPERATIONS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass(frozen=True)
class SubjectContext:
    withdrawn: bool
    visited_action_ids: frozenset[str]
    completed_action_ids: frozenset[str]


def _normalize_json_booleans(expression: str) -> str:
    return (
        expression.replace("true", "True")
        .replace("false", "False")
        .replace("null", "None")
    )


def evaluate_condition(language: str, expression: str, context: SubjectContext) -> bool:
    if language != "text/x-soa-expressionplain":
        logger.warning("Unsupported condition language %r; failing closed", language)
        return False

    try:
        parsed = ast.literal_eval(_normalize_json_booleans(expression))
    except (ValueError, SyntaxError):
        logger.warning("Unparseable condition expression %r; failing closed", expression)
        return False

    if not isinstance(parsed, dict):
        logger.warning("Condition expression %r is not a dict; failing closed", expression)
        return False

    operation = _OPERATIONS.get(parsed.get("operation", "=="))
    if operation is None:
        logger.warning("Unsupported operation in %r; failing closed", expression)
        return False

    if "withdraw" in parsed or "withdrawn" in parsed:
        expected = parsed.get("withdraw", parsed.get("withdrawn"))
        return operation(context.withdrawn, expected)

    logger.warning("No recognized condition key in %r; failing closed", expression)
    return False
