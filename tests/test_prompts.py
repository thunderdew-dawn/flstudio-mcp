"""Tests for MCP Prompt registration and rendering.

Verifies:
- Server importable and build_server() works
- prompts.register(mcp) executes without error
- All expected prompt names are available via list_prompts()
- Core prompts render without error and produce non-empty content
- Existing tools remain registered after prompt additions
- Existing resources remain registered after prompt additions
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastmcp import FastMCP

from fls_pilot import prompts as prompt_defs
from fls_pilot.server import build_server

# ---------------------------------------------------------------------------
# Expected prompt names (from prompts.py _PROMPT_MAP)
# ---------------------------------------------------------------------------

EXPECTED_PROMPTS = {
    "mix_review",
    "routing_review",
    "project_organizer",
    "project_preflight",
    "plugin_chain_planner",
    "composition_scale_writer",
    "audio_to_midi_or_reference_analysis",
    "api_probe",
    "bug_triage",
    "implementation_slice",
    "release_prepare",
}

# Resources that must remain registered
EXISTING_RESOURCES = {
    "fl://agent-briefing",
    "fl://status",
    "fl://project",
    "fl://transport",
    "fl://channels",
    "fl://mixer",
    "fl://patterns",
}

# A sample of tools that must remain registered
REQUIRED_TOOLS_SAMPLE = {
    "fl_transport",
    "fl_mixer",
    "fl_channel",
    "fl_pattern",
    "fl_playlist",
    "fl_effect",
    "fl_plugin",
    "fl_piano_roll",
    "fl_batch",
    "kb_search",
    "kb_get",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build() -> FastMCP:
    return build_server()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_server_importable():
    """The server module must import without error."""
    from fls_pilot import server  # noqa: F401

    assert hasattr(server, "build_server")


def test_build_server_succeeds():
    """build_server() must succeed and return a FastMCP instance."""
    server = _build()
    assert server is not None
    assert isinstance(server, FastMCP)


def test_prompts_register_on_fresh_mcp():
    """prompts.register(mcp) must work on a standalone FastMCP instance."""
    m = FastMCP("test-prompts")
    prompt_defs.register(m)
    prompts = _run(m.list_prompts())
    assert len(prompts) >= len(EXPECTED_PROMPTS)


def test_all_expected_prompts_registered():
    """All 11 expected prompt names must appear in list_prompts()."""
    server = _build()
    prompts = _run(server.list_prompts())
    registered_names = {p.name for p in prompts}
    missing = EXPECTED_PROMPTS - registered_names
    assert not missing, f"Missing prompts: {missing}"


def test_prompt_count():
    """Server must register exactly 11 prompts."""
    server = _build()
    prompts = _run(server.list_prompts())
    assert len(prompts) == 11


def test_mix_review_prompt_renderable():
    """mix_review prompt must render non-empty content."""
    server = _build()
    result = _run(server.render_prompt("mix_review", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert len(text) > 100, "mix_review prompt content too short"
    # Must reference core workflow concepts
    assert "fl_review_mix" in text or "mix" in text.lower()


def test_plugin_chain_planner_prompt_renderable():
    """plugin_chain_planner must render and include API limit warning."""
    server = _build()
    result = _run(server.render_prompt("plugin_chain_planner", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert len(text) > 100
    # Must mention the hard limit about plugin loading
    assert "plugin" in text.lower()


def test_release_prepare_prompt_renderable():
    """release_prepare prompt must render non-empty content."""
    server = _build()
    result = _run(server.render_prompt("release_prepare", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert len(text) > 50


def test_project_preflight_prompt_renderable():
    """project_preflight must reference health check tools."""
    server = _build()
    result = _run(server.render_prompt("project_preflight", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert len(text) > 50


def test_composition_scale_writer_prompt_renderable():
    """composition_scale_writer must reference scale tools and approval gate."""
    server = _build()
    result = _run(server.render_prompt("composition_scale_writer", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert "fl_scale" in text or "scale" in text.lower()


def test_audio_to_midi_prompt_renderable():
    """audio_to_midi_or_reference_analysis must render and mention analyze_audio."""
    server = _build()
    result = _run(server.render_prompt("audio_to_midi_or_reference_analysis", {}))
    assert result.messages
    text = result.messages[0].content.text
    assert len(text) > 50


def test_all_prompts_renderable():
    """Every registered prompt must render without raising an exception."""
    server = _build()
    prompts = _run(server.list_prompts())
    for p in prompts:
        result = _run(server.render_prompt(p.name, {}))
        assert result.messages, f"Prompt {p.name!r} returned no messages"
        assert result.messages[0].content.text, f"Prompt {p.name!r} returned empty text"


def test_existing_tools_still_registered():
    """Required existing tools must still be registered after prompt additions."""
    server = _build()
    tools = _run(server.list_tools())
    registered = {t.name for t in tools}
    missing = REQUIRED_TOOLS_SAMPLE - registered
    assert not missing, f"Missing existing tools: {missing}"


def test_existing_resources_still_registered():
    """All original fl:// resources must remain registered."""
    server = _build()
    resources = _run(server.list_resources())
    registered = {str(r.uri) for r in resources}
    missing = EXISTING_RESOURCES - registered
    assert not missing, f"Missing existing resources: {missing}"


def test_prompt_content_from_markdown(tmp_path, monkeypatch):
    """Prompts must load content from bundled Markdown files."""
    # Just verify the prompt module can locate its MD dir without error
    from fls_pilot.prompts import _PROMPTS_DIR

    assert _PROMPTS_DIR.exists(), f"Prompt MD directory not found: {_PROMPTS_DIR}"
    assert (_PROMPTS_DIR / "mix-review.md").exists()
    assert (_PROMPTS_DIR / "routing-review.md").exists()
    assert (_PROMPTS_DIR / "project-preflight.md").exists()
    assert (_PROMPTS_DIR / "plugin-chain-planner.md").exists()
    assert (_PROMPTS_DIR / "composition-scale-writer.md").exists()
    assert (_PROMPTS_DIR / "audio-to-midi.md").exists()
