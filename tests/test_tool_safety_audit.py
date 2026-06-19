#!/usr/bin/env python3
"""Regression tests for the static MCP tool safety audit."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_tool_safety as audit  # noqa: E402


def _audit_source(tmp_path: Path, source: str) -> audit.ToolAudit:
    path = tmp_path / "tool_module.py"
    path.write_text(source, encoding="utf-8")
    audits = audit.audit_file(path)
    assert len(audits) == 1
    return audits[0]


def test_direct_persistent_select_write_is_a_write_gap(tmp_path: Path) -> None:
    result = _audit_source(
        tmp_path,
        '''
from fls_pilot import protocol


@mcp.tool(annotations={"readOnlyHint": False, "safetyClass": "write-safe-required"})
def fl_bad_select():
    """Direct write.

    Safety: Write-Safe-Required with Rollback.
    """
    return bridge.call(protocol.CMD_MIXER_SELECT_TRACK, {"track": 1})
''',
    )

    assert result.status == "write-gap"
    assert result.contract_safety_class == "write-gap"
    assert "CMD_MIXER_SELECT_TRACK" in result.evidence


def test_safe_write_classifies_as_write_safe_required(tmp_path: Path) -> None:
    result = _audit_source(
        tmp_path,
        '''
from fls_pilot import protocol, safety


@mcp.tool(annotations={"readOnlyHint": False, "safetyClass": "write-safe-required"})
def fl_good_write():
    """Safe write.

    Safety: Write-Safe-Required with Rollback.
    """
    return safety.safe_write(
        bridge,
        tool="set_tempo",
        scope="tempo",
        command=protocol.CMD_SET_TEMPO,
        params={"bpm": 128.0},
        build_restore=lambda before: {
            "command": protocol.CMD_SET_TEMPO,
            "params": {"bpm": before["bpm"]},
        },
    )
''',
    )

    assert result.status == "write-safe-required"
    assert result.contract_safety_class == "write-safe-required"
    assert result.safety_class_annotation == "write-safe-required"


def test_approved_step_write_helper_classifies_as_write_safe_required(
    tmp_path: Path,
) -> None:
    result = _audit_source(
        tmp_path,
        '''
from fls_pilot.step_sequencer import safe_set_steps


@mcp.tool(annotations={"readOnlyHint": False, "safetyClass": "write-safe-required"})
def fl_step_write():
    """Safe bounded step write.

    Safety: Write-Safe-Required with Rollback.
    """
    return safe_set_steps(
        bridge,
        tool="channel_set_steps",
        channel=0,
        pattern=1,
        steps=[{"step": 0, "value": True}],
        rollback_unit="step_test",
    )
''',
    )

    assert result.status == "write-safe-required"
    assert result.contract_safety_class == "write-safe-required"


def test_legacy_write_safe_annotation_is_not_mapped(tmp_path: Path) -> None:
    result = _audit_source(
        tmp_path,
        '''
from fls_pilot import protocol, safety


@mcp.tool(annotations={"readOnlyHint": False, "safetyClass": "write-safe"})
def fl_legacy_annotation():
    """Safe write with stale annotation.

    Safety: Write-Safe-Required with Rollback.
    """
    return safety.safe_write(
        bridge,
        tool="set_tempo",
        scope="tempo",
        command=protocol.CMD_SET_TEMPO,
        params={"bpm": 128.0},
        build_restore=lambda before: {
            "command": protocol.CMD_SET_TEMPO,
            "params": {"bpm": before["bpm"]},
        },
    )
''',
    )

    assert result.status == "write-safe-required"
    assert result.contract_safety_class == "write-safe-required"
    assert result.safety_class_annotation == "write-safe"
    assert "safetyClass expected 'write-safe-required'" in result.evidence


def test_unclassified_non_readonly_tool_needs_review(tmp_path: Path) -> None:
    result = _audit_source(
        tmp_path,
        '''
@mcp.tool(annotations={"readOnlyHint": False, "safetyClass": "read-only"})
def fl_unknown_effect():
    """Unknown effect.

    Safety: Read-Only.
    """
    return {"ok": True}
''',
    )

    assert result.status == "needs-review"
    assert result.contract_safety_class == "needs-review"


def test_audio_analysis_tool_is_server_state() -> None:
    audio_path = ROOT / "src" / "fls_pilot" / "tools" / "audio.py"

    result = next(item for item in audit.audit_file(audio_path) if item.name == "fl_audio_analysis")

    assert result.status == "server-state"
    assert result.contract_safety_class == "server-state"
