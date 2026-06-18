"""Phase 1B MCP tools: plugin parameter control.

- fl_plugin_list(track)              -> filled effect slots on a mixer track
- fl_plugin_get_params(track, slot)  -> every named param (name, value, string)
- fl_plugin_set_param(track, slot, param, value)
       ``param`` may be an int index OR a param name (e.g. "Decay time").
       Names are resolved server-side from the live param list. The write
       routes through ``safety.safe_write`` so it is logged + rollback-able.

Native FL plugins (Fruity Parametric EQ 2, Reeverb 2, ...) expose real param
names and small counts, so name-based addressing is reliable for them. VST/AU
wrappers can report thousands of generic slots; for those prefer int indices.

Values are NORMALISED 0..1 (FL's setParamValue domain). The display string
from fl_plugin_get_params (e.g. '3.6dB', '500Hz') tells you what a given
normalised value maps to -- there is no generic unit->normalised conversion.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import FLTimeout, call_with_retry, fetch_all_pages, get_bridge
from .registration import RETIRED_LOW_LEVEL_TOOLS, hide_retired_tools
from .targets import mixer_track_error


class ParamNotFound(ValueError):
    """Raised when a param name cannot be resolved to a single index."""


def _norm(s) -> str:
    """Lowercase + strip non-alphanumerics, for forgiving name matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def resolve_param_index(bridge, track: int, slot: int, param):
    """Resolve ``param`` (int index or str name) to a concrete ``(index, name)``.

    Integer (or integer-like) params are used directly, with the name looked
    up for the response. String params are matched against the live param
    list: exact normalised match first, then a unique substring match.
    Ambiguous or missing names raise :class:`ParamNotFound` with the candidate
    list, so the caller can correct the spelling rather than poke a wrong knob.
    """
    if isinstance(param, bool):  # guard: bool is an int subclass
        raise ParamNotFound("param must be an index or a name, not a bool")
    if isinstance(param, int) or (isinstance(param, str) and param.lstrip("-").isdigit()):
        idx = int(param)
        one = bridge.call(
            protocol.CMD_PLUGIN_GET_PARAM, {"track": track, "slot": slot, "param": idx}
        )
        return idx, one.get("name", "")

    want = _norm(param)
    if not want:
        raise ParamNotFound("empty param name")

    dump = fetch_all_pages(
        bridge,
        protocol.CMD_PLUGIN_GET_PARAMS,
        "params",
        {"track": track, "slot": slot},
        timeout=10.0,
        attempts=3,
    )
    params = dump.get("params", [])

    exact = [p for p in params if _norm(p["name"]) == want]
    if len(exact) == 1:
        return exact[0]["i"], exact[0]["name"]
    if len(exact) > 1:
        raise ParamNotFound(
            "param name {!r} is ambiguous: {}".format(param, [p["name"] for p in exact])
        )

    subs = [p for p in params if want in _norm(p["name"])]
    if len(subs) == 1:
        return subs[0]["i"], subs[0]["name"]
    if len(subs) > 1:
        raise ParamNotFound(
            "param name {!r} matches several: {}".format(param, [p["name"] for p in subs][:12])
        )

    raise ParamNotFound(
        f"no param named {param!r} on track {track} slot {slot}; "
        f"available: {[p['name'] for p in params][:20]}"
    )


