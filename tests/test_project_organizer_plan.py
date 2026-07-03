#!/usr/bin/env python3
"""Tests for template-aware Project Organizer plans."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot import project_templates as templates
from fls_pilot.analysis.broker import StaticProjectSnapshot
from fls_pilot.tools import project_organizer


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, annotations=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


class FakeBroker:
    def __init__(self, snapshot: StaticProjectSnapshot) -> None:
        self.snapshot = snapshot

    def get_static_project_snapshot(self, _bridge):
        return self.snapshot


class FakeBridge:
    pass


def _snapshot(
    *,
    fingerprint: str = "proj_static",
    channel_name: str = "Channel 0",
    channel_target: int = 0,
    template_context: dict | None = None,
) -> StaticProjectSnapshot:
    return StaticProjectSnapshot(
        created_at=1.0,
        project_fingerprint=fingerprint,
        snapshot_id=f"snap_{fingerprint}",
        channels=(
            {
                "channel": 0,
                "name": channel_name,
                "type": {"label": "genplug"},
                "target_mixer_track": channel_target,
                "target_name": "Master" if channel_target == 0 else "Kick",
            },
        ),
        mixer_tracks=(
            {"i": 0, "name": "Master", "routes_to": []},
            {"i": 2, "name": "Wrong Kick", "routes_to": [{"dst": 0}]},
            {"i": 20, "name": "Kick Bus", "routes_to": [{"dst": 1}]},
        ),
        routing=(
            {"i": 0, "name": "Master", "routes_to": []},
            {"i": 2, "name": "Wrong Kick", "routes_to": [{"dst": 0}]},
            {"i": 20, "name": "Kick Bus", "routes_to": [{"dst": 1}]},
        ),
        template_context=template_context or {},
        source_observation_ids=("obs_static_1",),
    )


def _registered(monkeypatch, snapshot: StaticProjectSnapshot):
    mcp = MockMCP()
    project_organizer.register(mcp)
    broker = FakeBroker(snapshot)
    monkeypatch.setattr(project_organizer, "get_bridge", lambda: FakeBridge())
    monkeypatch.setattr(project_organizer, "get_analysis_broker", lambda: broker)
    project_organizer._PLAN_STORE.clear()
    return mcp, broker


def test_organizer_plan_static_only_is_provisional(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    plan = mcp.tools["fl_plan_project_organization"]()

    assert plan["plan_status"] == "blocked"
    assert plan["plan_id"]
    assert plan["plan_hash"]
    assert plan["project_fingerprint"] == "proj_static"
    assert plan["interaction_requests"][0]["id"] == "organizer.choose_target_template"
    assert plan["blocked_steps"][0]["evidence_type"] == "name_based_detection"
    assert plan["blocked_steps"][0]["safe_to_apply"] is False
    assert plan["organization_plan_status"] == plan["plan_status"]
    assert plan["metadata"]["organizer_plan"]["status"] == plan["plan_status"]
    assert plan["source_report_id"] == "snap_proj_static"
    assert plan["findings"]
    assert plan["decisions_required"]
    assert plan["blocked_steps"][0]["step_id"] == "name_based_rename_channel_0"
    assert plan["blocked_steps"][0]["kind"] == "rename"
    assert plan["blocked_steps"][0]["before_state"] == {"name": "Channel 0"}
    assert plan["blocked_steps"][0]["required_user_decision"]["required"] is True


def test_organizer_scan_alias_returns_read_only_analysis(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    result = mcp.tools["fl_scan_project_organization"]()

    assert result["workflow"] == "project_organizer"
    assert result["safety"]["read_only"] is True
    assert result["summary"]["unnamed_channels"] == 1


def test_organizer_template_ambiguous_blocks_apply_plan(monkeypatch) -> None:
    context = {
        "matched": True,
        "ambiguous": True,
        "candidate_slugs": ["psytrance", "electro"],
        "candidate_templates": ["Psytrance", "Electro"],
    }
    mcp, _broker = _registered(monkeypatch, _snapshot(template_context=context))

    plan = mcp.tools["fl_plan_project_organization"]()

    assert plan["template_match_status"] == "ambiguous_requires_user_selection"
    assert plan["safety"]["requires_explicit_approval"] is True
    assert plan["blocked_steps"]
    assert plan["steps"] == []


def test_organizer_user_template_decision_unblocks_template_plan(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )
    step = next(row for row in plan["steps"] if row["id"] == "template_rename_channel_0")

    assert plan["target_template"]["template_slug"] == "psytrance"
    assert step["status"] == "approved"
    assert step["safe_to_apply"] is True
    assert step["confidence"] == "confirmed"


def test_organization_step_schema_rejects_invalid_risk_level() -> None:
    step = project_organizer._organizer_step(
        id="schema_test_step",
        action_type="rename",
        tool="fl_apply_project_cleanup_step",
        target={"type": "channel", "index": 1},
        observed_state={"name": "Channel 1"},
        proposed_state={
            "renames": [{"type": "channel", "index": 1, "name": "Lead"}]
        },
        reason="Validate typed organizer step schema.",
        evidence_type="template_profile",
        confidence="high",
        risk_level="low",
        rollback_unit="organization_plan_schema_test",
        user_decisions=[],
    )
    invalid = dict(step)
    invalid["risk_level"] = "tiny"

    with pytest.raises(ValueError, match="invalid organization step schema_test_step"):
        project_organizer._validate_organization_step_payload(invalid)


def test_organizer_template_routing_steps_are_medium_risk(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    plan = mcp.tools["fl_plan_project_organization"](target_template="psytrance")
    route_step = next(
        row for row in plan["steps"] if row["id"] == "template_route_channel_0_to_2"
    )

    assert route_step["risk_level"] == "medium"
    assert route_step["required_user_decision"]["required"] is True


def test_organizer_reserved_placeholders_are_never_cleanup_targets() -> None:
    profile = {
        "template_name": "Test",
        "template_slug": "test",
        "channel_routes": [
            {
                "channel_index": 0,
                "channel_name": "Kick",
                "target_mixer_track": 9,
            }
        ],
        "mixer_tracks": [],
    }
    snapshot = _snapshot(
        template_context={
            "matched": True,
            "ambiguous": False,
            "track_roles": {
                "9": {"role": templates.ROLE_RESERVED_PLACEHOLDER, "template": "Test"}
            },
        }
    )

    plan = project_organizer.build_template_alignment_plan(
        snapshot,
        profile,
        [{"step_id": "blocked_route_channel_0_reserved_9", "decision": "approved_for_apply"}],
        target_selected_by_user=True,
    )

    blocked = next(
        row for row in plan["blocked_steps"] if row["id"] == "blocked_route_channel_0_reserved_9"
    )
    assert blocked["blocked_reason"] == "reserved_placeholder_target"
    assert blocked["safe_to_apply"] is False


def test_organizer_plan_contains_project_fingerprint_and_plan_hash(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    plan = mcp.tools["fl_plan_project_organization"](target_template="psytrance")

    assert plan["project_fingerprint"] == "proj_static"
    assert plan["snapshot_id"] == "snap_proj_static"
    assert plan["source_observation_ids"] == ["obs_static_1"]
    assert project_organizer._PLAN_STORE[plan["plan_id"]]["plan_hash"] == plan["plan_hash"]


def test_organizer_apply_rejects_missing_approval(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=False,
    )

    assert result["mode"] == "approval_required"
    assert result["safety"]["approval_received"] is False


def test_organizer_apply_rejects_stale_project_fingerprint(monkeypatch) -> None:
    mcp, broker = _registered(monkeypatch, _snapshot(fingerprint="proj_a"))
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )
    broker.snapshot = _snapshot(fingerprint="proj_b")

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=True,
    )

    assert result["mode"] == "rejected"
    assert result["diagnostics"][0]["id"] == "organization_plan_stale_project_fingerprint"


def test_organizer_apply_rejects_unknown_step_id(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["missing_step"],
        approved=True,
    )

    assert result["diagnostics"][0]["id"] == "organization_plan_unknown_step"


def test_organizer_apply_excludes_rejected_steps(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[{"step_id": "template_rename_channel_0", "decision": "rejected"}],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=True,
    )

    assert next(row for row in plan["steps"] if row["id"] == "template_rename_channel_0")[
        "status"
    ] == "rejected"
    assert result["diagnostics"][0]["id"] == "organization_plan_step_blocked"


def test_organizer_apply_excludes_ignored_steps(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[{"step_id": "template_rename_channel_0", "decision": "ignored"}],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=True,
    )

    assert next(row for row in plan["steps"] if row["id"] == "template_rename_channel_0")[
        "status"
    ] == "ignored"
    assert result["diagnostics"][0]["id"] == "organization_plan_step_blocked"


def test_organizer_apply_rejects_mixed_low_and_routing_steps(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    def fail_safe_write_group(*args, **kwargs):
        raise AssertionError("safe_write_group must not run for mixed-risk steps")

    monkeypatch.setattr(project_organizer.safety, "safe_write_group", fail_safe_write_group)
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"},
            {"step_id": "template_route_channel_0_to_2", "decision": "approved_for_apply"},
        ],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=[
            "template_rename_channel_0",
            "template_route_channel_0_to_2",
        ],
        approved=True,
    )

    assert result["mode"] == "rejected"
    assert result["diagnostics"][0]["id"] == (
        "organization_plan_risky_step_requires_separate_apply"
    )


def test_project_cleanup_step_rejects_routing_mixed_with_renames(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    result = mcp.tools["fl_apply_project_cleanup_step"](
        renames=[{"type": "channel", "index": 0, "name": "Kick"}],
        routing=[{"channel": 0, "track": 2}],
        approved=True,
    )

    assert result["mode"] == "rejected"
    assert result["diagnostics"][0]["id"] == "routing_cleanup_requires_separate_approval"


def test_organizer_name_based_step_requires_user_confirmation(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())

    plan = mcp.tools["fl_plan_project_organization"]()

    step = plan["blocked_steps"][0]
    assert step["id"] == "name_based_rename_channel_0"
    assert step["blocked_reason"] == "name_based_step_requires_user_confirmation"
    assert step["status"] == "blocked"


def test_organizer_template_confirmed_rename_step_can_apply(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    safe_write_calls = []

    def mock_safe_write_group(*args, **kwargs):
        safe_write_calls.append(kwargs)
        return {
            "dry_run": False,
            "before": [{"name": "Channel 0"}],
            "after": [{"name": "Kick"}],
            "change_id": "chg_organization_plan",
            "rollback": {"rollback_unit": kwargs["rollback_unit"]},
            "undo": "call fl_rollback_change(change_id='chg_organization_plan')",
        }

    monkeypatch.setattr(project_organizer.safety, "safe_write_group", mock_safe_write_group)
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=True,
    )

    assert result["mode"] == "applied"
    assert result["applied_changes"][0]["id"] == "template_rename_channel_0"
    assert result["applied_changes"][0]["change_id"] == "chg_organization_plan"
    assert safe_write_calls[0]["tool"] == "apply_organization_plan"
    assert safe_write_calls[0]["rollback_unit"] == f"organization_plan_{plan['plan_id']}"
    status = mcp.tools["fl_get_organization_status"](
        plan_id=plan["plan_id"],
        include_history=False,
    )
    assert status["plans"][0]["step_status_counts"]["verified"] == 1


def test_organizer_decision_update_unblocks_name_based_step(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    safe_write_calls = []

    def mock_safe_write_group(*args, **kwargs):
        safe_write_calls.append(kwargs)
        return {
            "dry_run": False,
            "before": [{"name": "Channel 0"}],
            "after": [{"name": "Instrument 0"}],
            "change_id": "chg_name_based",
            "rollback": {"rollback_unit": kwargs["rollback_unit"]},
            "undo": "call fl_rollback_change(change_id='chg_name_based')",
        }

    monkeypatch.setattr(project_organizer.safety, "safe_write_group", mock_safe_write_group)
    plan = mcp.tools["fl_plan_project_organization"]()

    updated = mcp.tools["fl_update_organization_plan_decision"](
        plan_id=plan["plan_id"],
        approve_step_ids=["name_based_rename_channel_0"],
    )
    step = next(row for row in updated["steps"] if row["id"] == "name_based_rename_channel_0")

    assert updated["plan_status"] == "approved"
    assert step["status"] == "approved"
    assert step["safe_to_apply"] is True
    assert step["blocked_reason"] is None

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["name_based_rename_channel_0"],
        approved=True,
    )

    assert result["mode"] == "applied"
    assert safe_write_calls[0]["tool"] == "apply_organization_plan"


def test_organizer_status_lists_stored_plans(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](target_template="psytrance")

    status = mcp.tools["fl_get_organization_status"](include_history=False)

    assert status["ok"] is True
    assert status["active_plan_count"] == 1
    assert status["plans"][0]["plan_id"] == plan["plan_id"]
    assert status["plans"][0]["plan_hash"] == plan["plan_hash"]


def test_organizer_rollback_by_unit_delegates_to_lifo_safety(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    calls = []

    monkeypatch.setattr(
        project_organizer.safety,
        "change_history",
        lambda *args, **kwargs: {
            "entries": [
                {
                    "change_id": "chg_organization_plan",
                    "rollback_unit": "organization_plan_orgplan_123",
                    "scope": "project_organizer",
                    "tool": "apply_organization_plan",
                }
            ]
        },
    )

    def mock_rollback_change(_bridge, change_id):
        calls.append(change_id)
        return {"ok": True, "change_id": change_id}

    monkeypatch.setattr(project_organizer.safety, "rollback_change", mock_rollback_change)

    result = mcp.tools["fl_rollback_organization_change"](
        rollback_unit_id="organization_plan_orgplan_123"
    )

    assert result["ok"] is True
    assert calls == ["chg_organization_plan"]


def test_organizer_bus_layout_reuses_routing_apply_path(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot(channel_name="Kick", channel_target=2))
    safe_write_calls = []

    def mock_safe_write_group(*args, **kwargs):
        safe_write_calls.append(kwargs)
        return {
            "dry_run": False,
            "before": [],
            "after": [],
            "change_id": "chg_bus_layout",
            "rollback": {"rollback_unit": kwargs["rollback_unit"]},
        }

    monkeypatch.setattr(project_organizer.safety, "safe_write_group", mock_safe_write_group)
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_bus_layout_20", "decision": "approved_for_apply"}
        ],
    )
    assert next(row for row in plan["steps"] if row["id"] == "template_bus_layout_20")[
        "tool"
    ] == "fl_apply_bus_layout"

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_bus_layout_20"],
        approved=True,
    )

    assert result["mode"] == "applied"
    assert safe_write_calls[0]["writes"]
    assert safe_write_calls[0]["scope"] == "project_organizer"


def test_organizer_plan_hash_changes_when_steps_change() -> None:
    profile = templates.profile_by_slug("psytrance")
    first = project_organizer.build_template_alignment_plan(
        _snapshot(channel_name="Channel 0"),
        profile,
        [],
        target_selected_by_user=True,
    )
    second = project_organizer.build_template_alignment_plan(
        _snapshot(channel_name="Kick"),
        profile,
        [],
        target_selected_by_user=True,
    )

    assert first["plan_hash"] != second["plan_hash"]


def test_organizer_apply_blocks_if_plan_expired(monkeypatch) -> None:
    mcp, _broker = _registered(monkeypatch, _snapshot())
    plan = mcp.tools["fl_plan_project_organization"](
        target_template="psytrance",
        user_decisions=[
            {"step_id": "template_rename_channel_0", "decision": "approved_for_apply"}
        ],
    )
    project_organizer._PLAN_STORE[plan["plan_id"]]["expires_at"] = 0

    result = mcp.tools["fl_apply_organization_plan"](
        plan_id=plan["plan_id"],
        approved_step_ids=["template_rename_channel_0"],
        approved=True,
    )

    assert result["diagnostics"][0]["id"] == "organization_plan_expired"
