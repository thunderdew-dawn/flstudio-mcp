"""Data-only schema for deterministic workflow rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

RULE_OPERATORS = {"eq", "ne", "contains", "in", "gte", "lte", "truthy", "falsy"}


@dataclass(frozen=True)
class RuleCondition:
    field: str
    operator: str
    value: Any = None

    def __post_init__(self) -> None:
        field_name = str(self.field or "").strip()
        if not field_name:
            raise ValueError("rule condition field is required")
        operator = str(self.operator or "").strip().lower()
        if operator not in RULE_OPERATORS:
            raise ValueError(f"invalid rule operator: {self.operator!r}")
        object.__setattr__(self, "field", field_name)
        object.__setattr__(self, "operator", operator)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass(frozen=True)
class RuleDefinition:
    id: str
    title: str
    severity: str
    risk_score: int
    confidence_score: int
    evidence_mode: str
    conditions: tuple[RuleCondition, ...]
    match: str = "all"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rule_id = str(self.id or "").strip()
        if not rule_id:
            raise ValueError("rule id is required")
        match = str(self.match or "").strip().lower()
        if match not in {"all", "any"}:
            raise ValueError(f"invalid rule match mode: {self.match!r}")
        object.__setattr__(self, "id", rule_id)
        object.__setattr__(self, "title", str(self.title or rule_id))
        object.__setattr__(self, "severity", str(self.severity or "info").lower())
        object.__setattr__(self, "risk_score", max(0, min(100, int(self.risk_score))))
        object.__setattr__(
            self,
            "confidence_score",
            max(0, min(100, int(self.confidence_score))),
        )
        object.__setattr__(self, "evidence_mode", str(self.evidence_mode))
        object.__setattr__(self, "conditions", tuple(self.conditions))
        object.__setattr__(self, "match", match)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "evidence_mode": self.evidence_mode,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "match": self.match,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RuleFinding:
    id: str
    rule_id: str
    title: str
    severity: str
    risk_score: int
    confidence_score: int
    evidence_mode: str
    evidence: tuple[dict[str, Any], ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "confidence_score": self.confidence_score,
            "evidence_mode": self.evidence_mode,
            "evidence": [dict(item) for item in self.evidence],
            "metadata": dict(self.metadata),
        }
