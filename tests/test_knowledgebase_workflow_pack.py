"""Tests for KB workflow pack and structured search tools.

Verifies:
- kb_search(query) still works with original string output (backwards compat)
- kb_search_structured returns list of dicts with required fields
- kb_get_many returns dict mapping paths to content
- kb_get_workflow_pack returns structured, bounded output
- kb_get_capability returns correct support status
- kb_explain_limit returns limit info for known hard limits
- All new tools registered in server
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot.server import build_server
from fls_pilot.tools.knowledgebase import (
    kb_search,
    kb_search_structured,
    kb_get,
    kb_get_many,
    kb_get_workflow_pack,
    kb_get_capability,
    kb_explain_limit,
    KB_ROOT,
    _WORKFLOW_KB_PATHS,
)

KNOWN_WORKFLOWS = list(_WORKFLOW_KB_PATHS.keys())


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Backwards compatibility: kb_search(query)
# ---------------------------------------------------------------------------


def test_kb_search_returns_string():
    """Original kb_search must still return a str (backwards compat)."""
    result = kb_search("mixer")
    assert isinstance(result, str)


def test_kb_search_no_results_returns_string():
    """kb_search for non-existent term must return a string."""
    result = kb_search("zzz_nonexistent_term_xyz_999")
    assert isinstance(result, str)
    assert "No results" in result or result  # either message or empty


# ---------------------------------------------------------------------------
# kb_search_structured
# ---------------------------------------------------------------------------


def test_kb_search_structured_returns_list():
    """kb_search_structured must return a list."""
    result = kb_search_structured("mixer")
    assert isinstance(result, list)


def test_kb_search_structured_has_required_keys():
    """kb_search_structured results must contain all required keys."""
    result = kb_search_structured("mixer")
    if result and "error" not in result[0] and "message" not in result[0]:
        item = result[0]
        for key in ("path", "title", "snippet", "confidence", "machine_readable", "recommended_next_tool"):
            assert key in item, f"Missing key {key!r} in structured result"


def test_kb_search_structured_max_results():
    """kb_search_structured must respect max_results cap."""
    result = kb_search_structured("a", max_results=3)
    # Could be fewer if KB is small, but should not exceed cap
    assert len(result) <= 3


def test_kb_search_structured_recommended_tool():
    """recommended_next_tool must always be 'kb_get'."""
    result = kb_search_structured("mixer")
    for item in result:
        if "recommended_next_tool" in item:
            assert item["recommended_next_tool"] == "kb_get"


def test_kb_search_structured_no_results():
    """Empty search returns list with message dict."""
    result = kb_search_structured("zzz_nonexistent_abc_999_xyz")
    assert isinstance(result, list)
    assert len(result) >= 1


# ---------------------------------------------------------------------------
# kb_get_many
# ---------------------------------------------------------------------------


def test_kb_get_many_returns_dict():
    """kb_get_many must return a dict."""
    result = kb_get_many(["MCP_TOOL_POLICY.md"])
    assert isinstance(result, dict)


def test_kb_get_many_missing_file():
    """kb_get_many must handle missing files gracefully."""
    result = kb_get_many(["nonexistent/path.md"])
    assert isinstance(result, dict)
    assert "nonexistent/path.md" in result
    # Should contain an error or 'not found' string, not raise
    assert isinstance(result["nonexistent/path.md"], str)


def test_kb_get_many_truncation():
    """kb_get_many must truncate content exceeding max_chars_per_file."""
    result = kb_get_many(["README.md"], max_chars_per_file=100)
    for content in result.values():
        if "not found" not in content.lower() and "error" not in content.lower():
            assert len(content) <= 200  # 100 chars + truncation note


# ---------------------------------------------------------------------------
# kb_get_workflow_pack
# ---------------------------------------------------------------------------


def test_kb_get_workflow_pack_returns_dict():
    """kb_get_workflow_pack must return a dict."""
    result = kb_get_workflow_pack("mix_review")
    assert isinstance(result, dict)


def test_kb_get_workflow_pack_has_required_keys():
    """kb_get_workflow_pack must have workflow, files, and note keys."""
    result = kb_get_workflow_pack("mix_review")
    assert "workflow" in result
    assert "files" in result
    assert "note" in result


def test_kb_get_workflow_pack_workflow_field():
    """The workflow field must match the input."""
    for wf in KNOWN_WORKFLOWS:
        result = kb_get_workflow_pack(wf)
        assert result.get("workflow") == wf, f"Mismatch for {wf!r}"


def test_kb_get_workflow_pack_unknown_workflow():
    """Unknown workflow must return error dict with available list."""
    result = kb_get_workflow_pack("nonexistent_workflow_xyz")
    assert "error" in result
    assert "available" in result


def test_kb_get_workflow_pack_content_bounded():
    """Files in pack must not exceed max_per_file chars each."""
    MAX_PER_FILE = 1500
    for wf in KNOWN_WORKFLOWS:
        result = kb_get_workflow_pack(wf)
        for path, content in result.get("files", {}).items():
            # Content should be at most slightly over max due to truncation note
            assert len(content) <= MAX_PER_FILE + 50, (
                f"Workflow {wf!r} file {path!r} too large: {len(content)} chars"
            )


def test_kb_get_workflow_pack_max_files():
    """Workflow pack must not return more than 8 files."""
    for wf in KNOWN_WORKFLOWS:
        result = kb_get_workflow_pack(wf)
        file_count = len(result.get("files", {}))
        assert file_count <= 8, f"Workflow {wf!r} returned {file_count} files (max 8)"


# ---------------------------------------------------------------------------
# kb_get_capability
# ---------------------------------------------------------------------------


def test_kb_get_capability_supported_mix():
    """'mix' intent must be identified as supported."""
    result = kb_get_capability("review the mix")
    assert isinstance(result, dict)
    assert result.get("supported") is True


def test_kb_get_capability_unsupported_plugin_load():
    """'load plugin' intent must be identified as not supported."""
    result = kb_get_capability("load plugin")
    assert result.get("supported") is False
    assert "workaround" in result.get("guidance", "").lower() or "not supported" in result.get("guidance", "").lower()


def test_kb_get_capability_unsupported_render():
    """'render' intent must be identified as not supported."""
    result = kb_get_capability("render wav")
    assert result.get("supported") is False


def test_kb_get_capability_unknown_intent():
    """Unknown intent must return 'unknown' status."""
    result = kb_get_capability("some completely random action xyz")
    assert result.get("supported") == "unknown"


def test_kb_get_capability_has_intent_field():
    """Result must echo back the original intent."""
    intent = "review the mix with fl studio"
    result = kb_get_capability(intent)
    assert result.get("intent") == intent


# ---------------------------------------------------------------------------
# kb_explain_limit
# ---------------------------------------------------------------------------


def test_kb_explain_limit_plugin_loading():
    """'load plugin' must return a hard limit explanation."""
    result = kb_explain_limit("load plugin")
    assert isinstance(result, dict)
    assert result.get("is_hard_limit") is True
    assert "workaround" in result


def test_kb_explain_limit_render():
    """'render' must return a hard limit."""
    result = kb_explain_limit("render audio")
    assert result.get("is_hard_limit") is True


def test_kb_explain_limit_playlist_clips():
    """'playlist clip' editing must return a hard limit."""
    result = kb_explain_limit("move playlist clip")
    assert result.get("is_hard_limit") is True


def test_kb_explain_limit_unknown():
    """Unknown intent must return non-hard-limit with fallback guidance."""
    result = kb_explain_limit("do something completely unknown xyz")
    assert result.get("is_hard_limit") is False
    assert "workaround" in result


def test_kb_explain_limit_has_see_also_for_known():
    """Known limits must include see_also field."""
    result = kb_explain_limit("load vst plugin")
    assert "see_also" in result


# ---------------------------------------------------------------------------
# Server registration check for new tools
# ---------------------------------------------------------------------------


def test_new_kb_tools_registered_in_server():
    """All new KB tools must appear in the server tool list."""
    server = build_server()
    tools = _run(server.list_tools())
    tool_names = {t.name for t in tools}
    new_tools = {"kb_search_structured", "kb_get_many", "kb_get_workflow_pack", "kb_get_capability", "kb_explain_limit"}
    missing = new_tools - tool_names
    assert not missing, f"New KB tools not registered: {missing}"


def test_original_kb_tools_still_registered():
    """Original KB tools must remain registered."""
    server = build_server()
    tools = _run(server.list_tools())
    tool_names = {t.name for t in tools}
    original = {"kb_search", "kb_get", "kb_get_parameter_spec", "kb_get_conversion",
                "kb_record_finding", "kb_record_verified_finding", "kb_list_open_questions"}
    missing = original - tool_names
    assert not missing, f"Original KB tools missing: {missing}"
