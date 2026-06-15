"""Phase 3 MCP tools: Patterns and Playlist management.

All mutations use safety.safe_write (snapshot -> write -> readback -> rollback).
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import protocol, safety
from ..connection import fetch_all_pages, get_bridge
from .registration import RETIRED_LOW_LEVEL_TOOLS, hide_retired_tools


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

    # ---- Pattern Reads ------------------------------------------------------

    @mcp.tool(annotations={"title": "List patterns", **_RO})
    def fl_pattern_list() -> dict:
        """List all patterns in the project with names, colors, and lengths.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_PATTERN_LIST, "patterns")

    @mcp.tool(annotations={"title": "Get pattern details", **_RO})
    def fl_pattern_get(
        index: Annotated[int, Field(ge=1, description="Pattern index.")],
    ) -> dict:
        """Get one pattern with name, color, and length.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_PATTERN_GET, {"index": index})

    @mcp.tool(annotations={"title": "Get pattern length", **_RO})
    def fl_pattern_get_length(
        index: Annotated[int, Field(ge=1, description="Pattern index.")],
    ) -> dict:
        """Get the length of a pattern in beats and steps.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_PATTERN_GET_LENGTH, {"index": index})

    # ---- Pattern Writes -----------------------------------------------------

    @mcp.tool(annotations={"title": "Select active pattern", **_WR})
    def fl_pattern_select(
        index: Annotated[int, Field(ge=1, description="Pattern index to select.")],
    ) -> dict:
        """Make a pattern active; rollback restores the previously selected pattern.

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="pattern_select",
            scope="patterns_selected",
            command=protocol.CMD_PATTERN_SELECT,
            params={"index": index},
            build_restore=lambda b: {
                "command": protocol.CMD_PATTERN_SELECT,
                "params": {"index": b["selected"]},
            },
        )

    @mcp.tool(annotations={"title": "Rename pattern", **_WR})
    def fl_pattern_rename(
        index: Annotated[int, Field(ge=1, description="Pattern index to rename.")],
        name: Annotated[str, Field(description="New name for the pattern.")],
    ) -> dict:
        """Rename a pattern; rollback restores the previous name.

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="pattern_rename",
            scope=f"pattern:{index}",
            command=protocol.CMD_PATTERN_RENAME,
            params={"index": index, "name": name},
            build_restore=lambda b: {
                "command": protocol.CMD_PATTERN_RENAME,
                "params": {"index": index, "name": b["name"]},
            },
        )

    @mcp.tool(annotations={"title": "Set pattern color", **_WR})
    def fl_pattern_set_color(
        index: Annotated[int, Field(ge=1, description="Pattern index to recolor.")],
        r: Annotated[int, Field(ge=0, le=255, description="Red component.")] = 0,
        g: Annotated[int, Field(ge=0, le=255, description="Green component.")] = 0,
        b: Annotated[int, Field(ge=0, le=255, description="Blue component.")] = 0,
        color: Annotated[int | None, Field(description="Optional FL color integer.")] = None,
    ) -> dict:
        """Set a pattern color; rollback restores the previous color integer.

        Safety: Write-Safe-Required with Rollback.
        """
        params: dict = {"index": index}
        if color is not None:
            params["color"] = int(color)
        else:
            params.update({"r": r, "g": g, "b": b})
        return safety.safe_write(
            get_bridge(),
            tool="pattern_set_color",
            scope=f"pattern:{index}",
            command=protocol.CMD_PATTERN_SET_COLOR,
            params=params,
            build_restore=lambda b: {
                "command": protocol.CMD_PATTERN_SET_COLOR,
                "params": {"index": index, "color": b["color"]["int"]},
            },
        )

    @mcp.tool(annotations={"title": "Set pattern length", **_WR})
    def fl_pattern_set_length(
        index: Annotated[int, Field(ge=1, description="Pattern index to resize.")],
        beats: Annotated[float, Field(gt=0.0, description="New pattern length in beats.")],
    ) -> dict:
        """Set a pattern length; rollback restores the previous length.

        Safety: Write-Safe-Required with Rollback. On FL builds where pattern length
        writes are unavailable, readback failure prevents a persistent change
        from being reported as successful.
        """
        return safety.safe_write(
            get_bridge(),
            tool="pattern_set_length",
            scope=f"pattern:{index}",
            command=protocol.CMD_PATTERN_SET_LENGTH,
            params={"index": index, "beats": float(beats)},
            build_restore=lambda b: {
                "command": protocol.CMD_PATTERN_SET_LENGTH,
                "params": {"index": index, "beats": float(b.get("length", 16))},
            },
        )

    @mcp.tool(annotations={"title": "Find next empty pattern", **_RO})
    def fl_pattern_find_empty() -> dict:
        """Find the first empty pattern index or next index after the current count.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_PATTERN_FIND_EMPTY, {})

    # ---- Playlist Reads -----------------------------------------------------

    @mcp.tool(annotations={"title": "List playlist tracks", **_RO})
    def fl_playlist_list_tracks() -> dict:
        """List playlist tracks with names, colors, mute, solo, and selection state.

        Safety: Read-Only.
        """
        return fetch_all_pages(get_bridge(), protocol.CMD_PLAYLIST_LIST_TRACKS, "tracks")

    @mcp.tool(annotations={"title": "Get playlist track details", **_RO})
    def fl_playlist_get_track(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
    ) -> dict:
        """Get details for a single playlist track using a 1-based index.

        Safety: Read-Only.
        """
        return get_bridge().call(protocol.CMD_PLAYLIST_GET_TRACK, {"index": index})

    # ---- Playlist Writes ----------------------------------------------------

    @mcp.tool(annotations={"title": "Set playlist track mute", **_WR})
    def fl_playlist_set_mute(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
        state: bool,
    ) -> dict:
        """Mute or unmute a playlist track (state=True mutes).

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="playlist_set_mute",
            scope=f"playlist_track:{index}",
            command=protocol.CMD_PLAYLIST_SET_MUTE,
            params={"index": index, "state": state},
            verify=("mute", state),
            build_restore=lambda b: {
                "command": protocol.CMD_PLAYLIST_SET_MUTE,
                "params": {"index": index, "state": b["mute"]},
            },
        )

    @mcp.tool(annotations={"title": "Set playlist track solo", **_WR})
    def fl_playlist_set_solo(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
        state: bool,
    ) -> dict:
        """Solo or unsolo a playlist track (state=True solos).

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="playlist_set_solo",
            scope=f"playlist_track:{index}",
            command=protocol.CMD_PLAYLIST_SET_SOLO,
            params={"index": index, "state": state},
            verify=("solo", state),
            build_restore=lambda b: {
                "command": protocol.CMD_PLAYLIST_SET_SOLO,
                "params": {"index": index, "state": b["solo"]},
            },
        )

    @mcp.tool(annotations={"title": "Set playlist track name", **_WR})
    def fl_playlist_set_name(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
        name: str,
    ) -> dict:
        """Rename a playlist track.

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="playlist_set_name",
            scope=f"playlist_track:{index}",
            command=protocol.CMD_PLAYLIST_SET_NAME,
            params={"index": index, "name": name},
            build_restore=lambda b: {
                "command": protocol.CMD_PLAYLIST_SET_NAME,
                "params": {"index": index, "name": b["name"]},
            },
        )

    @mcp.tool(annotations={"title": "Set playlist track color", **_WR})
    def fl_playlist_set_color(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
        r: Annotated[int, Field(ge=0, le=255, description="Red component.")] = 0,
        g: Annotated[int, Field(ge=0, le=255, description="Green component.")] = 0,
        b: Annotated[int, Field(ge=0, le=255, description="Blue component.")] = 0,
        color: Annotated[
            int | None,
            Field(description="Optional color integer, for example from rollback."),
        ] = None,
    ) -> dict:
        """Set color for a playlist track.

        Safety: Write-Safe-Required with Rollback.
        """
        params: dict = {"index": index}
        if color is not None:
            params["color"] = color
        else:
            params["r"] = r
            params["g"] = g
            params["b"] = b

        return safety.safe_write(
            get_bridge(),
            tool="playlist_set_color",
            scope=f"playlist_track:{index}",
            command=protocol.CMD_PLAYLIST_SET_COLOR,
            params=params,
            build_restore=lambda b: {
                "command": protocol.CMD_PLAYLIST_SET_COLOR,
                "params": {"index": index, "color": b["color"]["int"]},
            },
        )

    @mcp.tool(annotations={"title": "Select playlist track", **_WR})
    def fl_playlist_select_track(
        index: Annotated[int, Field(ge=1, description="Playlist track index.")],
        state: bool = True,
    ) -> dict:
        """Select or deselect a playlist track.

        Safety: Write-Safe-Required with Rollback.
        """
        return safety.safe_write(
            get_bridge(),
            tool="playlist_select_track",
            scope=f"playlist_track:{index}",
            command=protocol.CMD_PLAYLIST_SELECT_TRACK,
            params={"index": index, "state": state},
            verify=("selected", state),
            build_restore=lambda b: {
                "command": protocol.CMD_PLAYLIST_SELECT_TRACK,
                "params": {"index": index, "state": b["selected"]},
            },
        )
