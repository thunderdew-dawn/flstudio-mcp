"""Canonical workflow identities shared by registries and data-only manifests."""

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
