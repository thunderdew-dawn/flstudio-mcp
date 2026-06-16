"""Read-only analysis contracts for workflow reports and observations."""

from .broker import AnalysisBroker, StaticProjectSnapshot, StaticSnapshotPolicy
from .canonical import (
    CanonicalEntity,
    channel_entity_id,
    mixer_count_policy,
    mixer_entity_id,
    pattern_count_policy,
    pattern_entity_id,
    playlist_count_policy,
    playlist_slot_entity_id,
    plugin_entity_id,
)
from .fl_reads import StaticReadSpec, project_fingerprint
from .observations import Observation, ObservationStore
from .reports import analysis_report_to_control_center_legacy, analysis_report_to_workflow_report
from .requirements import (
    COMMON_OBSERVATIONS,
    WorkflowRequirement,
    WorkflowRequirementSet,
    requirement,
)
from .routing import routing_analysis_report_from_legacy_payload
from .schema import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
)
from .scoring import (
    clamp_score,
    confidence_band,
    confidence_from_coverage,
    coverage_score,
    health_from_risk,
    risk_band,
    risk_from_severities,
)

__all__ = [
    "ANALYSIS_REPORT_CONTRACT_VERSION",
    "COMMON_OBSERVATIONS",
    "AnalysisBroker",
    "AnalysisReport",
    "CanonicalEntity",
    "Coverage",
    "EntityRef",
    "Finding",
    "Freshness",
    "Observation",
    "ObservationStore",
    "Prerequisite",
    "StaticProjectSnapshot",
    "StaticReadSpec",
    "StaticSnapshotPolicy",
    "WorkflowRequirement",
    "WorkflowRequirementSet",
    "analysis_report_to_control_center_legacy",
    "analysis_report_to_workflow_report",
    "channel_entity_id",
    "clamp_score",
    "confidence_band",
    "confidence_from_coverage",
    "coverage_score",
    "health_from_risk",
    "mixer_count_policy",
    "mixer_entity_id",
    "pattern_count_policy",
    "pattern_entity_id",
    "playlist_count_policy",
    "playlist_slot_entity_id",
    "plugin_entity_id",
    "project_fingerprint",
    "requirement",
    "risk_band",
    "risk_from_severities",
    "routing_analysis_report_from_legacy_payload",
]
