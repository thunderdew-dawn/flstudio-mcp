"""Canonical workflow identities shared by registries and data-only manifests."""

import re

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

CUSTOM_WORKFLOW_ID_RE = re.compile(r"^(user|local)\.[a-z0-9][a-z0-9_.-]{1,80}$")

def is_builtin_workflow_id(value: str) -> bool:
    """Check if the given workflow id is a known built-in identity."""
    try:
        canonical_workflow_id(value)
        return True
    except ValueError:
        return False

def is_custom_workflow_id(value: str) -> bool:
    """Check if the given workflow id matches the custom namespace format."""
    if not value:
        return False
    return bool(CUSTOM_WORKFLOW_ID_RE.match(value))

def canonical_workflow_id(value: str) -> str:
    """Normalize a workflow id without accepting unknown identities."""
    normalized = str(value or "").strip().lower().replace("-", "_")
    canonical = LEGACY_WORKFLOW_ALIASES.get(normalized, normalized)
    if canonical not in CANONICAL_WORKFLOW_IDS:
        raise ValueError(f"unknown workflow id: {value!r}")
    return canonical

def normalize_workflow_id(value: str, *, allow_custom: bool = False) -> str:
    """Normalize a workflow id, optionally accepting valid custom identities."""
    try:
        return canonical_workflow_id(value)
    except ValueError:
        if allow_custom and is_custom_workflow_id(value):
            return value
        raise ValueError(f"invalid or unknown workflow id: {value!r}")
