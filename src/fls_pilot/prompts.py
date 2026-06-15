"""MCP Prompt definitions for FLStudioPilot.

Registers all MCP Prompts via ``@mcp.prompt``. Content is loaded from Markdown
files bundled under ``fls_pilot.context.prompts`` so installed packages expose
the same prompts without requiring a repository checkout.

Usage (called from server.py)::

    from . import prompts as prompt_defs
    prompt_defs.register(mcp)

Prompt categories
-----------------
Runtime prompts (user-facing workflows):
  mix_review, routing_review, project_organizer, project_preflight,
  plugin_chain_planner, composition_scale_writer,
  audio_to_midi_or_reference_analysis
"""

from __future__ import annotations

import logging
from importlib import resources

from fastmcp import FastMCP
from fastmcp.prompts import Message

from .tools.workflow_context import WORKFLOW_REGISTRY

logger = logging.getLogger("fls_pilot.prompts")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_PROMPTS_PACKAGE = "fls_pilot.context.prompts"
_PROMPTS_DIR = resources.files(_PROMPTS_PACKAGE)


def _load_md(filename: str) -> str:
    """Load a prompt Markdown file.  Returns empty string on error."""
    p = _PROMPTS_DIR / filename
    try:
        return p.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        logger.warning("Prompt Markdown not found: %s", p)
        return f"(Prompt file {filename} not found \u2013 check fls_pilot.context.prompts)"
    except Exception as exc:
        logger.error("Error loading prompt Markdown %s: %s", p, exc)
        return f"(Error loading {filename}: {exc})"


def _workflow_preamble(workflow_key: str) -> str:
    """Build a compact orientation block from the workflow registry."""
    if workflow_key not in WORKFLOW_REGISTRY:
        return ""
    entry = WORKFLOW_REGISTRY[workflow_key]
    lines = [
        f"## Workflow Context: {workflow_key}",
        "",
        f"**Purpose**: {entry['description']}",
        "",
        "**Read first**:",
        *[f"- `{r}`" for r in entry["resources_to_read"]],
        "",
        "**Tools to use**:",
        *[f"- `{t}`" for t in entry["tools_to_use"]],
        "",
        "**Requires explicit user approval**:",
        *[f"- `{t}`" for t in entry["approval_required_for"]],
        "",
        "**Not automatable (manual steps)**:",
        *[f"- {u}" for u in entry["unsupported"]],
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt registry: maps MCP name -> (markdown_file, workflow_key_or_None)
# ---------------------------------------------------------------------------

_PROMPT_MAP: list[tuple[str, str, str | None, str]] = [
    # (mcp_name, md_filename, workflow_key, description)
    (
        "mix_review",
        "mix-review.md",
        "mix_review",
        "Guide an agent through a full mix review (headroom, clipping, low-end, stereo).",
    ),
    (
        "routing_review",
        "routing-review.md",
        "routing_review",
        "Guide an agent through mixer routing review and optional cleanup planning.",
    ),
    (
        "project_organizer",
        "project-organizer.md",
        "project_organizer",
        "Guide an agent through project naming, color, grouping, and cleanup.",
    ),
    (
        "project_preflight",
        "project-preflight.md",
        "project_preflight",
        "Check project health and export readiness before a release or handoff.",
    ),
    (
        "plugin_chain_planner",
        "plugin-chain-planner.md",
        "plugin_chain",
        "Plan or configure a plugin FX chain using already-loaded plugins only.",
    ),
    (
        "composition_scale_writer",
        "composition-scale-writer.md",
        "composition",
        "Compose melody or chords using a scale/raga and write to the Piano Roll.",
    ),
    (
        "audio_to_midi_or_reference_analysis",
        "audio-to-midi.md",
        "audio_analysis",
        "Analyze an audio file for tempo/key/melody; optionally write MIDI to Piano Roll.",
    ),
]


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def register(mcp: FastMCP) -> None:
    """Register all FLStudioPilot MCP prompts on *mcp*.

    This function is additive: it does not alter any tool or resource
    registrations. It is idempotent within a single server lifecycle.
    """
    for prompt_name, md_file, workflow_key, description in _PROMPT_MAP:
        _register_one(mcp, prompt_name, md_file, workflow_key, description)

    registered = [p[0] for p in _PROMPT_MAP]
    logger.info("fls_pilot.prompts: registered %d prompts: %s", len(registered), registered)


def _register_one(
    mcp: FastMCP,
    prompt_name: str,
    md_file: str,
    workflow_key: str | None,
    description: str,
) -> None:
    """Register a single prompt by closing over its arguments."""
    # Capture values in default args to avoid late-binding closure issues.
    def _make_prompt(
        _name: str = prompt_name,
        _md: str = md_file,
        _wf: str | None = workflow_key,
        _desc: str = description,
    ):
        @mcp.prompt(name=_name, description=_desc)
        def _prompt() -> list[Message]:
            parts: list[str] = []

            # 1. Workflow orientation block (from registry)
            if _wf:
                preamble = _workflow_preamble(_wf)
                if preamble:
                    parts.append(preamble)

            # 2. Full Markdown content from docs/
            md_content = _load_md(_md)
            if md_content:
                parts.append(md_content)

            text = "\n\n---\n\n".join(parts) if parts else f"(No content for {_name})"

            return [Message(role="user", content=text)]

        return _prompt

    _make_prompt()
