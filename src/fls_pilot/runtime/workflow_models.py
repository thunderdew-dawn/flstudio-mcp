"""Workflow Definition Models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

WorkflowOrigin = Literal["builtin", "custom", "pack"]
WorkflowStatus = Literal["active", "inactive", "archived", "planned", "draft"]
WorkflowRunnerType = Literal["builtin", "job"]

@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    version: int
    title: str
    kind: str
    status: WorkflowStatus
    origin: WorkflowOrigin
    protected: bool
    runner_type: WorkflowRunnerType
    analysis_report_required: bool
    health_inclusion_policy: str
    created_at: str
    updated_at: str
    
    # Optional / defaulted fields
    description: str = ""
    runner_ref: str | None = None
    requirements: dict[str, Any] | None = None
    parent_workflow_id: str | None = None
    panel_id: str | None = None
    group: str = ""
    endpoint: str | None = None
    action_label: str | None = None
    safety_note: str = ""
    
    # Tuples (stored as JSON arrays)
    supported_next_actions: tuple[str, ...] = ()
    manual_only_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    
    # Dicts
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Pack/License fields
    pack_id: str | None = None
    pack_version: str | None = None
    edition: str | None = None
    license_required: str | None = None
    
    archived_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_next_actions", tuple(self.supported_next_actions))
        object.__setattr__(self, "manual_only_actions", tuple(self.manual_only_actions))
        object.__setattr__(self, "forbidden_actions", tuple(self.forbidden_actions))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "status": self.status,
            "origin": self.origin,
            "protected": self.protected,
            "runner_type": self.runner_type,
            "runner_ref": self.runner_ref,
            "analysis_report_required": self.analysis_report_required,
            "health_inclusion_policy": self.health_inclusion_policy,
            "requirements": self.requirements,
            "parent_workflow_id": self.parent_workflow_id,
            "panel_id": self.panel_id,
            "group": self.group,
            "endpoint": self.endpoint,
            "action_label": self.action_label,
            "safety_note": self.safety_note,
            "supported_next_actions": list(self.supported_next_actions),
            "manual_only_actions": list(self.manual_only_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "inputs_schema": self.inputs_schema,
            "metadata": self.metadata,
            "capabilities": list(self.capabilities),
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "edition": self.edition,
            "license_required": self.license_required,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "archived_at": self.archived_at,
        }