def register(mcp: FastMCP) -> None:
    mcp = hide_retired_tools(mcp, RETIRED_LOW_LEVEL_TOOLS)
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe-required",
    }

    @mcp.tool(annotations={"title": "List plugins on a mixer track", **_RO})
    def fl_plugin_list(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
    ) -> dict:
        """List the filled effect slots (0-9) on a mixer track, with plugin names.

        We cannot load NEW plugins (FL API limit) -- this only reports plugins
        already present in the project.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="plugin slot listing")
        if error is not None:
            return error
        try:
            return call_with_retry(
                bridge, protocol.CMD_PLUGIN_LIST, {"track": track}, timeout=8.0, attempts=3
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}

    @mcp.tool(annotations={"title": "Get plugin parameters", **_RO})
    def fl_plugin_get_params(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index 0-9.")],
        count: Annotated[
            int,
            Field(ge=1, le=32, description="Maximum parameters scanned per SysEx page."),
        ] = 32,
        names_only: Annotated[
            bool,
            Field(description="Return only parameter indices and names."),
        ] = False,
        values: Annotated[
            bool,
            Field(description="Include normalized values and display strings."),
        ] = True,
    ) -> dict:
        """Every named parameter of the plugin in this slot: index, name,
        normalised value (0..1) and FL's display string (e.g. '3.6dB',
        '500Hz'). Returns {"total", "params":[{"i","name","v","s"}, ...]}.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="plugin parameter listing")
        if error is not None:
            return error
        try:
            return fetch_all_pages(
                bridge,
                protocol.CMD_PLUGIN_GET_PARAMS,
                "params",
                {
                    "track": track,
                    "slot": slot,
                    "count": count,
                    "names_only": names_only,
                    "values": values,
                },
                timeout=10.0,
                attempts=3,
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}

    @mcp.tool(annotations={"title": "Set plugin parameter", **_WR})
    def fl_plugin_set_param(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9)],
        param: Annotated[
            int | str, Field(description="Param index (int) or name (str, e.g. 'Decay time').")
        ],
        value: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised 0..1.")],
    ) -> dict:
        """Set one plugin parameter (normalised 0..1). ``param`` may be an
        index or a name; names are resolved from the live param list. The
        change is logged and undo-able via fl_rollback_last_change. Returns
        before/after plus the resolved {index, name}.

        Safety: Write-Safe-Required with Rollback. This only configures already-loaded
        plugins; plugin loading remains manual.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="plugin parameter write")
        if error is not None:
            return error
        idx, name = resolve_param_index(bridge, track, slot, param)
        scope = f"plugin_param:{track}:{slot}:{idx}"
        result = safety.safe_write(
            bridge,
            tool="plugin_set_param",
            scope=scope,
            command=protocol.CMD_PLUGIN_SET_PARAM,
            params={"track": track, "slot": slot, "param": idx, "value": value},
            verify=("v", round(float(value), 4)),
            build_restore=lambda b: {
                "command": protocol.CMD_PLUGIN_SET_PARAM,
                "params": {"track": track, "slot": slot, "param": idx, "value": b["v"]},
            },
        )
        if isinstance(result, dict):
            result["resolved_param"] = {"index": idx, "name": name}
        return result

    @mcp.tool(annotations={"title": "List plugin parameters", **_RO})
    def fl_plugin_list_params(
        track: Annotated[int, Field(ge=0, description="Mixer track index (0 = Master).")],
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index 0-9.")],
    ) -> dict:
        """List all parameters of a plugin. Alias for fl_plugin_get_params.

        Safety: Read-Only.
        """
        return fl_plugin_get_params(track, slot)

    @mcp.tool(annotations={"title": "Get plugin parameter value", **_RO})
    def fl_plugin_get_param(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[int, Field(ge=0, le=9)],
        param: Annotated[int | str, Field(description="Param index (int) or name (str).")],
    ) -> dict:
        """Get the current value and display string of a single plugin parameter.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="plugin parameter read")
        if error is not None:
            return error
        try:
            idx, name = resolve_param_index(bridge, track, slot, param)
        except ParamNotFound as e:
            return {"ok": False, "error": str(e)}

        try:
            val = call_with_retry(
                bridge,
                protocol.CMD_PLUGIN_GET_PARAM,
                {"track": track, "slot": slot, "param": idx},
                timeout=8.0,
                attempts=3,
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}
        return {
            "ok": True,
            "track": track,
            "slot": slot,
            "param_index": idx,
            "param_name": name,
            "value": val.get("v", 0.0),
            "string": val.get("s", ""),
        }

    @mcp.tool(annotations={"title": "Get current plugin preset name", **_RO})
    def fl_plugin_get_preset_name(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[
            int,
            Field(ge=-1, le=9, description="Effect slot index. Use -1 for channel generators."),
        ],
    ) -> dict:
        """Get the current preset name of a plugin.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="plugin preset read")
        if error is not None:
            return error
        try:
            val = call_with_retry(
                bridge,
                protocol.CMD_PLUGIN_GET_PRESET_NAME,
                {"track": track, "slot": slot},
                timeout=8.0,
                attempts=3,
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}
        return {
            "ok": True,
            "track": track,
            "slot": slot,
            "plugin_name": val.get("plugin_name"),
            "preset_name": val.get("name_f3") or val.get("name_f6") or "Unknown",
            "preset_count": val.get("preset_count"),
        }

    @mcp.tool(annotations={"title": "Plan next plugin preset switch", **_RO})
    def fl_plugin_next_preset(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[
            int,
            Field(ge=-1, le=9, description="Effect slot index. Use -1 for channel generators."),
        ],
    ) -> dict:
        """Return manual guidance; preset switching is not exposed as a write tool.

        Safety: Read-Only. FL exposes next/previous preset navigation, but this
        project does not have a plugin-preset restore primitive that satisfies
        the rollback contract.
        """
        current = fl_plugin_get_preset_name(track, slot)
        return {
            "ok": False,
            "api_limited": True,
            "manual_action": "Use the plugin UI to switch to the next preset.",
            "reason": "Plugin preset navigation has no verified MCP rollback path.",
            "current": current,
        }

    @mcp.tool(annotations={"title": "Plan previous plugin preset switch", **_RO})
    def fl_plugin_prev_preset(
        track: Annotated[int, Field(ge=0)],
        slot: Annotated[
            int,
            Field(ge=-1, le=9, description="Effect slot index. Use -1 for channel generators."),
        ],
    ) -> dict:
        """Return manual guidance; preset switching is not exposed as a write tool.

        Safety: Read-Only. FL exposes next/previous preset navigation, but this
        project does not have a plugin-preset restore primitive that satisfies
        the rollback contract.
        """
        current = fl_plugin_get_preset_name(track, slot)
        return {
            "ok": False,
            "api_limited": True,
            "manual_action": "Use the plugin UI to switch to the previous preset.",
            "reason": "Plugin preset navigation has no verified MCP rollback path.",
            "current": current,
        }
