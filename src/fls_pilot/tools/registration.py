"""Shared helpers for shaping the public MCP runtime surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP


class RuntimeToolFilter:
    """FastMCP facade that leaves retired helper functions unregistered."""

    def __init__(self, mcp: FastMCP, retired_names: set[str]) -> None:
        self._mcp = mcp
        self._retired_names = retired_names

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        register_tool = self._mcp.tool(*args, **kwargs)

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            if fn.__name__ in self._retired_names:
                return fn
            return register_tool(fn)

        return decorator


RETIRED_LOW_LEVEL_TOOLS = {
    # Transport one-off aliases. Use fl_transport(action, params).
    "fl_ping",
    "fl_get_tempo",
    "fl_set_tempo",
    "fl_play",
    "fl_stop",
    "fl_toggle_play",
    "fl_record",
    "fl_get_play_state",
    "fl_get_song_position",
    "fl_set_song_position",
    "fl_get_time_signature",
    "fl_set_time_signature",
    # Mixer/channel core aliases. Use fl_mixer/fl_channel or retained safety tools.
    "fl_get_mixer_state",
    "fl_get_channel_state",
    "fl_set_mixer_volume",
    "fl_set_mixer_pan",
    "fl_set_mixer_mute",
    "fl_set_mixer_solo",
    "fl_set_mixer_name",
    "fl_set_channel_volume",
    "fl_set_channel_pan",
    "fl_set_channel_mute",
    "fl_set_channel_solo",
    "fl_mixer_list_tracks",
    "fl_mixer_get_track",
    "fl_mixer_set_volume",
    "fl_mixer_set_pan",
    "fl_mixer_set_mute",
    "fl_mixer_set_solo",
    "fl_mixer_select_track",
    "fl_mixer_get_route",
    "fl_mixer_set_route",
    "fl_mixer_set_stereo_separation",
    # Channel organizer aliases that are covered by fl_channel.
    "fl_get_channel_details",
    "fl_set_channel_name",
    "fl_set_channel_mixer_track",
    "fl_channel_get_grid",
    "fl_channel_set_grid_bit",
    "fl_channel_set_step_param",
    "fl_channel_set_steps",
    "fl_channel_clear_grid",
    "fl_classify_channels",
    # Routing one-off aliases covered by fl_mixer route actions.
    "fl_get_routing",
    "fl_set_route",
    # Pattern and playlist one-off aliases. Use fl_pattern/fl_playlist.
    "fl_pattern_list",
    "fl_pattern_get",
    "fl_pattern_get_length",
    "fl_pattern_select",
    "fl_pattern_rename",
    "fl_pattern_set_color",
    "fl_pattern_set_length",
    "fl_pattern_find_empty",
    "fl_playlist_list_tracks",
    "fl_playlist_get_track",
    "fl_playlist_set_mute",
    "fl_playlist_set_solo",
    "fl_playlist_set_name",
    "fl_playlist_set_color",
    "fl_playlist_select_track",
    # Effect slot and native EQ one-off aliases. Use fl_effect.
    "fl_effect_get_slot",
    "fl_effect_list_slots",
    "fl_effect_set_slot_mix",
    "fl_effect_get_track_slots_enabled",
    "fl_effect_set_track_slots_enabled",
    "fl_effect_set_slot_enabled",
    "fl_eq_get",
    "fl_eq_set_band",
    # Already-loaded plugin parameter aliases. Use fl_plugin.
    "fl_plugin_list",
    "fl_plugin_get_params",
    "fl_plugin_set_param",
    "fl_plugin_list_params",
    "fl_plugin_get_param",
    # Piano Roll one-off aliases. Use fl_piano_roll.
    "fl_write_piano_roll_notes",
    "fl_quantize_pattern",
    "fl_piano_write_notes",
    "fl_piano_write_chord",
    "fl_piano_clear",
    "fl_piano_quantize",
    "fl_piano_transpose",
    "fl_piano_duplicate",
    "fl_piano_velocity_ramp",
    "fl_piano_probe_return_channel",
    "fl_piano_add_marker",
    "fl_piano_add_time_signature_marker",
    "fl_piano_clear_markers",
    "fl_piano_get_notes",
}


def hide_retired_tools(mcp: FastMCP, retired_names: set[str]) -> RuntimeToolFilter:
    return RuntimeToolFilter(mcp, retired_names)
