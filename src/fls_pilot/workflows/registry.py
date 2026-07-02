"""Single source of truth for workflow identity and product metadata."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from ..workflow_identity import CANONICAL_WORKFLOW_IDS as CANONICAL_WORKFLOW_IDS
from ..workflow_identity import canonical_workflow_id
from ..workflow_requirements import WorkflowRequirementSet, requirement

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
            raise ValueError(f"invalid health inclusion policy: {self.health_inclusion_policy!r}")
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
        object.__setattr__(self, "supported_next_actions", tuple(self.supported_next_actions))
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
        out = {
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
        if self.metadata:
            out["metadata"] = dict(self.metadata)
        return out


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
        return [row.to_control_center_dict() for row in self._rows if row.panel_id is not None]


def build_effective_workflow_registry(
    base_registry: WorkflowRegistry,
    pack_manifests: Iterable[Any],
) -> WorkflowRegistry:
    """Attach validated pack metadata to known core workflows."""
    manifests = tuple(pack_manifests)
    seen_pack_ids: set[str] = set()
    extensions_by_workflow: dict[str, list[dict[str, Any]]] = {}

    for manifest in manifests:
        if manifest.pack_id in seen_pack_ids:
            raise ValueError(f"duplicate pack id: {manifest.pack_id}")
        seen_pack_ids.add(manifest.pack_id)
        profiles_by_id = _pack_profiles_by_id(manifest)
        for extension in manifest.workflows:
            workflow = base_registry.get(extension.workflow_id)
            selected_profiles = []
            for profile_id in extension.profiles:
                try:
                    selected_profiles.append(dict(profiles_by_id[profile_id]))
                except KeyError as exc:
                    raise ValueError(
                        f"unknown profile id {profile_id!r} in pack {manifest.pack_id!r}"
                    ) from exc
            extensions_by_workflow.setdefault(workflow.id, []).append(
                {
                    "pack_id": manifest.pack_id,
                    "pack_version": manifest.version,
                    "pack_title": manifest.title,
                    "publisher": manifest.publisher,
                    "entitlement": manifest.entitlement.to_dict(),
                    "profiles": selected_profiles,
                    "metadata": dict(extension.metadata),
                }
            )

    declarations = []
    for row in base_registry.list():
        extensions = extensions_by_workflow.get(row.id)
        if not extensions:
            declarations.append(row)
            continue
        metadata = dict(row.metadata)
        metadata["pack_extensions"] = extensions
        declarations.append(replace(row, metadata=metadata))
    return WorkflowRegistry(declarations)


def _pack_profiles_by_id(manifest: Any) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for index, profile in enumerate(manifest.profiles):
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id:
            raise ValueError(f"profiles[{index}].id is required in pack {manifest.pack_id!r}")
        if profile_id in profiles:
            raise ValueError(f"duplicate profile id {profile_id!r} in pack {manifest.pack_id!r}")
        profiles[profile_id] = dict(profile)
    return profiles


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
                    requirement(
                        "live_meter_window",
                        required=False,
                        ttl_seconds=2,
                        evidence_mode="live_runtime",
                    ),
                    requirement(
                        "rendered_stem_features",
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
                "Read-only mixer review. Level 1 is static; Level 2 uses optional "
                "transient playback/watch evidence; Level 3 uses linked rendered "
                "master proxy evidence; Level 4 uses role-confirmed stem/bus evidence."
            ),
            supported_next_actions=(
                "run_static_review",
                "start_level_2_watch",
                "link_rendered_master_evidence",
                "link_stem_bus_evidence",
                "confirm_mix_review_finding",
                "accept_mix_review_finding",
                "reject_mix_review_finding",
                "ignore_mix_review_finding",
            ),
            manual_only_actions=(
                "choose_loudest_section",
                "manual_audio_render",
                "manual_stem_export",
                "confirm_track_roles",
                "approve_fix_plan",
            ),
            forbidden_actions=("automatic_render", "plugin_loading", "playlist_clip_editing"),
            metadata={
                "mix_review_levels": [
                    "level_1_static_project_metadata",
                    "level_2_live_meter_window",
                    "level_3_rendered_master_audio_proxy",
                    "level_4_role_confirmed_stem_bus_audio",
                ],
                "finding_states": [
                    "static_heuristic",
                    "name_based_unconfirmed",
                    "metadata_suspected",
                    "live_meter_supported",
                    "rendered_master_proxy",
                    "stem_audio_confirmed",
                    "accepted_by_user",
                    "rejected_by_user",
                    "ignored_by_user",
                    "requires_more_evidence",
                ],
                "score_fields": [
                    "legacy_score",
                    "risk_score_v2",
                    "score_status",
                    "score_inputs",
                    "evidence_weight",
                    "decision_adjusted_score",
                    "blocked_findings_count",
                    "provisional_findings_count",
                    "confirmed_findings_count",
                ],
                "fix_plan_statuses": [
                    "blocked",
                    "draft",
                    "requires_user_approval",
                    "approved",
                    "not_applicable",
                ],
                "genre_profiles": [
                    "default",
                    "psytrance",
                    "techno",
                    "hiphop",
                    "ambient",
                    "rock",
                    "cinematic",
                ],
                "target_contexts": ["streaming", "club", "festival", "demo", "unknown"],
            },
        ),
        _declaration(
            "routing_audit",
            "Routing Audit",
            "analysis_workflow",
            "active",
            "included_when_current_report_available",
            True,
            requirements=WorkflowRequirementSet(
                "routing_audit",
                (
                    requirement("fl_session_alive", ttl_seconds=2),
                    requirement("static_project_snapshot", ttl_seconds=60),
                    requirement("channel_routing_snapshot", ttl_seconds=60),
                    requirement("routing_snapshot", ttl_seconds=60),
                    requirement(
                        "live_meter_window",
                        required=False,
                        ttl_seconds=2,
                        evidence_mode="live_runtime",
                    ),
                ),
            ),
            panel_id="producer_routing",
            endpoint="/api/workflows/routing-audit",
            action_label="Run Routing Audit",
            safety_note=(
                "Read-only routing audit. Static and meter findings remain evidence-labeled; "
                "cleanup remains proposal-first and confirmation-gated."
            ),
            supported_next_actions=(
                "run_static_routing_snapshot",
                "run_meter_snapshot_proxy",
                "confirm_template_profile",
                "confirm_track_roles",
                "plan_cleanup_after_confirmation",
            ),
            manual_only_actions=(
                "confirm_direct_to_master_intent",
                "confirm_reference_monitor_only",
                "confirm_sidechain_control_not_audible",
                "approve_cleanup_plan",
            ),
            forbidden_actions=(
                "automatic_routing_cleanup",
                "playlist_clip_editing",
                "plugin_loading",
                "automatic_render",
            ),
            metadata={
                "routing_evidence_levels": [
                    "static_routing_snapshot",
                    "meter_snapshot_proxy",
                    "user_confirmed_routing_intent",
                    "verified_cleanup_readback",
                ],
                "plan_gating_statuses": [
                    "blocked_requires_confirmation",
                    "draft_proxy_evidence",
                    "ready_for_user_approval",
                    "no_actionable_findings",
                ],
                "intent_profiles": [
                    "default",
                    "psytrance_stem_bus_template",
                    "mixdown_premaster_template",
                    "recording_session",
                    "sound_design_session",
                    "live_performance",
                    "minimal_sketch",
                    "reference_monitoring",
                ],
            },
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
                    requirement(
                        "live_meter_window",
                        required=False,
                        ttl_seconds=2,
                        evidence_mode="live_runtime",
                    ),
                ),
            ),
            panel_id="producer_low_end",
            endpoint="/api/workflows/low-end-analysis",
            action_label="Run Low-End Safety Check",
            safety_note=(
                "Read-only low-end review. Metadata raises suspicions; rendered "
                "master audio creates proxy claims only; stem-specific conclusions "
                "require role-confirmed stem or bus evidence."
            ),
            supported_next_actions=(
                "low_end.confirm_detected_tracks",
                "low_end.assign_track_roles:*",
                "low_end.choose_genre_profile",
                "low_end.confirm_finding:*",
                "audio.render_master",
                "audio.render_low_end_stems",
                "low_end.approve_fix_plan",
                "low_end.after_fix_render",
            ),
            manual_only_actions=(
                "audio.render_master",
                "audio.render_low_end_stems",
                "low_end.confirm_detected_tracks",
                "low_end.assign_track_roles:*",
                "low_end.choose_genre_profile",
                "low_end.confirm_finding:*",
                "low_end.approve_fix_plan",
                "low_end.after_fix_render",
            ),
            forbidden_actions=(
                "automatic_fl_studio_render",
                "automatic_project_writes",
                "plugin_loading",
                "unsafe_fix_application",
                "stem_specific_claims_from_master_only_audio",
                "final_fix_plan_from_unconfirmed_static_metadata",
            ),
            metadata={
                "evidence_levels": {
                    "1": "static_metadata",
                    "2": "live_playback_data",
                    "3": "rendered_master_audio",
                    "4": "role_confirmed_bus_or_stem_evidence",
                    "5": "deeper_batch_or_multi_source_evidence",
                },
                "genre_profiles": ["default", "psytrance"],
                "future_genre_profiles": [
                    "techno",
                    "drum_and_bass",
                    "hip_hop",
                    "cinematic",
                ],
                "automatic_fl_render": False,
                "master_audio_limit": (
                    "Rendered master audio may create proxy low-end findings but "
                    "must not create kick, bass, sub, or stem-specific causal claims."
                ),
            },
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
            safety_note=("Planned for v3.1+. No Control Center action is available in v3.0."),
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
            safety_note=("Planned after v3.0. Plugin detector settings remain a manual check."),
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
                "Planned after v3.0. Plugin loading and unknown parameter writes remain manual."
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
            safety_note=("Planned after v3.0. Preset loading remains manual."),
            supported_next_actions=("list_preset_names", "suggest_by_name"),
            manual_only_actions=("load_preset", "audition_preset"),
            forbidden_actions=("automatic_preset_loading",),
        ),
        _declaration(
            "audio_evidence",
            "Audio Evidence",
            "evidence_worker",
            "active",
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
            panel_id="producer_audio_evidence",
            endpoint="/api/audio-analysis",
            action_label="Analyze Audio",
            safety_note=(
                "Offline analysis of a user-selected file. Source audio and FL Studio "
                "projects are not modified."
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
