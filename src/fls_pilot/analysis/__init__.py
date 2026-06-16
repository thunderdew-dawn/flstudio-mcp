"""Read-only analysis contracts for workflow reports and observations."""

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
from .observations import Observation, ObservationStore
from .requirements import (
    COMMON_OBSERVATIONS,
    WorkflowRequirement,
    WorkflowRequirementSet,
    requirement,
)
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
    coverage_score,
    health_from_risk,
    risk_band,
)

__all__ = [
    "ANALYSIS_REPORT_CONTRACT_VERSION",
    "COMMON_OBSERVATIONS",
    "AnalysisReport",
    "CanonicalEntity",
    "Coverage",
    "EntityRef",
    "Finding",
    "Freshness",
    "Observation",
    "ObservationStore",
    "Prerequisite",
    "WorkflowRequirement",
    "WorkflowRequirementSet",
    "channel_entity_id",
    "clamp_score",
    "confidence_band",
    "coverage_score",
    "health_from_risk",
    "mixer_count_policy",
    "mixer_entity_id",
    "pattern_count_policy",
    "pattern_entity_id",
    "playlist_count_policy",
    "playlist_slot_entity_id",
    "plugin_entity_id",
    "requirement",
    "risk_band",
]
