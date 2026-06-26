"""Agent-facing workflow guidance and read-only fl_get_workflow_context tool.

The ``WORKFLOW_REGISTRY`` dict is the single source of truth for agent
workflow guidance:
- which resources an agent should read for a given workflow,
- which tools the agent may call,
- which tools require explicit user approval before execution,
- what cannot be automated (hard API limits).

Both ``src/fls_pilot/prompts.py`` and the ``fl_get_workflow_context`` tool
import this registry so that prompts and context responses never drift apart.
"""

from __future__ import annotations

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Agent-facing workflow guidance registry
# ---------------------------------------------------------------------------

WORKFLOW_REGISTRY: dict[str, dict] = {
    "mix_review": {
        "description": "Diagnose the current mix for headroom, clipping, low-end, and stereo issues.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://status",
            "fl://mixer",
        ],
        "tools_to_use": [
            "fl_review_mix",
            "fl_review_low_end_stereo",
            "fl_mix_watch_start",
            "fl_mix_watch_stop",
            "fl_get_track_level",
        ],
        "approval_required_for": [
            "fl_apply_mix_adjustment",
            "fl_gain_stage",
        ],
        "stop_rules": [
            "Do not mutate FL Studio state without explicit user approval.",
            "Do not guess normalized values, dB mappings, or plugin parameters.",
            "Prefer high-level tools (fl_review_mix) before raw API calls.",
            "Stop if bridge is down or project state is unclear.",
        ],
        "unsupported": [
            "plugin loading",
            "WAV rendering",
            "deep playlist clip editing",
            "audio track creation",
        ],
    },
    "routing_review": {
        "description": "Review mixer routing, bus structure, and send/return assignments.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://status",
            "fl://mixer",
        ],
        "tools_to_use": [
            "fl_review_routing",
            "fl_get_routing_all",
            "fl_get_channel_routing",
            "fl_plan_routing_cleanup",
        ],
        "approval_required_for": [
            "fl_apply_routing_cleanup",
            "fl_apply_bus_layout",
        ],
        "stop_rules": [
            "Do not mutate routing without explicit user approval.",
            "Do not guess track indices or routing targets.",
            "Prefer fl_review_routing before any cleanup plan.",
            "Stop if target selection or rollback is unclear.",
        ],
        "unsupported": [
            "plugin loading",
            "WAV rendering",
            "playlist clip editing",
        ],
    },
    "project_organizer": {
        "description": "Plan and apply naming, colors, grouping, and routing cleanup.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://channels",
            "fl://mixer",
            "fl://patterns",
        ],
        "tools_to_use": [
            "fl_analyze_project_organization",
            "fl_plan_project_cleanup",
            "fl_detect_cleanup_candidates",
            "fl_group_tracks",
        ],
        "approval_required_for": [
            "fl_apply_project_cleanup_step",
            "fl_apply_naming_standard",
            "fl_apply_color_standard",
        ],
        "stop_rules": [
            "Apply only one approved cleanup step at a time.",
            "Do not delete patterns or clips.",
            "Do not edit playlist clip placement.",
            "Stop if color mapping, routing, or readback is unclear.",
        ],
        "unsupported": [
            "pattern/clip deletion",
            "playlist clip placement",
            "plugin loading",
            "WAV rendering",
        ],
    },
    "project_preflight": {
        "description": "Check project health and export readiness before release.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://status",
        ],
        "tools_to_use": [
            "fl_project_health_overview",
            "fl_check_project_preflight",
            "fl_get_guided_cleanup_context",
            "fl_export_readiness_report",
        ],
        "approval_required_for": [
            "fl_apply_project_cleanup_step",
        ],
        "stop_rules": [
            "Do not apply any fix without explicit user approval.",
            "Do not render or export audio automatically.",
            "Prioritize export blockers before cosmetic issues.",
        ],
        "unsupported": [
            "WAV rendering",
            "plugin loading",
            "playlist clip editing",
            "project save-as automation",
        ],
    },
    "plugin_chain": {
        "description": "Plan or configure an FX chain using already-loaded plugins.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://mixer",
            "fls://capabilities/not-possible",
        ],
        "tools_to_use": [
            "fl_list_chains",
            "fl_list_installed_plugins",
            "fl_setup_chain",
            "fl_effect(action=list_slots)",
        ],
        "approval_required_for": [
            "fl_setup_chain (parameter writes)",
            "fl_effect(action=set_slot_mix)",
            "fl_effect(action=set_slot_enabled)",
        ],
        "stop_rules": [
            "Cannot load new VST/AU plugin instances automatically.",
            "Do not guess normalized plugin parameter values.",
            "Use Knowledgebase evidence before any parameter write.",
            "Flag missing plugins as manual steps for the user.",
        ],
        "unsupported": [
            "plugin loading / VST instantiation",
            "WAV rendering",
            "deep audio clip editing",
        ],
    },
    "composition": {
        "description": "Write melodic or harmonic content to the Piano Roll using scales or ragas.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fl://channels",
            "fl://patterns",
        ],
        "tools_to_use": [
            "fl_scale_list",
            "fl_scale_get",
        ],
        "approval_required_for": [
            "fl_write_raga_melody",
            "fl_write_raga_chords",
            "fl_piano_roll (write_notes)",
        ],
        "stop_rules": [
            "Always show note preview to user before writing.",
            "Do not write to Piano Roll without explicit user confirmation.",
            "Stop if target pattern or channel is not confirmed.",
        ],
        "unsupported": [
            "WAV rendering",
            "audio track creation",
            "playlist clip placement",
        ],
    },
    "audio_analysis": {
        "description": "Analyze audio files for tempo, key, and melody; optionally write MIDI.",
        "resources_to_read": [
            "fl://agent-briefing",
            "fls://capabilities/supported",
            "fls://capabilities/not-possible",
        ],
        "tools_to_use": [
            "fl_audio_analysis",
            "fl_extract_melody",
            "fl_inspect_audio_clips",
        ],
        "approval_required_for": [
            "fl_piano_roll (write extracted melody)",
        ],
        "stop_rules": [
            "Do not write to Piano Roll without explicit user confirmation.",
            "Do not import audio clips into playlist automatically.",
            "Flag low-confidence extractions before proposing any write.",
        ],
        "unsupported": [
            "audio track creation in FL playlist",
            "WAV rendering",
            "direct audio clip import",
        ],
    },
}

