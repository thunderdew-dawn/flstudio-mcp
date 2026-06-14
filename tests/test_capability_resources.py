"""Tests for new fls:// static resources (capability and docs resources).

Verifies:
- All new fls://docs/ and fls://capabilities/ resources are registered
- Capability resources return compact, structured dicts
- Doc resources return file content (or graceful error if file missing)
- All existing fl:// resources still work
- Resource outputs stay within reasonable size bounds
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fls_pilot.server import build_server

NEW_DOC_RESOURCES = [
    "fls://docs/safety-contract",
    "fls://docs/api-capability-audit",
    "fls://docs/default-safe-ux",
    "fls://docs/runtime-usage",
    "fls://docs/knowledgebase-protocol",
    "fls://docs/tool-policy",
]

NEW_CAPABILITY_RESOURCES = [
    "fls://capabilities/supported",
    "fls://capabilities/not-possible",
    "fls://capabilities/api-limits",
    "fls://capabilities/write-safety",
]

EXISTING_RESOURCES = [
    "fl://agent-briefing",
    "fl://status",
    "fl://project",
    "fl://transport",
    "fl://channels",
    "fl://mixer",
    "fl://patterns",
]

ALL_NEW_RESOURCES = NEW_DOC_RESOURCES + NEW_CAPABILITY_RESOURCES


def _run(coro):
    return asyncio.run(coro)


def _text(r) -> str:
    """Extract text from whatever read_resource returns (FastMCP 3.x compatible)."""
    # FastMCP 3.4+ returns ResourceResult with .contents list
    if hasattr(r, "contents"):
        contents = r.contents
        if contents:
            first = contents[0]
            for attr in ("content", "text", "data", "blob"):
                v = getattr(first, attr, None)
                if isinstance(v, str):
                    return v
                if v is not None:
                    return str(v)
    # Older or list-based formats
    if isinstance(r, (list, tuple)) and r:
        r = r[0]
    for attr in ("text", "content", "data"):
        v = getattr(r, attr, None)
        if isinstance(v, str):
            return v
        if v is not None:
            return str(v)
    return str(r)



def _server():
    return build_server()


# ---------------------------------------------------------------------------
# Registration checks
# ---------------------------------------------------------------------------


def test_all_new_resources_registered():
    """All new fls:// resources must appear in list_resources()."""
    server = _server()
    resources = _run(server.list_resources())
    registered = {str(r.uri) for r in resources}
    missing = set(ALL_NEW_RESOURCES) - registered
    assert not missing, f"New resources not registered: {missing}"


def test_all_existing_resources_still_registered():
    """All original fl:// resources must remain registered."""
    server = _server()
    resources = _run(server.list_resources())
    registered = {str(r.uri) for r in resources}
    missing = set(EXISTING_RESOURCES) - registered
    assert not missing, f"Original resources missing: {missing}"


def test_total_resource_count():
    """Server must have at least 17 resources (7 original + 10 new)."""
    server = _server()
    resources = _run(server.list_resources())
    assert len(resources) >= 17


# ---------------------------------------------------------------------------
# Capability resources: structure
# ---------------------------------------------------------------------------


def test_capabilities_supported_has_list():
    """fls://capabilities/supported must return dict with 'supported' list."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/supported")))
    data = json.loads(text)
    assert "supported" in data
    assert isinstance(data["supported"], list)
    assert len(data["supported"]) > 5


def test_capabilities_not_possible_has_list():
    """fls://capabilities/not-possible must return dict with 'not_possible' list."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/not-possible")))
    data = json.loads(text)
    assert "not_possible" in data
    assert isinstance(data["not_possible"], list)
    assert len(data["not_possible"]) >= 5  # At least 5 hard limits documented


def test_capabilities_not_possible_entry_fields():
    """Each entry in 'not_possible' must have action, reason, workaround."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/not-possible")))
    data = json.loads(text)
    for entry in data["not_possible"]:
        assert "action" in entry, f"Entry missing 'action': {entry}"
        assert "reason" in entry, f"Entry missing 'reason': {entry}"
        assert "workaround" in entry, f"Entry missing 'workaround': {entry}"


def test_capabilities_api_limits_has_hard_limits():
    """fls://capabilities/api-limits must contain hard_limits and do_not_guess."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/api-limits")))
    data = json.loads(text)
    assert "hard_limits" in data
    assert "do_not_guess" in data
    assert len(data["hard_limits"]) >= 5


def test_capabilities_write_safety_has_protocol():
    """fls://capabilities/write-safety must define a 6-step protocol."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/write-safety")))
    data = json.loads(text)
    assert "protocol" in data
    assert len(data["protocol"]) >= 6
    assert "approval_gates" in data
    assert "never_auto_execute" in data


def test_write_safety_mentions_prompt_not_approval():
    """write-safety must clearly state prompts don't grant write approval."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/write-safety")))
    assert "prompt" in text.lower()
    # The never_auto_execute message should be present
    assert "guided template" in text.lower() or "not a write approval" in text.lower()


# ---------------------------------------------------------------------------
# Doc resources: content checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uri", NEW_DOC_RESOURCES)
def test_doc_resource_readable(uri):
    """Every fls://docs/ resource must be readable without error."""
    server = _server()
    text = _text(_run(server.read_resource(uri)))
    data = json.loads(text)
    # Should have either 'content' or 'error' key
    assert "content" in data or "error" in data, f"{uri} returned unexpected structure"


@pytest.mark.parametrize("uri", NEW_DOC_RESOURCES)
def test_doc_resource_compact(uri):
    """fls://docs/ resources must stay under 4 KB."""
    server = _server()
    text = _text(_run(server.read_resource(uri)))
    assert len(text) < 4000, f"{uri} is too large: {len(text)} chars"


def test_doc_safety_contract_content():
    """fls://docs/safety-contract must contain safety-related content."""
    server = _server()
    text = _text(_run(server.read_resource("fls://docs/safety-contract")))
    assert "safety" in text.lower() or "rule" in text.lower() or "contract" in text.lower()


def test_doc_tool_policy_content():
    """fls://docs/tool-policy must reference the tool hierarchy."""
    server = _server()
    text = _text(_run(server.read_resource("fls://docs/tool-policy")))
    assert "tool" in text.lower()


# ---------------------------------------------------------------------------
# Capability resources: compactness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("uri", NEW_CAPABILITY_RESOURCES)
def test_capability_resource_compact(uri):
    """fls://capabilities/ resources must stay under 5 KB."""
    server = _server()
    text = _text(_run(server.read_resource(uri)))
    assert len(text) < 5000, f"{uri} is too large: {len(text)} chars"


# ---------------------------------------------------------------------------
# Hard API limit checks in not-possible resource
# ---------------------------------------------------------------------------


def test_not_possible_mentions_plugin_loading():
    """Plugin loading must appear in the not-possible list."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/not-possible")))
    assert "plugin" in text.lower()


def test_not_possible_mentions_wav_rendering():
    """WAV/audio rendering must appear in the not-possible list."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/not-possible")))
    assert "render" in text.lower() or "wav" in text.lower()


def test_not_possible_mentions_playlist_clips():
    """Playlist clip editing must appear in the not-possible list."""
    server = _server()
    text = _text(_run(server.read_resource("fls://capabilities/not-possible")))
    assert "playlist" in text.lower()
