"""Shared analysis report schema primitives.

These dataclasses are intentionally lightweight. They are the internal contract
that workflow code can adapt into the current MCP and Control Center payloads
while the migration is in progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .scoring import clamp_score, coverage_score, health_from_risk, risk_band

ANALYSIS_REPORT_CONTRACT_VERSION = "fls-pilot.analysis-report.v1"

FRESHNESS_STATUSES = {"fresh", "stale", "partial", "unavailable", "unknown"}
ANALYSIS_MODES = {
    "static_snapshot",
    "live_runtime",
    "watch_window",
    "rendered_audio",
    "manual_check",
    "hybrid",
}
PREREQUISITE_STATUSES = {"ok", "missing", "unavailable", "skipped", "unknown"}
SEVERITIES = {"ok", "info", "low", "medium", "high", "critical", "warning", "error"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def report_id(prefix: str = "rep") -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _validate(value: str, allowed: set[str], field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"invalid {field_name}: {value!r}")
    return normalized


def _compact(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): _compact(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_compact(v) for v in value if v is not None]
    return value


@dataclass(frozen=True)
class Freshness:
    status: str = "unknown"
    created_at: str | None = None
    valid_until: str | None = None
    invalidates_on: tuple[str, ...] = ()
    source_observation_ids: tuple[str, ...] = ()
    details: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _validate(self.status, FRESHNESS_STATUSES, "freshness status"),
        )
        object.__setattr__(self, "invalidates_on", tuple(self.invalidates_on))
        object.__setattr__(self, "source_observation_ids", tuple(self.source_observation_ids))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.created_at:
            out["created_at"] = self.created_at
        if self.valid_until:
            out["valid_until"] = self.valid_until
        if self.invalidates_on:
            out["invalidates_on"] = list(self.invalidates_on)
        if self.source_observation_ids:
            out["source_observation_ids"] = list(self.source_observation_ids)
        if self.details:
            out["details"] = self.details
        return out


@dataclass(frozen=True)
class Coverage:
    required: int = 0
    available: int = 0
    missing: tuple[str, ...] = ()
    optional_available: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "required", max(0, int(self.required)))
        object.__setattr__(self, "available", max(0, int(self.available)))
        object.__setattr__(self, "optional_available", max(0, int(self.optional_available)))
        object.__setattr__(self, "missing", tuple(str(item) for item in self.missing))

    @property
    def score(self) -> int:
        return coverage_score(self.required, self.available)

    @property
    def status(self) -> str:
        if self.required == 0:
            return "fresh"
        if self.available <= 0:
            return "unavailable"
        if self.missing or self.available < self.required:
            return "partial"
        return "fresh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "available": self.available,
            "missing": list(self.missing),
            "optional_available": self.optional_available,
            "score": self.score,
            "status": self.status,
        }


@dataclass(frozen=True)
class Prerequisite:
    id: str
    status: str
    details: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(
            self,
            "status",
            _validate(self.status, PREREQUISITE_STATUSES, "prerequisite status"),
        )

    def to_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "status": self.status}
        if self.details:
            out["details"] = self.details
        return out


@dataclass(frozen=True)
class EntityRef:
    type: str
    canonical_id: str
    display_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "type": str(self.type),
            "canonical_id": str(self.canonical_id),
        }
        if self.display_name:
            out["display_name"] = str(self.display_name)
        if self.metadata:
            out["metadata"] = _compact(self.metadata)
        return out


@dataclass(frozen=True)
class Finding:
    id: str
    rule_id: str
    title: str
    severity: str
    risk_score: int
    confidence_score: int
    evidence_mode: str
    entities: tuple[EntityRef, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    source_observation_ids: tuple[str, ...] = ()
    recommended_next_action: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "rule_id", str(self.rule_id))
        object.__setattr__(self, "title", str(self.title))
        object.__setattr__(self, "severity", _validate(self.severity, SEVERITIES, "severity"))
        object.__setattr__(self, "risk_score", clamp_score(self.risk_score))
        object.__setattr__(self, "confidence_score", clamp_score(self.confidence_score))
        object.__setattr__(
            self,
            "evidence_mode",
            _validate(self.evidence_mode, ANALYSIS_MODES, "evidence mode"),
        )
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "evidence", tuple(dict(item) for item in self.evidence))
        object.__setattr__(self, "assumptions", tuple(str(item) for item in self.assumptions))
        object.__setattr__(self, "limitations", tuple(str(item) for item in self.limitations))
        object.__setattr__(
            self,
            "source_observation_ids",
            tuple(str(item) for item in self.source_observation_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity,
            "risk_score": self.risk_score,
            "risk_band": risk_band(self.risk_score),
            "confidence_score": self.confidence_score,
            "evidence_mode": self.evidence_mode,
            "entities": [_compact(entity) for entity in self.entities],
            "evidence": [_compact(row) for row in self.evidence],
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "source_observation_ids": list(self.source_observation_ids),
        }
        if self.recommended_next_action:
            out["recommended_next_action"] = _compact(self.recommended_next_action)
        if self.metadata:
            out["metadata"] = _compact(self.metadata)
        return out


@dataclass(frozen=True)
class AnalysisReport:
    workflow: str
    title: str
    analysis_mode: str
    evidence_mode: str = "static_snapshot_only"
    report_id: str = field(default_factory=report_id)
    created_at: str = field(default_factory=utc_now_iso)
    project_fingerprint: str | None = None
    freshness: Freshness = field(default_factory=Freshness)
    coverage: Coverage = field(default_factory=Coverage)
    prerequisites: tuple[Prerequisite, ...] = ()
    risk_score: int = 0
    health_score: int | None = None
    confidence_score: int = 0
    findings: tuple[Finding, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    manual_checks: tuple[dict[str, Any], ...] = ()
    source_observations: tuple[str, ...] = ()
    next_actions: tuple[dict[str, Any], ...] = ()
    proposed_changes: tuple[dict[str, Any], ...] = ()
    applied_changes: tuple[dict[str, Any], ...] = ()
    safety: dict[str, Any] = field(default_factory=lambda: {"read_only": True})
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workflow", str(self.workflow))
        object.__setattr__(self, "title", str(self.title))
        object.__setattr__(
            self,
            "analysis_mode",
            _validate(self.analysis_mode, ANALYSIS_MODES, "analysis mode"),
        )
        object.__setattr__(self, "evidence_mode", str(self.evidence_mode))
        object.__setattr__(self, "risk_score", clamp_score(self.risk_score))
        health = (
            health_from_risk(self.risk_score)
            if self.health_score is None
            else self.health_score
        )
        object.__setattr__(self, "health_score", clamp_score(health))
        object.__setattr__(self, "confidence_score", clamp_score(self.confidence_score))
        object.__setattr__(self, "prerequisites", tuple(self.prerequisites))
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(self, "assumptions", tuple(str(item) for item in self.assumptions))
        object.__setattr__(self, "limitations", tuple(str(item) for item in self.limitations))
        object.__setattr__(self, "manual_checks", tuple(dict(item) for item in self.manual_checks))
        object.__setattr__(
            self,
            "source_observations",
            tuple(str(item) for item in self.source_observations),
        )
        object.__setattr__(self, "next_actions", tuple(dict(item) for item in self.next_actions))
        object.__setattr__(
            self,
            "proposed_changes",
            tuple(dict(item) for item in self.proposed_changes),
        )
        object.__setattr__(
            self,
            "applied_changes",
            tuple(dict(item) for item in self.applied_changes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": ANALYSIS_REPORT_CONTRACT_VERSION,
            "report_id": self.report_id,
            "workflow": self.workflow,
            "title": self.title,
            "created_at": self.created_at,
            "analysis_mode": self.analysis_mode,
            "evidence_mode": self.evidence_mode,
            "project_fingerprint": self.project_fingerprint or "unknown",
            "freshness": self.freshness.to_dict(),
            "coverage": self.coverage.to_dict(),
            "prerequisites": [_compact(item) for item in self.prerequisites],
            "risk_score": self.risk_score,
            "risk_band": risk_band(self.risk_score),
            "health_score": self.health_score,
            "confidence_score": self.confidence_score,
            "findings": [_compact(item) for item in self.findings],
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "manual_checks": [_compact(item) for item in self.manual_checks],
            "source_observations": list(self.source_observations),
            "next_actions": [_compact(item) for item in self.next_actions],
            "proposed_changes": [_compact(item) for item in self.proposed_changes],
            "applied_changes": [_compact(item) for item in self.applied_changes],
            "safety": _compact(self.safety),
            "metadata": _compact(self.metadata),
        }
