"""Pure evaluation functions for data-only rules."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .schema import RuleCondition, RuleDefinition, RuleFinding

_MISSING = object()


def evaluate_condition(
    observation: Mapping[str, Any],
    condition: RuleCondition,
) -> bool:
    """Evaluate one condition; missing or incompatible values do not match."""
    actual = _field_value(observation, condition.field)
    if actual is _MISSING:
        return False
    expected = condition.value
    operator = condition.operator

    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "truthy":
        return bool(actual)
    if operator == "falsy":
        return not actual
    if operator == "contains":
        try:
            return expected in actual
        except (TypeError, ValueError):
            return False
    if operator == "in":
        try:
            return actual in expected
        except (TypeError, ValueError):
            return False
    if operator == "gte":
        try:
            return actual >= expected
        except (TypeError, ValueError):
            return False
    if operator == "lte":
        try:
            return actual <= expected
        except (TypeError, ValueError):
            return False
    return False


def evaluate_rules(
    observation: Mapping[str, Any],
    rules: Iterable[RuleDefinition],
) -> tuple[RuleFinding, ...]:
    """Return findings for matching rules in input order."""
    findings = []
    for rule in rules:
        results = [
            evaluate_condition(observation, condition)
            for condition in rule.conditions
        ]
        matched = all(results) if rule.match == "all" else any(results)
        if not results or not matched:
            continue
        evidence = tuple(
            {
                "field": condition.field,
                "operator": condition.operator,
                "expected": condition.value,
                "actual": _field_value(observation, condition.field),
            }
            for condition, result in zip(rule.conditions, results, strict=True)
            if result
        )
        findings.append(
            RuleFinding(
                id=f"rule:{rule.id}",
                rule_id=rule.id,
                title=rule.title,
                severity=rule.severity,
                risk_score=rule.risk_score,
                confidence_score=rule.confidence_score,
                evidence_mode=rule.evidence_mode,
                evidence=evidence,
                metadata=rule.metadata,
            )
        )
    return tuple(findings)


def _field_value(observation: Mapping[str, Any], field: str) -> Any:
    current: Any = observation
    for part in field.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current
