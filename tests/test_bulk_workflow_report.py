#!/usr/bin/env python3
"""Tests for bulk tools workflow report integration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot import protocol
from fls_pilot.tools import bulk


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


class MixFixBridge:
    def __init__(self) -> None:
        self.track = {"index": 4, "name": "Lead", "mute": False, "solo": False}
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))
        if command == protocol.CMD_MIXER_LIST_TRACKS:
            return {"tracks": [
                {"i": 0, "name": "Master", "mute": False, "solo": False},
                {"i": 1, "name": "Kick", "mute": False, "solo": False},
                {"i": 2, "name": "Snare", "mute": False, "solo": False},
                {"i": 3, "name": "Lead Vox", "mute": False, "solo": False},
            ]}
        return {"ok": True}


def test_fl_solo_tracks_requires_approval(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)

    result = mcp.tools["fl_solo_tracks"](category="drums", approved=False)

    assert result["mode"] == "approval_required"
    assert len(result["proposed_changes"]) == 1
    assert result["proposed_changes"][0]["proposed_state"]["approved"] is True


def test_fl_solo_tracks_applied(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)

    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [{"track": 3, "mute": False}],
            "after": [{"track": 3, "mute": True}],
            "change_id": "chg_bulk_solo",
            "rollback": {"rollback_unit": "bulk_solo_tracks"},
            "undo": "call fl_rollback_change(change_id='chg_bulk_solo')",
        }

    monkeypatch.setattr(bulk.safety, "safe_write_group", mock_safe_write_group)

    result = mcp.tools["fl_solo_tracks"](category="drums", approved=True)

    assert result["mode"] == "applied"
    assert len(result["applied_changes"]) == 1
    applied = result["applied_changes"][0]
    assert applied["id"] == "bulk_solo_tracks_3"
    assert applied["change_id"] == "chg_bulk_solo"
    assert applied["rollback"]["rollback_unit"] == "bulk_solo_tracks"
    assert applied["rollback_command"] == "call fl_rollback_change(change_id='chg_bulk_solo')"
    assert applied["requested_change"] == {"track": 3, "state": True}
    assert applied["readback_ok"] is True


def test_fl_solo_tracks_noop(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)

    # Make all others muted so no mute is needed
    bridge.call = lambda cmd, params=None: {"tracks": [
        {"i": 0, "name": "Master", "mute": False, "solo": False},
        {"i": 1, "name": "Kick", "mute": False, "solo": False},
        {"i": 2, "name": "Snare", "mute": False, "solo": False},
        {"i": 3, "name": "Lead Vox", "mute": True, "solo": False},
    ]} if cmd == protocol.CMD_MIXER_LIST_TRACKS else {"ok": True}

    result = mcp.tools["fl_solo_tracks"](category="drums", approved=False)

    assert result["mode"] == "no_op"
    assert result["ok"] is True


def test_fl_mute_tracks_requires_approval(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)

    result = mcp.tools["fl_mute_tracks"](category="drums", approved=False)

    assert result["mode"] == "approval_required"


def test_fl_mute_tracks_applied(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)

    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [{"track": 1, "mute": False}, {"track": 2, "mute": False}],
            "after": [{"track": 1, "mute": True}, {"track": 2, "mute": True}],
            "change_id": "chg_bulk_mute",
            "rollback": {"rollback_unit": "bulk_mute_tracks"},
            "undo": "call fl_rollback_change(change_id='chg_bulk_mute')",
        }

    monkeypatch.setattr(bulk.safety, "safe_write_group", mock_safe_write_group)

    result = mcp.tools["fl_mute_tracks"](category="drums", approved=True)

    assert result["mode"] == "applied"
    assert [row["change_id"] for row in result["applied_changes"]] == [
        "chg_bulk_mute",
        "chg_bulk_mute",
    ]
    assert result["applied_changes"][0]["rollback"]["rollback_unit"] == "bulk_mute_tracks"


def test_fl_clear_mute_solo_requires_approval(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)
    bridge.call = lambda cmd, params=None: {"tracks": [
        {"i": 0, "name": "Master", "mute": False, "solo": False},
        {"i": 1, "name": "Kick", "mute": True, "solo": False},
    ]} if cmd == protocol.CMD_MIXER_LIST_TRACKS else {"ok": True}

    result = mcp.tools["fl_clear_mute_solo"](approved=False)

    assert result["mode"] == "approval_required"


def test_fl_clear_mute_solo_applied(monkeypatch):
    mcp = MockMCP()
    bulk.register(mcp)
    bridge = MixFixBridge()
    monkeypatch.setattr(bulk, "get_bridge", lambda: bridge)
    bridge.call = lambda cmd, params=None: {"tracks": [
        {"i": 0, "name": "Master", "mute": False, "solo": False},
        {"i": 1, "name": "Kick", "mute": True, "solo": False},
    ]} if cmd == protocol.CMD_MIXER_LIST_TRACKS else {"ok": True}

    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [{"track": 1, "mute": True}],
            "after": [{"track": 1, "mute": False}],
            "change_id": "chg_clear",
            "rollback": {"rollback_unit": "clear_mute_solo"},
            "undo": "call fl_rollback_change(change_id='chg_clear')",
        }

    monkeypatch.setattr(bulk.safety, "safe_write_group", mock_safe_write_group)

    result = mcp.tools["fl_clear_mute_solo"](approved=True)

    assert result["mode"] == "applied"
    applied = result["applied_changes"][0]
    assert applied["change_id"] == "chg_clear"
    assert applied["rollback"]["rollback_unit"] == "clear_mute_solo"
    assert applied["requested_change"] == {"track": 1, "state": False}
