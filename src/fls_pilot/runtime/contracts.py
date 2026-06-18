"""Serializable contracts for the canonical cross-process Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_session_id() -> str:
    return f"runtime_{uuid4().hex[:16]}"


@dataclass(frozen=True)
class RuntimeSession:
    id: str = field(default_factory=runtime_session_id)
    started_at: str = field(default_factory=utc_now_iso)
    runtime_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "runtime_version": self.runtime_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeSession:
        return cls(
            id=str(value.get("id") or runtime_session_id()),
            started_at=str(value.get("started_at") or utc_now_iso()),
            runtime_version=(
                str(value["runtime_version"]) if value.get("runtime_version") else None
            ),
        )


@dataclass(frozen=True)
class ProjectContext:
    runtime_session_id: str
    project_scope_id: str = "unknown"
    project_identity_hint: str | None = None
    project_identity_confidence: str = "unknown"
    project_fingerprint: str = "unknown"
    snapshot_id: str = "unknown"
    snapshot_revision: int = 0
    created_at: str = field(default_factory=utc_now_iso)
    refreshed_at: str = field(default_factory=utc_now_iso)
    source_observation_ids: tuple[str, ...] = ()
    freshness: str = "unknown"
    invalidation_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_revision", max(0, int(self.snapshot_revision)))
        object.__setattr__(
            self,
            "source_observation_ids",
            tuple(str(row) for row in self.source_observation_ids),
        )
        object.__setattr__(
            self,
            "invalidation_reasons",
            tuple(str(row) for row in self.invalidation_reasons),
        )

    @property
    def is_known(self) -> bool:
        return self.project_scope_id != "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_session_id": self.runtime_session_id,
            "project_scope_id": self.project_scope_id,
            "project_identity_hint": self.project_identity_hint,
            "project_identity_confidence": self.project_identity_confidence,
            "project_fingerprint": self.project_fingerprint,
            "snapshot_id": self.snapshot_id,
            "snapshot_revision": self.snapshot_revision,
            "created_at": self.created_at,
            "refreshed_at": self.refreshed_at,
            "source_observation_ids": list(self.source_observation_ids),
            "freshness": self.freshness,
            "invalidation_reasons": list(self.invalidation_reasons),
        }

    @classmethod
    def unknown(cls, runtime_session_id: str) -> ProjectContext:
        return cls(runtime_session_id=runtime_session_id)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProjectContext:
        return cls(
            runtime_session_id=str(value.get("runtime_session_id") or "unknown"),
            project_scope_id=str(value.get("project_scope_id") or "unknown"),
            project_identity_hint=(
                str(value["project_identity_hint"])
                if value.get("project_identity_hint")
                else None
            ),
            project_identity_confidence=str(
                value.get("project_identity_confidence") or "unknown"
            ),
            project_fingerprint=str(value.get("project_fingerprint") or "unknown"),
            snapshot_id=str(value.get("snapshot_id") or "unknown"),
            snapshot_revision=int(value.get("snapshot_revision") or 0),
            created_at=str(value.get("created_at") or utc_now_iso()),
            refreshed_at=str(value.get("refreshed_at") or utc_now_iso()),
            source_observation_ids=tuple(value.get("source_observation_ids") or ()),
            freshness=str(value.get("freshness") or "unknown"),
            invalidation_reasons=tuple(value.get("invalidation_reasons") or ()),
        )


@dataclass(frozen=True)
class ReportScope:
    workflow_id: str
    runtime_session_id: str
    project_scope_id: str
    snapshot_id: str = "unknown"
    snapshot_revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "runtime_session_id": self.runtime_session_id,
            "project_scope_id": self.project_scope_id,
            "snapshot_id": self.snapshot_id,
            "snapshot_revision": self.snapshot_revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ReportScope:
        return cls(
            workflow_id=str(value.get("workflow_id") or ""),
            runtime_session_id=str(value.get("runtime_session_id") or "unknown"),
            project_scope_id=str(value.get("project_scope_id") or "unknown"),
            snapshot_id=str(value.get("snapshot_id") or "unknown"),
            snapshot_revision=int(value.get("snapshot_revision") or 0),
        )


@dataclass(frozen=True)
class RuntimeResponse:
    ok: bool
    operation: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {
            "ok": bool(self.ok),
            "operation": self.operation,
            "data": dict(self.data),
        }
        if self.error:
            out["error"] = self.error
        if self.code:
            out["code"] = self.code
        return out

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RuntimeResponse:
        data = value.get("data")
        return cls(
            ok=bool(value.get("ok")),
            operation=str(value.get("operation") or ""),
            data=dict(data) if isinstance(data, Mapping) else {},
            error=str(value["error"]) if value.get("error") else None,
            code=str(value["code"]) if value.get("code") else None,
        )
