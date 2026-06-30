#!/usr/bin/env python3
"""Focused tests for the consolidated transport domain tool."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot import protocol, safety  # noqa: E402
from fls_pilot.tools import transport as transport_tools  # noqa: E402


class FakeBridge:
    def __init__(self) -> None:
        self.bpm = 120.0
        self.playing = False
        self.recording = False
        self.calls: list[tuple[str, dict]] = []

    def heartbeat_age(self) -> float:
        return 0.25

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))
        if command == protocol.CMD_PING:
            return {"controller_build": "test-build"}
        if command == protocol.CMD_GET_TEMPO:
            return {"bpm": self.bpm}
        if command == protocol.CMD_SET_TEMPO:
            self.bpm = float(params["bpm"])
            return {"bpm": self.bpm}
        if command == protocol.CMD_PLAY:
            self.playing = True
            return {"playing": self.playing, "recording": self.recording}
        if command == protocol.CMD_GET_PLAY_STATE:
            return {"playing": self.playing, "recording": self.recording}
        if command == protocol.CMD_LIST_PLAYLIST_MARKERS:
            return {
                "state": "live",
                "total": 2,
                "markers": [{"index": 0, "name": "BREAKDOWN"}, {"index": 1, "name": "DROP #1"}],
            }
        if command == protocol.CMD_JUMP_PLAYLIST_MARKER:
            return {"ok": True, "target": {"index": params["index"], "name": "DROP #1"}}
        raise AssertionError(f"unexpected command: {command}")


def _unwrap(result):
    for attr in ("data", "structured_content", "structuredContent"):
        value = getattr(result, attr, None)
        if value is not None:
            return value
    if isinstance(result, (list, tuple)) and result:
        first = result[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return json.loads(text)
        return _unwrap(first)
    return result


@pytest.fixture
def transport_mcp(monkeypatch, tmp_path):
    bridge = FakeBridge()
    monkeypatch.setattr(transport_tools, "get_bridge", lambda: bridge)
    safety._log = safety.ChangeLog(tmp_path / "changes.jsonl")
    mcp = FastMCP(name="transport-test")
    transport_tools.register(mcp)
    return mcp, bridge


def _call(mcp: FastMCP, action: str, params: dict | None = None):
    args = {"action": action}
    if params is not None:
        args["params"] = params
    return _unwrap(asyncio.run(mcp.call_tool("fl_transport", args)))


def test_transport_domain_read_action(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "get_tempo")

    assert result == {"bpm": 120.0}
    assert bridge.calls == [(protocol.CMD_GET_TEMPO, {})]


def test_transport_domain_ping_action(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "ping")

    assert result["alive"] is True
    assert result["controller_build"] == "test-build"
    assert result["heartbeat_age_seconds"] == 0.25
    assert bridge.calls == [(protocol.CMD_PING, {})]


def test_transport_domain_safe_write_action(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "set_tempo", {"bpm": 128})

    assert result["ok"] is True
    assert result["before"] == {"bpm": 120.0}
    assert result["after"] == {"bpm": 128.0}
    assert bridge.calls == [
        (protocol.CMD_GET_TEMPO, {}),
        (protocol.CMD_SET_TEMPO, {"bpm": 128.0}),
        (protocol.CMD_GET_TEMPO, {}),
    ]


def test_transport_domain_transient_action(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "play")

    assert result == {"playing": True, "recording": False}
    assert bridge.calls == [(protocol.CMD_PLAY, {})]


def test_transport_domain_lists_playlist_markers(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "list_markers")

    assert result["total"] == 2
    assert result["markers"][1]["name"] == "DROP #1"
    assert bridge.calls == [(protocol.CMD_LIST_PLAYLIST_MARKERS, {})]


def test_transport_domain_jumps_to_playlist_marker(transport_mcp) -> None:
    mcp, bridge = transport_mcp

    result = _call(mcp, "jump_to_marker", {"index": 1})

    assert result["ok"] is True
    assert result["target"]["index"] == 1
    assert bridge.calls == [(protocol.CMD_JUMP_PLAYLIST_MARKER, {"index": 1})]


def test_transport_domain_rejects_invalid_action(transport_mcp) -> None:
    mcp, _bridge = transport_mcp

    with pytest.raises(Exception, match="unknown operation: transport.not_an_action"):
        _call(mcp, "not_an_action")


def test_transport_domain_rejects_invalid_parameters(transport_mcp) -> None:
    mcp, _bridge = transport_mcp

    with pytest.raises(Exception, match="bpm must be 10..999"):
        _call(mcp, "set_tempo", {"bpm": 1000})
