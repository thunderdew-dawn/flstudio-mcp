"""Declarative workflow requirements for analysis orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMMON_OBSERVATIONS = {
    "fl_session_alive",
    "static_project_snapshot",
    "project_state",
    "canonical_mixer_model",
    "channel_routing_snapshot",
    "mixer_tracks_snapshot",
    "routing_snapshot",
    "patterns_snapshot",
    "playlist_tracks_snapshot",
    "template_context_snapshot",
    "live_meter_window",
    "rendered_audio_features",
    "knowledgebase_policy_refs",
    "requires_fl_connected",
    "requires_playback",
    "requires_meter_window",
    "requires_recent_watch",
}


@dataclass(frozen=True)
class WorkflowRequirement:
    id: str
    observation_kind: str
    required: bool = True
    ttl_seconds: float | None = None
    invalidates_on: tuple[str, ...] = ()
    evidence_mode: str = "static_snapshot"
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "observation_kind", str(self.observation_kind))
        object.__setattr__(self, "invalidates_on", tuple(str(x) for x in self.invalidates_on))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "observation_kind": self.observation_kind,
            "required": self.required,
            "evidence_mode": self.evidence_mode,
            "invalidates_on": list(self.invalidates_on),
        }
        if self.ttl_seconds is not None:
            out["ttl_seconds"] = self.ttl_seconds
        if self.description:
            out["description"] = self.description
        return out


@dataclass(frozen=True)
class WorkflowRequirementSet:
    workflow_id: str
    requirements: tuple[WorkflowRequirement, ...] = field(default_factory=tuple)

    @property
    def required(self) -> tuple[WorkflowRequirement, ...]:
        return tuple(item for item in self.requirements if item.required)

    @property
    def optional(self) -> tuple[WorkflowRequirement, ...]:
        return tuple(item for item in self.requirements if not item.required)

    def observation_kinds(self, *, include_optional: bool = True) -> tuple[str, ...]:
        rows = self.requirements if include_optional else self.required
        return tuple(item.observation_kind for item in rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "required": [item.to_dict() for item in self.required],
            "optional": [item.to_dict() for item in self.optional],
        }


def requirement(
    observation_kind: str,
    *,
    id: str | None = None,
    required: bool = True,
    ttl_seconds: float | None = None,
    invalidates_on: list[str] | tuple[str, ...] | None = None,
    evidence_mode: str = "static_snapshot",
    description: str | None = None,
) -> WorkflowRequirement:
    return WorkflowRequirement(
        id=id or observation_kind,
        observation_kind=observation_kind,
        required=required,
        ttl_seconds=ttl_seconds,
        invalidates_on=tuple(invalidates_on or ()),
        evidence_mode=evidence_mode,
        description=description,
    )
