#!/usr/bin/env python3
"""Tests for routing tools workflow report integration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot import protocol
from fls_pilot.tools import routing


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
        self.track = {"index": 4, "name": "Lead", "vol_norm": 0.75, "vol_db": -1.0}
        self.calls: list[tuple[str, dict]] = []

    def call(self, command: str, params: dict | None = None) -> dict:
        params = dict(params or {})
        self.calls.append((command, params))
        if command == protocol.CMD_MIXER_GET_TRACK:
            return dict(self.track)
        if command == protocol.CMD_MIXER_SET_ROUTE:
            return {"ok": True}
        if command == protocol.CMD_MIXER_SET_NAME:
            return {"ok": True}
        return {"ok": True}


def test_fl_plan_routing_cleanup_returns_workflow_report():
    mcp = MockMCP()
    routing.register(mcp)

    plan = mcp.tools["fl_plan_routing_cleanup"](
        issues=["issue 1"], proposed_buses=[{"track": 10, "name": "Bus", "sources": [1]}]
    )

    assert plan["contract_version"] == "fls-pilot.workflow-report.v1"
    assert plan["workflow"] == "routing_cleanup_plan"
    assert plan["mode"] == "dry_run"
    assert len(plan["proposed_changes"]) == 2

    change_1 = plan["proposed_changes"][0]
    assert change_1["id"] == "fix_routing_issues"
    assert change_1["tool"] == "fl_apply_routing_cleanup"
    assert change_1["safety_class"] == "write-safe-required"
    assert change_1["risk_level"] == "medium"
    assert change_1["readback_expectation"]
    assert change_1["rollback_expectation"]

    change_2 = plan["proposed_changes"][1]
    assert change_2["id"] == "create_buses"


def test_fl_apply_routing_cleanup_requires_approval(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    routes = [{"src": 1, "dst": 10, "enabled": True}]
    renames = [{"track": 10, "name": "Bus"}]

    result = mcp.tools["fl_apply_routing_cleanup"](routes=routes, renames=renames, approved=False)

    assert result["mode"] == "approval_required"
    assert len(result["proposed_changes"]) == 1
    assert result["proposed_changes"][0]["proposed_state"]["approved"] is True


def test_fl_apply_routing_cleanup_applied(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    routes = [{"src": 1, "dst": 10, "enabled": True}]
    renames = [{"track": 10, "name": "Bus"}]

    # Mock safety.safe_write_group to return a dummy result
    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [],
            "after": [{"src": 1, "dst": 10}],
            "change_id": "chg_routing_cleanup",
            "rollback": {"rollback_unit": "routing_cleanup_batch"},
            "undo": "call fl_rollback_change(change_id='chg_routing_cleanup')",
        }

    monkeypatch.setattr(routing.safety, "safe_write_group", mock_safe_write_group)

    result = mcp.tools["fl_apply_routing_cleanup"](routes=routes, renames=renames, approved=True)

    assert result["mode"] == "applied"
    assert len(result["applied_changes"]) == 1
    applied = result["applied_changes"][0]
    assert applied["id"] == "apply_routing_cleanup"
    assert applied["change_id"] == "chg_routing_cleanup"
    assert applied["rollback"]["rollback_unit"] == "routing_cleanup_batch"
    assert applied["rollback_command"] == "call fl_rollback_change(change_id='chg_routing_cleanup')"
    assert applied["readback_ok"] is True


def test_fl_apply_bus_layout_requires_approval(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    buses = [{"bus_track": 10, "name": "Bus", "source_tracks": [1, 2]}]

    result = mcp.tools["fl_apply_bus_layout"](buses=buses, approved=False)

    assert result["mode"] == "approval_required"
    assert len(result["proposed_changes"]) == 1
    assert result["proposed_changes"][0]["proposed_state"]["approved"] is True


def test_fl_apply_bus_layout_applied(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    buses = [{"bus_track": 10, "name": "Bus", "source_tracks": [1, 2]}]

    # Mock safety.safe_write_group to return a dummy result
    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [],
            "after": [],
            "change_id": "chg_bus_layout",
            "rollback": {"rollback_unit": "bus_layout_creation"},
            "undo": "call fl_rollback_change(change_id='chg_bus_layout')",
        }

    monkeypatch.setattr(routing.safety, "safe_write_group", mock_safe_write_group)

    result = mcp.tools["fl_apply_bus_layout"](buses=buses, approved=True)

    assert result["mode"] == "applied"
    assert len(result["applied_changes"]) == 1
    applied = result["applied_changes"][0]
    assert applied["id"] == "apply_bus_layout"
    assert applied["change_id"] == "chg_bus_layout"
    assert applied["rollback"]["rollback_unit"] == "bus_layout_creation"
    assert applied["readback_ok"] is True


def test_fl_group_tracks_requires_approval(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    result = mcp.tools["fl_group_tracks"](sources=[1, 2], bus=10, name="Bus", approved=False)

    assert result["mode"] == "approval_required"
    assert len(result["proposed_changes"]) == 1
    assert result["proposed_changes"][0]["proposed_state"]["approved"] is True


def test_fl_group_tracks_applied(monkeypatch):
    mcp = MockMCP()
    routing.register(mcp)

    bridge = MixFixBridge()
    monkeypatch.setattr(routing, "get_bridge", lambda: bridge)

    # Mock safety.safe_write_group
    def mock_safe_write_group(*args, **kwargs):
        return {
            "dry_run": False,
            "before": [],
            "after": [],
            "change_id": "chg_group_tracks",
            "rollback": {"rollback_unit": "group_tracks_bus_10"},
            "undo": "call fl_rollback_change(change_id='chg_group_tracks')",
        }

    monkeypatch.setattr(routing.safety, "safe_write_group", mock_safe_write_group)
    monkeypatch.setattr(routing, "mixer_track_error", lambda *args, **kwargs: None)

    result = mcp.tools["fl_group_tracks"](sources=[1, 2], bus=10, name="Bus", approved=True)

    assert result["mode"] == "applied"
    assert len(result["applied_changes"]) == 1
    applied = result["applied_changes"][0]
    assert applied["id"] == "group_tracks"
    assert applied["change_id"] == "chg_group_tracks"
    assert applied["rollback"]["rollback_unit"] == "group_tracks_bus_10"
    assert applied["readback_ok"] is True
