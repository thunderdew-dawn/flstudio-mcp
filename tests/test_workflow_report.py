from fls_pilot.workflow_report import (
    _applied_change_line,
    _proposed_change_line,
    applied_change,
    proposed_change,
)


def test_proposed_change_canonical_v3():
    row = proposed_change(
        id="test-plan-1",
        title="Change volume",
        tool="fl_mixer",
        observed_state={"volume": 0.8},
        proposed_state={"volume": 0.5},
        safety_class="mixer_write",
        risk_level="low",
        readback_expectation="volume matches exactly",
        rollback_expectation="undo available",
        limitations=["not perfectly linear"],
        skipped_changes=["pan"],
    )

    assert row["id"] == "test-plan-1"
    assert row["title"] == "Change volume"
    assert row["tool"] == "fl_mixer"
    assert row["observed_state"] == {"volume": 0.8}
    assert row["proposed_state"] == {"volume": 0.5}
    assert row["safety_class"] == "mixer_write"
    assert row["risk_level"] == "low"
    assert row["readback_expectation"] == "volume matches exactly"
    assert row["rollback_expectation"] == "undo available"
    assert row["limitations"] == ["not perfectly linear"]
    assert row["skipped_changes"] == ["pan"]
    assert row["status"] == "proposed"
    assert row["requires_explicit_approval"] is True

    # Assert deprecated fields are absent
    deprecated_fields = [
        "reason", "params", "action", "target", "source_diagnostic_ids",
        "safety_basis", "readback", "rollback", "manual_review",
        "kb_rule_ids", "metadata"
    ]
    for deprecated in deprecated_fields:
        assert deprecated not in row

    line = _proposed_change_line(row)
    assert "- [risk: low] `test-plan-1`: Change volume via `fl_mixer`" in line
    assert "Approval required: true" in line
    assert "(readback: volume matches exactly, rollback: undo available)" in line


def test_applied_change_canonical_v3():
    row = applied_change(
        id="test-apply-1",
        title="Changed volume",
        tool="fl_mixer",
        before={"volume": 0.8},
        requested_change={"volume": 0.5},
        after={"volume": 0.5},
        safety_class="mixer_write",
        risk_level="medium",
        change_id="chg_1234",
        readback_ok=True,
        rollback={"command": "undo"},
        rollback_command="fl_rollback_change(change_id='chg_1234')",
        limitations=["volume is approximate"],
    )

    assert row["id"] == "test-apply-1"
    assert row["title"] == "Changed volume"
    assert row["tool"] == "fl_mixer"
    assert row["before"] == {"volume": 0.8}
    assert row["requested_change"] == {"volume": 0.5}
    assert row["after"] == {"volume": 0.5}
    assert row["safety_class"] == "mixer_write"
    assert row["risk_level"] == "medium"
    assert row["change_id"] == "chg_1234"
    assert row["readback_ok"] is True
    assert row["rollback"] == {"command": "undo"}
    assert row["rollback_command"] == "fl_rollback_change(change_id='chg_1234')"
    assert row["limitations"] == ["volume is approximate"]
    assert row["status"] == "applied"

    # Assert deprecated fields are absent
    for deprecated in ["params", "source_proposal_id", "metadata"]:
        assert deprecated not in row

    line = _applied_change_line(row)
    assert "- [risk: medium] `test-apply-1`: Changed volume via `fl_mixer`" in line
    assert "Change: `chg_1234`" in line
    assert "(readback_ok: true, rollback: fl_rollback_change(change_id='chg_1234'))" in line