# ---------------------------------------------------------------------------
# Tool: fl_get_workflow_context (read-only)
# ---------------------------------------------------------------------------


def fl_get_workflow_context(workflow: str, detail: str = "compact") -> dict:
    """Return the recommended resources, tools, approval rules, and hard limits
    for a named workflow.

    This tool is **read-only**: it never mutates FL Studio state.

    Args:
        workflow: One of the supported workflow keys:
            mix_review, routing_review, project_organizer, project_preflight,
            plugin_chain, composition, audio_analysis.
        detail: ``"compact"`` (default) returns only essential fields.
            ``"full"`` returns the complete registry entry.

    Returns:
        A dict with keys:
        - ``workflow``: the resolved workflow name
        - ``description``: human-readable purpose
        - ``resources_to_read``: MCP resource URIs to pull before acting
        - ``tools_to_use``: read-only or planning tools for this workflow
        - ``approval_required_for``: tools that require explicit user approval
        - ``stop_rules``: safety constraints
        - ``unsupported``: actions that cannot be automated

    Notes:
        This tool is the read-only companion to the MCP Prompts layer.
        It does not execute any workflow step. Use it as an orientation
        tool before choosing which resources and tools to call.
    """
    if workflow not in WORKFLOW_REGISTRY:
        available = sorted(WORKFLOW_REGISTRY.keys())
        return {
            "error": f"Unknown workflow {workflow!r}.",
            "available_workflows": available,
        }

    entry = WORKFLOW_REGISTRY[workflow]

    if detail == "full":
        return {"workflow": workflow, **entry}

    # compact: drop the description to keep token cost low
    return {
        "workflow": workflow,
        "resources_to_read": entry["resources_to_read"],
        "tools_to_use": entry["tools_to_use"],
        "approval_required_for": entry["approval_required_for"],
        "stop_rules": entry["stop_rules"],
        "unsupported": entry["unsupported"],
    }


def register(mcp: FastMCP) -> None:
    mcp.tool()(fl_get_workflow_context)
