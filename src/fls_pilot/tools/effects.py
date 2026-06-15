"""Effect-slot and native EQ tools.

All writes go through the safety layer and use scoped snapshots so each
operation is rollbackable.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import FLTimeout, call_with_retry, get_bridge
from .registration import RETIRED_LOW_LEVEL_TOOLS, hide_retired_tools
from .targets import mixer_track_error


def _band_before(before: dict, band: int) -> dict:
    for row in before.get("bands", []):
        if int(row.get("band", -1)) == int(band):
            return row
    return {"band": int(band), "gain": 0.0, "frequency": 0.5, "bandwidth": 1.0, "type": 0}


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

    @mcp.tool(annotations={"title": "Get effect slot details", **_RO})
    def fl_effect_get_slot(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index (0-9).")],
    ) -> dict:
        """Read one mixer effect slot.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot read")
        if error is not None:
            return error
        try:
            return call_with_retry(
                bridge, protocol.CMD_MIXER_GET_SLOT, {"track": track, "slot": slot}, attempts=3
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}

    @mcp.tool(annotations={"title": "List effect slots on a track", **_RO})
    def fl_effect_list_slots(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
    ) -> dict:
        """Read all 10 effect slots on a mixer track.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot listing")
        if error is not None:
            return error
        slots = []
        for slot in range(10):
            try:
                slots.append(
                    call_with_retry(
                        bridge,
                        protocol.CMD_MIXER_GET_SLOT,
                        {"track": track, "slot": slot},
                        attempts=3,
                    )
                )
            except FLTimeout as e:
                return {"ok": False, "retryable": True, "transient": True, "error": str(e)}
        return {"ok": True, "track": track, "slots": slots}

    @mcp.tool(annotations={"title": "Set effect slot mix", **_WR})
    def fl_effect_set_slot_mix(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index (0-9).")],
        mix: Annotated[float, Field(ge=0.0, le=1.0, description="Wet mix 0..1.")],
    ) -> dict:
        """Set one slot mix amount. Rollback restores the previous mix.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot mix write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="effect_set_slot_mix",
            scope=f"effect_slot:{track}:{slot}",
            command=protocol.CMD_MIXER_SET_SLOT_MIX,
            params={"track": track, "slot": slot, "mix": float(mix)},
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_SLOT_MIX,
                "params": {"track": track, "slot": slot, "mix": float(b.get("mix", 0.8))},
            },
        )

    @mcp.tool(annotations={"title": "Get track effect-slots enabled state", **_RO})
    def fl_effect_get_track_slots_enabled(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
    ) -> dict:
        """Read whether all effect slots are enabled on a mixer track.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot enabled read")
        if error is not None:
            return error
        try:
            return call_with_retry(
                bridge, protocol.CMD_MIXER_GET_TRACK_SLOTS, {"track": track}, attempts=3
            )
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}

    @mcp.tool(annotations={"title": "Enable or bypass all track effect slots", **_WR})
    def fl_effect_set_track_slots_enabled(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        enabled: bool,
    ) -> dict:
        """Enable or bypass all effect slots on a track. Rollback restores prior state.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot enabled write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="effect_set_track_slots_enabled",
            scope=f"track_slots:{track}",
            command=protocol.CMD_MIXER_SET_TRACK_SLOTS,
            params={"track": track, "enabled": bool(enabled)},
            verify=("enabled", bool(enabled)),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_TRACK_SLOTS,
                "params": {"track": track, "enabled": bool(b.get("enabled", True))},
            },
        )

    @mcp.tool(annotations={"title": "Enable or bypass one effect slot", **_WR})
    def fl_effect_set_slot_enabled(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        slot: Annotated[int, Field(ge=0, le=9, description="Effect slot index (0-9).")],
        enabled: bool,
    ) -> dict:
        """Enable or bypass one effect slot. Rollback restores prior enabled state.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="effect slot enabled write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="effect_set_slot_enabled",
            scope=f"effect_slot:{track}:{slot}",
            command=protocol.CMD_MIXER_SET_SLOT_ENABLED,
            params={"track": track, "slot": slot, "enabled": bool(enabled)},
            verify=("enabled", bool(enabled)),
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_SLOT_ENABLED,
                "params": {"track": track, "slot": slot, "enabled": bool(b.get("enabled", True))},
            },
        )

    @mcp.tool(annotations={"title": "Get native mixer EQ", **_RO})
    def fl_eq_get(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
    ) -> dict:
        """Read the native mixer EQ bands for one track.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="native mixer EQ read")
        if error is not None:
            return error
        try:
            return call_with_retry(bridge, protocol.CMD_MIXER_GET_EQ, {"track": track}, attempts=3)
        except FLTimeout as e:
            return {"ok": False, "retryable": True, "transient": True, "error": str(e)}

    @mcp.tool(annotations={"title": "Set one native EQ band", **_WR})
    def fl_eq_set_band(
        track: Annotated[int, Field(ge=0, description="Mixer track index.")],
        band: Annotated[int, Field(ge=0, le=2, description="EQ band index (0-2).")],
        gain: Annotated[float | None, Field(description="Optional gain value.")] = None,
        frequency: Annotated[float | None, Field(description="Optional frequency value.")] = None,
        bandwidth: Annotated[float | None, Field(description="Optional bandwidth/Q value.")] = None,
        eq_type: Annotated[int | None, Field(description="Optional EQ type integer.")] = None,
    ) -> dict:
        """Set one native EQ band parameter set. Rollback restores all three bands.

        Safety: Write-Safe-Required with Rollback. Native EQ type/high-pass writes are
        documented-unconfirmed on FL Studio Producer Edition v25.2.5 build
        5055; use this only where readback verifies the changed parameter.
        """
        params: dict = {"track": track, "band": band}
        if gain is not None:
            params["gain"] = float(gain)
        if frequency is not None:
            params["frequency"] = float(frequency)
        if bandwidth is not None:
            params["bandwidth"] = float(bandwidth)
        if eq_type is not None:
            params["type"] = int(eq_type)
        bridge = get_bridge()
        error = mixer_track_error(bridge, track, purpose="native mixer EQ write")
        if error is not None:
            return error
        return safety.safe_write(
            bridge,
            tool="eq_set_band",
            scope=f"mixer_eq:{track}",
            command=protocol.CMD_MIXER_SET_EQ,
            params=params,
            build_restore=lambda b: {
                "command": protocol.CMD_MIXER_SET_EQ,
                "params": {
                    "track": track,
                    "band": band,
                    "gain": float(_band_before(b, band)["gain"]),
                    "frequency": float(_band_before(b, band)["frequency"]),
                    "bandwidth": float(_band_before(b, band)["bandwidth"]),
                    "type": int(_band_before(b, band).get("type", 0)),
                },
            },
        )
