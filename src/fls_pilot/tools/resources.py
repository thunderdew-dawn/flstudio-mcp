"""MCP resources -- read-only project context the LLM assistant can pull WITHOUT a tool call.

All reuse existing (budget-paginated) reads, so no new heavy controller loops.
Kept COMPACT: summaries + counts, capped, with a note pointing to the detail
tool when a list is large. Every resource degrades gracefully if the bridge is
down (returns an {error} dict instead of throwing) so an auto-pull never breaks.

Static ``fls://docs/...`` resources serve compact bundled Markdown excerpts so
local LLMs can quickly orient without reading repository files.
``fls://capabilities/...`` resources document hard FL API limits.
"""

from __future__ import annotations

import logging
from importlib import resources

from fastmcp import FastMCP

from .. import protocol
from ..connection import fetch_all_pages, get_bridge

logger = logging.getLogger("fls_pilot.resources")

_DOCS_PACKAGE = "fls_pilot.context.docs"

_CAPS = {
    "channels": 24,
    "tracks": 28,
    "patterns": 80,
}

_DOMAIN_TOOLS = {
    "fl_transport": [
        "ping",
        "get_tempo",
        "set_tempo",
        "get_play_state",
        "play",
        "stop",
        "pause",
        "toggle_play",
        "record",
        "get_song_position",
        "set_song_position",
        "get_time_signature",
        "set_time_signature",
        "list_markers",
        "jump_to_marker",
        "jump_marker_relative",
    ],
    "fl_mixer": [
        "list",
        "get",
        "select",
        "get_route",
        "set_route",
        "set_volume",
        "set_pan",
        "set_mute",
        "set_solo",
        "set_stereo_separation",
    ],
    "fl_channel": [
        "list",
        "get",
        "get_selected",
        "get_steps",
        "classify",
        "select",
        "set_color",
        "set_mute",
        "set_mixer_target",
        "set_name",
        "set_pan",
        "set_solo",
        "set_steps",
        "set_volume",
    ],
    "fl_pattern": [
        "list",
        "get",
        "get_length",
        "get_selected",
        "find_empty",
        "select",
        "rename",
        "set_color",
        "set_length",
    ],
    "fl_playlist": [
        "list",
        "get",
        "select",
        "set_color",
        "set_mute",
        "set_name",
        "set_solo",
    ],
    "fl_effect": [
        "get_slot",
        "list_slots",
        "get_track_slots_enabled",
        "set_slot_enabled",
        "set_slot_mix",
        "set_track_slots_enabled",
        "get_eq",
        "set_eq_band",
    ],
    "fl_plugin": ["list", "list_params", "get_param", "set_param"],
    "fl_piano_roll": [
        "write_notes",
        "write_chord",
        "clear",
        "quantize",
        "transpose",
        "duplicate",
        "velocity_ramp",
        "markers",
        "readback_limits",
    ],
    "fl_batch": ["strict registry reads", "homogeneous persistent writes"],
}

_WORKFLOWS = [
    "project health/preflight",
    "mix review",
    "routing review",
    "project organizer",
    "audio analysis",
    "MIDI export",
    "Knowledgebase tools",
]

_SAFETY_RULES = [
    "Default safe UX: scan/read-only first, explain findings, then propose one "
    "reversible change with a risk level.",
    "Before any write, ask for explicit confirmation of the exact change.",
    "After confirmation, apply one reversible change only, readback where "
    "supported, report before/after plus rollback/change_id, then stop.",
    "Use Knowledgebase evidence before values, ranges, REC events, plugin params, or MIDI data.",
    "Prefer workflow/domain tools over legacy one-off aliases or raw FL API calls.",
    "No persistent FL write without snapshot, smallest write, readback, changelog, "
    "and rollback path.",
    "If API support, readback, or rollback is unclear, use read-only, dry-run, "
    "probe-only, or manual guidance.",
]

_STOP_RULES = [
    "Do not guess normalized values, dB/Hz mappings, track indexing, REC IDs, "
    "or plugin parameter indices.",
    "Do not edit MIDI/TCP ports unless the user explicitly asks for setup troubleshooting.",
    "Do not auto-load plugins, delete patterns/clips, edit playlist clips, render, "
    "save-as, or use raw escape hatches.",
    "Do not promise Stretch Pro, Normalize, native EQ type, Piano Roll readback, "
    "or other unsupported API behavior.",
]


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _summary(full, key, detail_tool):
    items = full.get(key) or []
    total = full.get("total", len(items))
    cap = _CAPS.get(key, 24)
    out = {"total": total, "shown": min(len(items), cap), key: items[:cap]}
    if len(items) > cap:
        out["truncated"] = True
        out["note"] = f"showing first {cap} of {total} -- call {detail_tool} for the rest"
    return out


