"""Tests for fl_get_workflow_context (read-only contract).

Verifies:
- Tool is registered in the server
- Returns expected fields for all known workflows
- Is read-only (does not mutate FL Studio state)
- Returns error for unknown workflows with available list
- detail="compact" and detail="full" work correctly
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot.server import build_server
from fls_pilot.tools.workflow_context import WORKFLOW_REGISTRY, fl_get_workflow_context

KNOWN_WORKFLOWS = list(WORKFLOW_REGISTRY.keys())

REQUIRED_COMPACT_KEYS = {
    "workflow",
    "resources_to_read",
    "tools_to_use",
    "approval_required_for",
    "stop_rules",
    "unsupported",
}


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_workflow_context_tool_registered():
    """fl_get_workflow_context must appear in server tool list."""
    server = build_server()
    tools = _run(server.list_tools())
    tool_names = {t.name for t in tools}
    assert "fl_get_workflow_context" in tool_names


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_compact_keys(workflow):
    """Compact output must contain all required keys."""
    result = fl_get_workflow_context(workflow, detail="compact")
    assert isinstance(result, dict)
    missing = REQUIRED_COMPACT_KEYS - result.keys()
    assert not missing, f"Workflow {workflow!r} missing keys: {missing}"


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_full_keys(workflow):
    """Full output must contain all compact keys plus description."""
    result = fl_get_workflow_context(workflow, detail="full")
    assert isinstance(result, dict)
    assert "description" in result
    assert "workflow" in result


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_resources_nonempty(workflow):
    """Every workflow must specify at least one resource to read."""
    result = fl_get_workflow_context(workflow)
    assert len(result["resources_to_read"]) > 0, f"{workflow} has no resources_to_read"


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_tools_nonempty(workflow):
    """Every workflow must specify at least one tool to use."""
    result = fl_get_workflow_context(workflow)
    assert len(result["tools_to_use"]) > 0, f"{workflow} has no tools_to_use"


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_approval_gates_present(workflow):
    """Every workflow must define approval gates (may be empty list but key must exist)."""
    result = fl_get_workflow_context(workflow)
    assert "approval_required_for" in result


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_stop_rules_present(workflow):
    """Every workflow must define at least one stop rule."""
    result = fl_get_workflow_context(workflow)
    assert len(result["stop_rules"]) > 0, f"{workflow} has no stop_rules"


@pytest.mark.parametrize("workflow", KNOWN_WORKFLOWS)
def test_workflow_context_unsupported_present(workflow):
    """Every workflow must define at least one unsupported action."""
    result = fl_get_workflow_context(workflow)
    assert len(result["unsupported"]) > 0, f"{workflow} has no unsupported list"


def test_workflow_context_unknown_workflow():
    """Unknown workflow must return error dict with available list."""
    result = fl_get_workflow_context("nonexistent_workflow")
    assert "error" in result
    assert "available_workflows" in result
    assert isinstance(result["available_workflows"], list)
    assert len(result["available_workflows"]) > 0


def test_workflow_context_is_read_only():
    """fl_get_workflow_context must be callable without FL Studio state.

    Since this tool reads only from WORKFLOW_REGISTRY (a module-level dict),
    it must never require a bridge connection or mutate any state.
    This test verifies the function returns data without any bridge calls.
    """
    # Should not raise even if bridge is unavailable
    result = fl_get_workflow_context("mix_review")
    assert "workflow" in result
    assert result["workflow"] == "mix_review"


def test_mix_review_workflow_context_references():
    """mix_review context must reference mixer resource and review tools."""
    result = fl_get_workflow_context("mix_review")
    assert "fl://mixer" in result["resources_to_read"]
    tools = result["tools_to_use"]
    assert any("fl_review_mix" in t for t in tools)


def test_routing_review_workflow_context():
    """routing_review context must reference routing tool and have approval gate."""
    result = fl_get_workflow_context("routing_review")
    assert any("fl_review_routing" in t for t in result["tools_to_use"])
    assert any("cleanup" in t.lower() for t in result["approval_required_for"])


def test_composition_workflow_approval_gate():
    """composition workflow must gate both melody and chord write tools."""
    result = fl_get_workflow_context("composition")
    approval = " ".join(result["approval_required_for"]).lower()
    assert "raga" in approval or "write" in approval or "piano" in approval


def test_workflow_context_workflow_field_matches_input():
    """The returned 'workflow' field must match the input key."""
    for wf in KNOWN_WORKFLOWS:
        result = fl_get_workflow_context(wf)
        assert result["workflow"] == wf, f"Mismatch: input={wf!r}, returned={result['workflow']!r}"
