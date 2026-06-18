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
from .contracts import (
    ACCEPTED_ANALYSIS_REPORT_VERSIONS,
    ANALYSIS_REPORT_CONTRACT_VERSION,
    IncompatibleReportVersionError,
    require_analysis_report_version,
)
from .fl_reads import StaticReadSpec, project_fingerprint
from .observations import Observation, ObservationStore
from .reports import (
    analysis_report_for_control_center,
    serialize_analysis_report,
)
from .requirements import (
    COMMON_OBSERVATIONS,
    WorkflowRequirement,
    WorkflowRequirementSet,
    requirement,
)
from .routing import routing_analysis_report_from_legacy_payload
from .runtime import get_analysis_broker, get_report_store
from .schema import (
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
    low_end_health_score,
    mix_health_score,
    organizer_score,
    risk_band,
    risk_from_severities,
    routing_health_score,
)

__all__ = [
    "ANALYSIS_REPORT_CONTRACT_VERSION",
    "ACCEPTED_ANALYSIS_REPORT_VERSIONS",
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
    "IncompatibleReportVersionError",
    "Prerequisite",
    "StaticProjectSnapshot",
    "StaticReadSpec",
    "StaticSnapshotPolicy",
    "WorkflowRequirement",
    "WorkflowRequirementSet",
    "analysis_report_for_control_center",
    "serialize_analysis_report",
    "channel_entity_id",
    "clamp_score",
    "confidence_band",
    "confidence_from_coverage",
    "coverage_score",
    "health_from_risk",
    "get_analysis_broker",
    "get_report_store",
    "low_end_health_score",
    "mix_health_score",
    "mixer_count_policy",
    "mixer_entity_id",
    "organizer_score",
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
    "routing_health_score",
    "require_analysis_report_version",
]