def _bridge_summary() -> dict:
    b = get_bridge()
    wait = getattr(b, "wait_for_heartbeat", None)
    if callable(wait):
        wait(timeout=1.0)
    alive = b.is_alive()
    out = {
        "alive": alive,
        "heartbeat_age_seconds": b.heartbeat_age() if alive else None,
    }
    if alive:
        ps = b.call(protocol.CMD_GET_PROJECT_STATE)
        out.update(
            {
                "fl_version": ps.get("fl_version"),
                "tempo_bpm": ps.get("tempo_bpm"),
                "playing": ps.get("playing"),
            }
        )
    return out


def register(mcp: FastMCP) -> None:

    @mcp.resource("fl://agent-briefing")
    def agent_briefing() -> dict:
        """Compact safety-first orientation for FLStudioPilot agents."""

        return {
            "purpose": "Start here before choosing tools or touching FL Studio state.",
            "startup": [
                "Read this resource, then fl://status.",
                "Use current workflow/domain tools before broad reads.",
                "Search Knowledgebase with kb_search/kb_get before values, "
                "plugin params, REC events, or MIDI data.",
            ],
            "bridge": _safe(_bridge_summary),
            "domain_tools": _DOMAIN_TOOLS,
            "workflows": _WORKFLOWS,
            "token_strategy": [
                "Use MCP resources and kb_search/kb_get before any repository file reads.",
                "Repository files are for maintenance tasks, not normal FL Studio runtime use.",
                "Use capped resources for orientation; call detail tools only for the active task.",
                "Use fl_batch for strict registry reads or safe homogeneous persistent writes.",
            ],
            "safety_rules": _SAFETY_RULES,
            "stop_rules": _STOP_RULES,
        }

    @mcp.resource("fl://status")
    def status() -> dict:
        """Bridge alive + a cheap transport/tempo snapshot."""
        return _safe(_bridge_summary)

    @mcp.resource("fl://project")
    def project() -> dict:
        """Tempo, transport, and channel/mixer/pattern counts."""
        def _do():
            b = get_bridge()
            out = dict(b.call(protocol.CMD_GET_PROJECT_STATE))
            out["metadata"] = b.call(protocol.CMD_GET_PROJECT_METADATA)
            return out

        return _safe(_do)

    @mcp.resource("fl://transport")
    def transport() -> dict:
        """Live transport: playing/recording, song position, tempo."""

        def _do():
            b = get_bridge()
            out = dict(b.call(protocol.CMD_GET_PLAY_STATE))
            out["song_position"] = b.call(protocol.CMD_GET_SONG_POS)
            out["tempo"] = b.call(protocol.CMD_GET_TEMPO)
            out["markers"] = b.call(protocol.CMD_LIST_PLAYLIST_MARKERS)
            return out

        return _safe(_do)

    @mcp.resource("fl://channels")
    def channels() -> dict:
        """Channel-rack summary (name + vol/pan/mute/solo), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_CHANNEL_LIST, "channels"),
                "channels",
                'fl_channel(action="list")',
            )
        )

    @mcp.resource("fl://mixer")
    def mixer() -> dict:
        """Mixer-track summary (name + vol/pan/mute/solo), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_MIXER_LIST_TRACKS, "tracks"),
                "tracks",
                'fl_mixer(action="list")',
            )
        )

    @mcp.resource("fl://patterns")
    def patterns() -> dict:
        """Pattern list (1-based index + name), capped."""
        return _safe(
            lambda: _summary(
                fetch_all_pages(get_bridge(), protocol.CMD_PATTERN_LIST, "patterns"),
                "patterns",
                'fl_pattern(action="list")',
            )
        )

    # ------------------------------------------------------------------
    # Static doc resources  fls://docs/…
    # Compact excerpts from canonical Markdown files.
    # Max ~3 KB each; longer docs are summarised with a kb_get pointer.
    # ------------------------------------------------------------------

    def _read_doc(filename: str, max_chars: int = 3000) -> dict:
        """Load a bundled Markdown file as a compact MCP resource."""
        p = resources.files(_DOCS_PACKAGE) / filename
        try:
            text = p.read_text(encoding="utf-8")
            if len(text) > max_chars:
                text = text[:max_chars] + (
                    "\n\n[Truncated. Use the matching MCP resource, prompt, "
                    "or Knowledgebase tool for complete task-specific context.]"
                )
            return {"source": f"{_DOCS_PACKAGE}/{filename}", "content": text}
        except FileNotFoundError:
            return {"error": f"Bundled doc not found: {filename}"}
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    @mcp.resource("fls://docs/safety-contract")
    def docs_safety_contract() -> dict:
        """Compact safety contract: what the agent may and may not do."""
        return _read_doc("safety-contract.md")

    @mcp.resource("fls://docs/api-capability-audit")
    def docs_api_capability_audit() -> dict:
        """Compact excerpt from the FL API capability audit."""
        return _read_doc("api-capability-audit.md", max_chars=2500)

    @mcp.resource("fls://docs/default-safe-ux")
    def docs_default_safe_ux() -> dict:
        """Default safe UX rules for write-capable workflows."""
        return _read_doc("default-safe-ux.md")

    @mcp.resource("fls://docs/runtime-usage")
    def docs_runtime_usage() -> dict:
        """Startup protocol and tool-choice matrix for runtime agents."""
        return _read_doc("runtime-usage.md")

    @mcp.resource("fls://docs/knowledgebase-protocol")
    def docs_knowledgebase_protocol() -> dict:
        """Knowledgebase protocol: when and how to record findings."""
        return _read_doc("knowledgebase-protocol.md")

    @mcp.resource("fls://docs/tool-policy")
    def docs_tool_policy() -> dict:
        """MCP tool policy: hierarchy, examples of allowed vs forbidden calls."""
        return _read_doc("tool-policy.md")

    # ------------------------------------------------------------------
    # Capability resources  fls://capabilities/…
    # Pure Python dicts — fast, always available, no file I/O.
    # ------------------------------------------------------------------

    @mcp.resource("fls://capabilities/supported")
    def capabilities_supported() -> dict:
        """What the MCP server can do (confirmed supported workflows)."""
        return {
            "supported": [
                "Mix Review (fl_review_mix, fl_review_low_end_stereo, fl_mix_watch_start/stop)",
                "Routing Review (fl_review_routing, fl_plan_routing_cleanup)",
                "Project Cleanup Planning (fl_plan_project_cleanup, fl_apply_project_cleanup_step)",
                "Project Health & Export Preflight (fl_project_health_overview, fl_check_project_preflight)",
                "Piano Roll write after explicit user approval (fl_piano_roll write_notes, fl_write_raga_melody, fl_write_raga_chords)",
                "MIDI Export from arrangement spec (fl_export_midi)",
                "Audio Feature Jobs — level, dynamics, bands, activity, stereo proxies "
                "(fl_audio_analysis)",
                "Melody Extraction from audio (fl_extract_melody)",
                "Knowledgebase Search & Retrieval (kb_search, kb_get, kb_get_many, kb_get_workflow_pack)",
                "Parameter Validation via Knowledgebase (kb_get_parameter_spec, kb_get_conversion)",
                "Plugin FX chain planning using already-loaded plugins (fl_setup_chain, fl_list_chains)",
                "Genre/recipe chain setup (fl_list_chains, fl_setup_chain)",
                "Gain Staging & Reference Matching (fl_gain_stage, fl_reference_match)",
                "Bulk mute/solo (fl_mute_tracks, fl_solo_tracks)",
                "Track/channel coloring (fl_set_track_color, fl_set_channel_color)",
                "Arrangement: pattern create/clone + markers (fl_arrange_new_pattern, fl_arrange_clone_pattern)",
                "Scale/Raga lookup (fl_scale_list, fl_scale_get)",
            ],
            "note": (
                "All write actions require explicit user approval before execution. "
                "Read fls://capabilities/write-safety for the exact protocol."
            ),
        }

    @mcp.resource("fls://capabilities/not-possible")
    def capabilities_not_possible() -> dict:
        """Hard FL API limits: actions that cannot be automated."""
        return {
            "not_possible": [
                {
                    "action": "Load new VST/AU plugin instances",
                    "reason": "FL Studio API does not expose plugin instantiation to controller scripts.",
                    "workaround": "User must load the plugin manually in FL Studio first.",
                },
                {
                    "action": "Render audio / WAV export",
                    "reason": "FL Studio's render/export pipeline is not accessible via MIDI SysEx bridge.",
                    "workaround": "User must trigger File > Export in FL Studio manually.",
                },
                {
                    "action": "Place, move, or delete playlist clips",
                    "reason": "Playlist clip placement API is not reliably supported via the controller bridge.",
                    "workaround": "User arranges clips manually; server can build patterns and add markers.",
                },
                {
                    "action": "Edit deep audio clip properties (pitch, stretch mode, warp markers)",
                    "reason": "Audio clip internals are not exposed through the controller API.",
                    "workaround": "Manual editing in FL Studio Edison or playlist properties.",
                },
                {
                    "action": "Guess normalized plugin/EQ parameter values",
                    "reason": "Mapping between UI values and normalized API values is non-linear and plugin-specific.",
                    "workaround": "Use kb_get_parameter_spec or kb_get_conversion for verified mappings only.",
                },
                {
                    "action": "Project open / save-as / new project automation",
                    "reason": "File I/O commands are not exposed to controller scripts.",
                    "workaround": "User manages project files in FL Studio.",
                },
                {
                    "action": "Piano Roll readback after write (in all FL versions)",
                    "reason": "Piano Roll state readback is unreliable or unsupported in some FL versions.",
                    "workaround": "Report note count from write response; user verifies visually.",
                },
            ],
        }

    @mcp.resource("fls://capabilities/api-limits")
    def capabilities_api_limits() -> dict:
        """Hard numerical and structural limits of the FL bridge API."""
        return {
            "hard_limits": [
                "Mixer track indices: 0–125 (FL 20.9+); 0–63 in older versions.",
                "Channel rack slot count: project-dependent, typically 0–499.",
                "Pattern count: up to ~500 in FL 20.9; older versions vary.",
                "Piano Roll note velocity: 0–127 (MIDI standard).",
                "Piano Roll note duration: ticks; 96 ticks = 1 beat at default PPQ.",
                "Tempo range: ~10–999 BPM (exact limits FL-version-dependent).",
                "Mixer volume: normalized 0.0–1.0 where 1.0 = 100% / 0 dB.",
                "Mixer pan: normalized 0.0–1.0 where 0.5 = center.",
                "EQ gain: normalized; see kb_get_parameter_spec for band-specific mapping.",
                "EQ frequency: normalized; see kb_get_parameter_spec for Hz mapping.",
            ],
            "do_not_guess": (
                "Never interpolate or guess normalized API values. "
                "Use kb_get_parameter_spec or kb_get_conversion for verified mappings. "
                "Use kb_search before any value-dependent API call."
            ),
        }

    @mcp.resource("fls://capabilities/write-safety")
    def capabilities_write_safety() -> dict:
        """Write-safety protocol: snapshot, confirmation, readback, rollback."""
        return {
            "protocol": [
                "1. Scan / read-only first. Explain findings before proposing writes.",
                "2. Propose exactly one reversible change with a risk level.",
                "3. Ask for explicit user confirmation of the exact change.",
                "4. After confirmation: apply one reversible change only.",
                "5. Readback where supported; report before/after plus rollback/change_id.",
                "6. Stop after the verified change and wait for user direction.",
            ],
            "snapshot_requirement": (
                "Every persistent write must be preceded by a scoped snapshot "
                "or change_id that enables rollback. Use fl_take_snapshot or the "
                "change history tools."
            ),
            "approval_gates": [
                "fl_apply_mix_adjustment",
                "fl_apply_routing_cleanup",
                "fl_apply_bus_layout",
                "fl_apply_project_cleanup_step",
                "fl_apply_naming_standard",
                "fl_apply_color_standard",
                "fl_piano_roll (write_notes, write_chord, clear, transpose, velocity_ramp)",
                "fl_write_raga_melody",
                "fl_write_raga_chords",
                "fl_gain_stage",
                "fl_effect (set_slot_mix, set_slot_enabled, set_eq_band)",
                "fl_plugin (set_param)",
                "fl_mixer (set_volume, set_pan, set_mute, set_solo, set_route)",
                "fl_channel (set_volume, set_pan, set_mute, set_steps, set_mixer_target)",
            ],
            "never_auto_execute": (
                "MCP Prompts do not execute any write tool automatically. "
                "A prompt invocation is a guided template, not a write approval."
            ),
        }
