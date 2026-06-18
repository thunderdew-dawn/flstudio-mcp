"""Single source of truth for workflow identity and product metadata."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..analysis.requirements import WorkflowRequirementSet, requirement

WORKFLOW_KINDS = {
    "runtime_readiness",
    "aggregator",
    "analysis_workflow",
    "organizer_subworkflow",
    "assistant_workflow",
    "evidence_worker",
}
WORKFLOW_STATUSES = {"active", "planned", "inactive"}
HEALTH_INCLUSION_POLICIES = {
    "runtime_prerequisite_only",
    "primary_aggregator",
    "required_when_enabled",
    "included_when_current_report_available",
    "included_when_enabled_and_current_report_available",
    "optional_context_report",
    "evidence_upgrade_when_available",
    "excluded",
}

CANONICAL_WORKFLOW_IDS = (
    "setup_runtime",
    "project_health",
    "mix_review",
    "routing_audit",
    "low_end_analysis",
    "project_organizer",
    "jam_2_project",
    "preflight",
    "sidechain_routing_check",
    "plugin_assistant",
    "preset_assistant",
    "audio_evidence",
)

LEGACY_WORKFLOW_ALIASES = {
    "low_end": "low_end_analysis",
    "low_end_safety": "low_end_analysis",
    "organizer": "project_organizer",
    "sidechain": "sidechain_routing_check",
    "sidechaining": "sidechain_routing_check",
    "routing_review": "routing_audit",
}


def canonical_workflow_id(value: str) -> str:
    """Normalize a workflow id without accepting unknown identities."""
    normalized = str(value or "").strip().lower().replace("-", "_")
    canonical = LEGACY_WORKFLOW_ALIASES.get(normalized, normalized)
    if canonical not in CANONICAL_WORKFLOW_IDS:
        raise ValueError(f"unknown workflow id: {value!r}")
    return canonical


@dataclass(frozen=True)
class WorkflowDeclaration:
    id: str
    title: str
    kind: str
    status: str
    health_inclusion_policy: str
    analysis_report_required: bool
    requirements: WorkflowRequirementSet | None = None
    parent_workflow_id: str | None = None
    panel_id: str | None = None
    group: str = "Project Review"
    endpoint: str | None = None
    action_label: str | None = None
    safety_note: str = ""
    supported_next_actions: tuple[str, ...] = ()
    manual_only_actions: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", canonical_workflow_id(self.id))
        if self.kind not in WORKFLOW_KINDS:
            raise ValueError(f"invalid workflow kind: {self.kind!r}")
        if self.status not in WORKFLOW_STATUSES:
            raise ValueError(f"invalid workflow status: {self.status!r}")
        if self.health_inclusion_policy not in HEALTH_INCLUSION_POLICIES:
            raise ValueError(
                f"invalid health inclusion policy: {self.health_inclusion_policy!r}"
            )
        if self.parent_workflow_id is not None:
            object.__setattr__(
                self,
                "parent_workflow_id",
                canonical_workflow_id(self.parent_workflow_id),
            )
        if self.requirements and self.requirements.workflow_id != self.id:
            raise ValueError(
                f"requirement workflow id {self.requirements.workflow_id!r} "
                f"does not match declaration {self.id!r}"
            )
        object.__setattr__(
            self, "supported_next_actions", tuple(self.supported_next_actions)
        )
        object.__setattr__(self, "manual_only_actions", tuple(self.manual_only_actions))
        object.__setattr__(self, "forbidden_actions", tuple(self.forbidden_actions))

    @property
    def enabled(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "enabled": self.enabled,
            "analysis_report_required": self.analysis_report_required,
            "health_inclusion_policy": self.health_inclusion_policy,
            "requirements": self.requirements.to_dict() if self.requirements else None,
            "parent_workflow_id": self.parent_workflow_id,
            "panel_id": self.panel_id,
            "group": self.group,
            "endpoint": self.endpoint,
            "action_label": self.action_label,
            "safety_note": self.safety_note,
            "supported_next_actions": list(self.supported_next_actions),
            "manual_only_actions": list(self.manual_only_actions),
            "forbidden_actions": list(self.forbidden_actions),
            "metadata": dict(self.metadata),
        }

    def to_control_center_dict(self) -> dict[str, Any]:
        maturity = "read_only" if self.enabled else "planned"
        return {
            "id": self.id,
            "panel_id": self.panel_id,
            "title": self.title,
            "group": self.group,
            "maturity": maturity,
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "action_label": self.action_label,
            "safety_note": self.safety_note,
            "kind": self.kind,
            "analysis_report_required": self.analysis_report_required,
            "health_inclusion_policy": self.health_inclusion_policy,
        }


class WorkflowRegistry:
    """Validated immutable-by-convention workflow declaration registry."""

    def __init__(self, declarations: Iterable[WorkflowDeclaration]) -> None:
        rows = tuple(declarations)
        by_id: dict[str, WorkflowDeclaration] = {}
        for row in rows:
            if row.id in by_id:
                raise ValueError(f"duplicate workflow id: {row.id}")
            by_id[row.id] = row
        for row in rows:
            if row.parent_workflow_id and row.parent_workflow_id not in by_id:
                raise ValueError(
                    f"unknown parent workflow {row.parent_workflow_id!r} for {row.id!r}"
                )
        self._rows = rows
        self._by_id = by_id

    def get(self, workflow_id: str) -> WorkflowDeclaration:
        return self._by_id[canonical_workflow_id(workflow_id)]

    def list(self, *, include_inactive: bool = True) -> tuple[WorkflowDeclaration, ...]:
        if include_inactive:
            return self._rows
        return tuple(row for row in self._rows if row.enabled)

    def control_center_catalog(self) -> list[dict[str, Any]]:
        return [
            row.to_control_center_dict()
            for row in self._rows
            if row.panel_id is not None
        ]


def _declaration(
    workflow_id: str,
    title: str,
    kind: str,
    status: str,
    health_policy: str,
    report_required: bool,
    **kwargs: Any,
) -> WorkflowDeclaration:
    return WorkflowDeclaration(
        id=workflow_id,
        title=title,
        kind=kind,
        status=status,
        health_inclusion_policy=health_policy,
        analysis_report_required=report_required,
        **kwargs,
    )


DEFAULT_WORKFLOW_REGISTRY = WorkflowRegistry(
    (
        _declaration(
            "setup_runtime",
            "Setup & Runtime Doctor",
            "runtime_readiness",
            "active",
            "runtime_prerequisite_only",
            False,
        ),
        _declaration(
            "project_health",
            "Health",
            "aggregator",
            "active",
            "primary_aggregator",
            False,
            panel_id="producer_health",
            endpoint="/api/workflows/project-health",
            action_label="Run Health Scan",
            safety_note="Read-only overview across current Runtime workflow reports.",
        ),
        _declaration(
            "mix_review",
            "Mix Review",
            "analysis_workflow",
            "active",
            "included_when_current_report_available",
            True,
            requirements=WorkflowRequirementSet(
                "mix_review",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("static_project_snapshot", ttl_seconds=60),
                    requirement(
                        "rendered_audio_features",
                        required=False,
                        evidence_mode="rendered_audio",
                        invalidates_on=(
                            "project_identity_change",
                            "audio_source_hash_changed",
                        ),
                    ),
                ),
            ),
            panel_id="producer_mix_review",
            endpoint="/api/workflows/mix-review",
            action_label="Run Mix Review",
            safety_note=(
                "Read-only mixer review. Static execution remains available; "
                "audio-backed conclusions require a linked rendered master."
            ),
        ),
        _declaration(
            "routing_audit",
            "Routing Audit",
            "analysis_workflow",
            "active",
            "included_when_current_report_available",
            True,
            panel_id="producer_routing",
            endpoint="/api/workflows/routing-audit",
            action_label="Run Routing Audit",
            safety_note="Read-only routing audit. Cleanup remains proposal-first.",
        ),
        _declaration(
            "low_end_analysis",
            "Low-End Safety Check",
            "analysis_workflow",
            "active",
            "included_when_current_report_available",
            True,
            requirements=WorkflowRequirementSet(
                "low_end_analysis",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("static_project_snapshot", ttl_seconds=60),
                    requirement(
                        "rendered_audio_features",
                        required=False,
                        evidence_mode="rendered_audio",
                        invalidates_on=(
                            "project_identity_change",
                            "audio_source_hash_changed",
                        ),
                    ),
                ),
            ),
            panel_id="producer_low_end",
            endpoint="/api/workflows/low-end-analysis",
            action_label="Run Low-End Safety Check",
            safety_note=(
                "Read-only low-end review. Metadata raises suspicions; rendered "
                "audio is required for audio-backed energy and stereo proxy claims."
            ),
        ),
        _declaration(
            "project_organizer",
            "Organizer",
            "analysis_workflow",
            "active",
            "included_when_current_report_available",
            True,
            panel_id="producer_organizer",
            endpoint="/api/workflows/project-organizer",
            action_label="Run Organizer",
            safety_note="Read-only scan. Cleanup requires an approved safe-write tool.",
        ),
        _declaration(
            "preflight",
            "Preflight",
            "analysis_workflow",
            "active",
            "included_when_enabled_and_current_report_available",
            True,
            requirements=WorkflowRequirementSet(
                "preflight",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("static_project_snapshot", ttl_seconds=60),
                    requirement(
                        "live_meter_window",
                        required=False,
                        ttl_seconds=2,
                        evidence_mode="live_runtime",
                    ),
                ),
            ),
            panel_id="producer_preflight",
            group="Project Review",
            endpoint="/api/workflows/preflight",
            action_label="Run Preflight",
            safety_note=(
                "Read-only export-readiness review. Render, save, export, and "
                "mastering remain manual."
            ),
            supported_next_actions=("run_mix_review", "review_safe_proposals"),
            manual_only_actions=(
                "render",
                "save",
                "export",
                "mastering",
                "audio_clip_stretch_mode",
                "audio_clip_normalize",
            ),
            forbidden_actions=("automatic_render", "automatic_save_as"),
        ),
        _declaration(
            "jam_2_project",
            "Structure Jammed Project",
            "organizer_subworkflow",
            "planned",
            "excluded",
            True,
            requirements=WorkflowRequirementSet(
                "jam_2_project",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("static_project_snapshot", ttl_seconds=60),
                    requirement("patterns_snapshot", ttl_seconds=60),
                    requirement("playlist_tracks_snapshot", ttl_seconds=60),
                ),
            ),
            parent_workflow_id="project_organizer",
            panel_id="producer_jam_2_project",
            group="Roadmap",
            safety_note=(
                "Planned for v3.1+. No Control Center action is available in v3.0."
            ),
            supported_next_actions=("run_project_organizer", "review_safe_proposals"),
            manual_only_actions=("confirm_sections", "confirm_musical_roles"),
            forbidden_actions=(
                "playlist_clip_editing",
                "automatic_arrangement",
                "destructive_cleanup",
            ),
        ),
        _declaration(
            "sidechain_routing_check",
            "Sidechain Routing Check",
            "analysis_workflow",
            "planned",
            "excluded",
            True,
            requirements=WorkflowRequirementSet(
                "sidechain_routing_check",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("routing_snapshot", ttl_seconds=60),
                ),
            ),
            panel_id="producer_sidechaining",
            group="Roadmap",
            safety_note=(
                "Planned after v3.0. Plugin detector settings remain a manual check."
            ),
            supported_next_actions=("inspect_loaded_plugin",),
            manual_only_actions=("verify_plugin_sidechain_input",),
            forbidden_actions=("plugin_loading", "unknown_parameter_writes"),
        ),
        _declaration(
            "plugin_assistant",
            "Plugin Assistant",
            "assistant_workflow",
            "planned",
            "excluded",
            True,
            requirements=WorkflowRequirementSet(
                "plugin_assistant",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement(
                        "mixer_track_target",
                        id="mixer_track_target",
                        evidence_mode="manual_check",
                    ),
                ),
            ),
            panel_id="producer_plugin_assistant",
            group="Roadmap",
            safety_note=(
                "Planned after v3.0. Plugin loading and unknown parameter writes "
                "remain manual."
            ),
            supported_next_actions=("list_loaded_plugins", "inspect_named_parameters"),
            manual_only_actions=("choose_mixer_track", "load_plugin"),
            forbidden_actions=("plugin_loading", "plugin_insertion"),
        ),
        _declaration(
            "preset_assistant",
            "Preset Assistant",
            "assistant_workflow",
            "planned",
            "excluded",
            True,
            requirements=WorkflowRequirementSet(
                "preset_assistant",
                (requirement("local_preset_library"),),
            ),
            panel_id="producer_preset_assistant",
            group="Roadmap",
            safety_note=(
                "Planned after v3.0. Preset loading remains manual."
            ),
            supported_next_actions=("list_preset_names", "suggest_by_name"),
            manual_only_actions=("load_preset", "audition_preset"),
            forbidden_actions=("automatic_preset_loading",),
        ),
        _declaration(
            "audio_evidence",
            "Audio Evidence",
            "evidence_worker",
            "planned",
            "excluded",
            True,
            requirements=WorkflowRequirementSet(
                "audio_evidence",
                (
                    requirement(
                        "rendered_audio_features",
                        evidence_mode="rendered_audio",
                        invalidates_on=("file_hash_change",),
                    ),
                ),
            ),
            supported_next_actions=("link_evidence_to_workflow",),
            manual_only_actions=("select_audio_file", "render_audio_in_fl_studio"),
            forbidden_actions=("automatic_render", "full_mixer_stem_batch"),
            metadata={
                "accepted_evidence_kinds": ["rendered_master", "stem", "candidate"],
                "short_file_limit_seconds": 180,
            },
        ),
    )
)
