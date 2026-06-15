from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from fastmcp import FastMCP

KB_ROOT = Path("knowledgebase")


def get_kb_root() -> Path:
    env_path = os.environ.get("FLS_PILOT_KB_PATH")
    if env_path:
        return Path(env_path).resolve()

    repo_kb = Path(__file__).resolve().parent.parent.parent.parent / "knowledgebase"
    if repo_kb.exists():
        return repo_kb

    return Path("knowledgebase").resolve()


KB_ROOT = get_kb_root()


def _resolve_path(sub_path: str) -> Path:
    p = KB_ROOT / sub_path
    return p.resolve()


def _read_file_safe(path: Path) -> str:
    if not path.exists():
        return f"File {path.name} not found in knowledgebase."
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading {path.name}: {e}"


def kb_search(query: str) -> str:
    """Search the Knowledgebase markdown and JSON files for a query."""
    if not KB_ROOT.exists():
        return "Knowledgebase directory not found."

    results = []
    for root_dir, _, files in os.walk(KB_ROOT):
        for file in files:
            if file.endswith((".md", ".json")):
                p = Path(root_dir) / file
                try:
                    content = p.read_text(encoding="utf-8")
                    if query.lower() in content.lower():
                        rel_path = p.relative_to(KB_ROOT)
                        results.append(f"Found in: {rel_path}")
                except Exception:
                    pass
    if not results:
        return f"No results found for '{query}'."
    return "\n".join(results)


def kb_get(topic_path: str) -> str:
    """Get the content of a specific Knowledgebase file (e.g. 'fl_api/mixer_eq.md')."""
    return _read_file_safe(KB_ROOT / topic_path)


def kb_get_parameter_spec(api_function: str) -> str:
    """Check knowledgebase for parameter specs of an API function."""
    # Specifically check mixer_eq_calibration.json or search globally
    calib = KB_ROOT / "fl_api" / "mixer_eq_calibration.json"
    if calib.exists():
        try:
            data = json.loads(calib.read_text())
            for entry in data:
                if (
                    entry.get("api_setter") == api_function
                    or entry.get("api_getter") == api_function
                ):
                    return json.dumps(entry, indent=2)
        except Exception:
            pass
    return f"No parameter spec found for {api_function} in known calibration files."


def kb_get_conversion(domain: str, parameter: str) -> str:
    """Get conversion mappings for a domain (e.g. 'eq_gain')."""
    calib = KB_ROOT / "fl_api" / "mixer_eq_calibration.json"
    if calib.exists():
        try:
            data = json.loads(calib.read_text())
            for entry in data:
                if entry.get("domain") == domain and entry.get("parameter") == parameter:
                    return json.dumps(entry.get("mapping", []), indent=2)
        except Exception:
            pass
    return f"No conversion found for domain '{domain}' and parameter '{parameter}'."


def kb_record_finding(
    topic: str,
    context: str,
    observation: str,
    tested_values: str,
    result: str,
    confidence: str,
    source_method: str,
    affected_files_tools: str = "N/A",
    open_questions: str = "None",
    next_action: str = "None",
) -> str:
    """Record a finding directly to the learning_log.md (append-only)."""
    log_file = KB_ROOT / "agent_notes" / "learning_log.md"
    if not log_file.exists():
        return "learning_log.md not found."

    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = f"\n## {date_str} — {topic}\n\n"
    entry += "Agent/Source: FL Studio Pilot Agent\n"
    entry += f"Context: {context}\n"
    entry += f"Observation: {observation}\n"
    entry += f"Tested values: {tested_values}\n"
    entry += f"Result: {result}\n"
    entry += f"Confidence: {confidence}\n"
    entry += f"Affected files/tools: {affected_files_tools}\n"
    entry += "Should update machine-readable data: Yes if confidence is high\n"
    entry += f"Open questions: {open_questions}\n"
    entry += f"Next action: {next_action}\n"

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
        return "Successfully appended finding to learning_log.md."
    except Exception as e:
        return f"Failed to write to learning_log.md: {e}"


def kb_record_verified_finding(json_path: str, new_mapping_entry: str, confidence: str) -> str:
    """Safely update a structured JSON file (e.g., fl_api/mixer_eq_calibration.json) with a new mapping."""
    if confidence not in [
        "implementation_verified",
        "cross_platform_verified",
        "measured_repeated",
        "measured_once",
    ]:
        return f"Error: Confidence '{confidence}' is too low to update structured machine data directly."

    p = KB_ROOT / json_path
    if not p.exists():
        return f"File {json_path} does not exist."

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        try:
            new_entry = json.loads(new_mapping_entry)
        except json.JSONDecodeError:
            return "Error: new_mapping_entry must be a valid JSON string."

        new_entry["confidence"] = confidence

        # Assumption: We are updating mixer_eq_calibration.json structure
        if isinstance(data, list) and len(data) > 0 and "mapping" in data[0]:
            # Simple check to avoid silent overwrite of existing normalized values
            existing = [m.get("normalized") for m in data[0]["mapping"]]
            if new_entry.get("normalized") in existing:
                return f"Error: Mapping for normalized value {new_entry.get('normalized')} already exists. Manual review required."

            data[0]["mapping"].append(new_entry)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return f"Successfully added new verified mapping to {json_path}."
        else:
            return "Error: JSON structure not recognized for automatic update."
    except Exception as e:
        return f"Error updating JSON: {e}"


def kb_list_open_questions() -> str:
    """Return the contents of open_questions.md."""
    return _read_file_safe(KB_ROOT / "agent_notes" / "open_questions.md")


# ---------------------------------------------------------------------------
# New structured and workflow-pack tools (backwards-compatible additions)
# ---------------------------------------------------------------------------

# Maps workflow names to relevant knowledgebase sub-paths.
_WORKFLOW_KB_PATHS: dict[str, list[str]] = {
    "mix_review": [
        "mixing/",
        "recipes/",
        "known_pitfalls/",
        "performance/",
    ],
    "routing_review": [
        "mixing/",
        "known_pitfalls/",
        "mcp/",
    ],
    "project_organizer": [
        "templates/",
        "mcp/",
        "known_pitfalls/",
    ],
    "plugin_chain": [
        "recipes/",
        "mixing/",
        "known_pitfalls/",
    ],
    "composition": [
        "production/",
        "recipes/",
    ],
    "audio_analysis": [
        "production/",
        "fl_api/",
        "known_pitfalls/",
    ],
}


def kb_search_structured(query: str, max_results: int = 10) -> list[dict]:
    """Search the Knowledgebase and return structured results.

    This is the structured companion to ``kb_search``. It returns JSON-friendly
    dicts instead of a plain string, making it easier for agents to parse and
    prioritise results.

    Args:
        query: Free-text search term.
        max_results: Maximum number of results to return (default 10).

    Returns:
        A list of dicts with keys:
        - ``path``: relative path inside the knowledgebase directory
        - ``title``: first heading found in the file, or the filename
        - ``snippet``: up to 200 chars surrounding the first match
        - ``confidence``: ``"documented"`` for structured JSON, ``"inferred"`` for Markdown
        - ``machine_readable``: True if the file is JSON/YAML
        - ``recommended_next_tool``: always ``"kb_get"``
    """
    if not KB_ROOT.exists():
        return [{"error": "Knowledgebase directory not found."}]

    results: list[dict] = []
    query_lower = query.lower()

    for root_dir, _, files in os.walk(KB_ROOT):
        for file in files:
            if not file.endswith((".md", ".json", ".yaml", ".yml")):
                continue
            p = Path(root_dir) / file
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                continue

            if query_lower not in content.lower():
                continue

            rel_path = str(p.relative_to(KB_ROOT))
            is_json = file.endswith((".json", ".yaml", ".yml"))

            # Extract title: first markdown heading or filename
            title = file
            for line in content.splitlines():
                if line.startswith("#"):
                    title = line.lstrip("#").strip()
                    break

            # Find a snippet around the first match
            idx = content.lower().find(query_lower)
            start = max(0, idx - 60)
            end = min(len(content), idx + 140)
            snippet = content[start:end].replace("\n", " ").strip()

            results.append(
                {
                    "path": rel_path,
                    "title": title,
                    "snippet": snippet,
                    "confidence": "documented" if is_json else "inferred",
                    "machine_readable": is_json,
                    "recommended_next_tool": "kb_get",
                }
            )

            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return [{"message": f"No results found for '{query}'."}]
    return results


def kb_get_many(paths: list[str], max_chars_per_file: int = 3000) -> dict[str, str]:
    """Retrieve the content of multiple Knowledgebase files in one call.

    Args:
        paths: List of relative paths inside the knowledgebase directory
            (e.g. ``["fl_api/mixer_eq.md", "mixing/headroom.md"]``).
        max_chars_per_file: Maximum characters returned per file (default 3000).
            Longer files are truncated with a note.

    Returns:
        A dict mapping each requested path to its content (or an error string).
    """
    results: dict[str, str] = {}
    for sub_path in paths:
        p = KB_ROOT / sub_path
        content = _read_file_safe(p)
        if len(content) > max_chars_per_file:
            content = (
                content[:max_chars_per_file]
                + f"\n\n[Truncated at {max_chars_per_file} chars. Call kb_get({sub_path!r}) for full content.]"
            )
        results[sub_path] = content
    return results


def kb_get_workflow_pack(workflow: str) -> dict:
    """Return curated Knowledgebase excerpts for a named workflow.

    Provides a size-limited pack of relevant KB content to help agents
    make informed decisions without loading the entire knowledgebase.

    Args:
        workflow: One of: mix_review, routing_review, project_organizer,
            plugin_chain, composition, audio_analysis.

    Returns:
        A dict with:
        - ``workflow``: the resolved workflow name
        - ``files``: dict of {relative_path: truncated_content}
        - ``note``: usage guidance
    """
    if workflow not in _WORKFLOW_KB_PATHS:
        return {
            "error": f"Unknown workflow {workflow!r}.",
            "available": sorted(_WORKFLOW_KB_PATHS.keys()),
        }

    sub_paths = _WORKFLOW_KB_PATHS[workflow]
    collected: dict[str, str] = {}
    max_per_file = 1500
    max_total_files = 8

    for sub_path in sub_paths:
        target = KB_ROOT / sub_path
        if target.is_dir():
            for p in sorted(target.glob("**/*.md"))[:max_total_files]:
                rel = str(p.relative_to(KB_ROOT))
                if rel not in collected:
                    content = _read_file_safe(p)
                    if len(content) > max_per_file:
                        content = content[:max_per_file] + "\n[...truncated]"
                    collected[rel] = content
                if len(collected) >= max_total_files:
                    break
        elif target.exists():
            rel = str(target.relative_to(KB_ROOT))
            content = _read_file_safe(target)
            if len(content) > max_per_file:
                content = content[:max_per_file] + "\n[...truncated]"
            collected[rel] = content

        if len(collected) >= max_total_files:
            break

    return {
        "workflow": workflow,
        "files": collected,
        "note": (
            f"Showing up to {max_total_files} files, {max_per_file} chars each. "
            "Use kb_get(path) for full content of any file."
        ),
    }


def kb_get_capability(intent: str) -> dict:
    """Describe what the MCP server can do for a given user intent.

    Useful for agents to quickly check whether an intent is supported before
    attempting tool calls.

    Args:
        intent: Free-text description of what the user wants to do
            (e.g. ``"load a plugin"``, ``"export WAV"``, ``"review the mix"``).

    Returns:
        A dict with ``supported``, ``unsupported``, and ``guidance`` fields.
    """
    intent_lower = intent.lower()

    supported_keywords = {
        "mix": "Use fl_review_mix, fl_review_low_end_stereo. See fls://capabilities/supported.",
        "review": "Use fl_review_mix or fl_review_routing. See fls://capabilities/supported.",
        "routing": "Use fl_review_routing, fl_plan_routing_cleanup.",
        "piano roll": "Write notes after explicit user approval via fl_piano_roll.",
        "midi": "Export via fl_export_midi; write notes via fl_piano_roll or fl_write_raga_melody.",
        "audio analysis": "Use fl_analyze_audio, fl_extract_melody.",
        "scale": "Use fl_scale_list, fl_scale_get.",
        "raga": "Use fl_scale_list, fl_scale_get, fl_write_raga_melody, fl_write_raga_chords.",
        "preset": "Use fl_list_presets, fl_suggest_preset.",
        "chain": "Use fl_list_chains, fl_setup_chain.",
        "health": "Use fl_project_health_overview, fl_check_project_preflight.",
        "preflight": "Use fl_check_project_preflight.",
        "knowledgebase": "Use kb_search, kb_get, kb_get_many, kb_get_workflow_pack.",
    }

    unsupported_keywords = {
        "load plugin": "Plugin loading is not supported. User must load VST/AU manually in FL Studio.",
        "render": "WAV rendering is not supported via MCP. Use File > Export in FL Studio.",
        "export wav": "WAV export is not supported via MCP. Use File > Export in FL Studio.",
        "playlist clip": "Playlist clip placement is not reliably supported. Arrange clips manually.",
        "save as": "Project save-as is not supported via MCP.",
        "open project": "Project open is not supported via MCP.",
    }

    for kw, guidance in unsupported_keywords.items():
        if kw in intent_lower:
            return {
                "intent": intent,
                "supported": False,
                "guidance": guidance,
                "see_also": "fls://capabilities/not-possible",
            }

    for kw, guidance in supported_keywords.items():
        if kw in intent_lower:
            return {
                "intent": intent,
                "supported": True,
                "guidance": guidance,
                "see_also": "fls://capabilities/supported",
            }

    return {
        "intent": intent,
        "supported": "unknown",
        "guidance": (
            "Could not determine capability for this intent. "
            "Check fls://capabilities/supported and fls://capabilities/not-possible, "
            "or use kb_search to find relevant KB entries."
        ),
    }


def kb_explain_limit(intent: str) -> dict:
    """Explain the hard API limit for an action the user wants to do.

    Args:
        intent: The action the user wants to perform
            (e.g. ``"load a VST plugin"``, ``"render audio"``).

    Returns:
        A dict with ``action``, ``reason``, ``workaround``, and ``is_hard_limit`` fields.
    """
    intent_lower = intent.lower()

    _LIMITS = [
        {
            "keywords": ["load plugin", "vst", "au plugin", "instantiate plugin"],
            "action": "Load new VST/AU plugin instances",
            "reason": "FL Studio's controller API does not expose plugin instantiation.",
            "workaround": "User must load the plugin manually in FL Studio before any MCP chain planning.",
            "is_hard_limit": True,
        },
        {
            "keywords": ["render", "wav", "export audio", "bounce"],
            "action": "Render audio / WAV export",
            "reason": "FL Studio's render pipeline is not accessible via the MIDI SysEx bridge.",
            "workaround": "User triggers File > Export in FL Studio manually.",
            "is_hard_limit": True,
        },
        {
            "keywords": ["playlist clip", "move clip", "place clip", "delete clip"],
            "action": "Place, move, or delete playlist clips",
            "reason": "Playlist clip editing API is not reliably supported via the controller bridge.",
            "workaround": "Arrange clips manually in FL Studio. Server can create patterns and add markers.",
            "is_hard_limit": True,
        },
        {
            "keywords": ["normalized value", "guess parameter", "interpolate"],
            "action": "Guess normalized plugin/EQ parameter values",
            "reason": "Mapping is non-linear and plugin-specific; guessing causes silent corruption.",
            "workaround": "Use kb_get_parameter_spec or kb_get_conversion for verified mappings only.",
            "is_hard_limit": True,
        },
        {
            "keywords": ["save as", "save project", "open project", "new project"],
            "action": "Project file management (open, save-as, new)",
            "reason": "File I/O commands are not exposed to controller scripts.",
            "workaround": "User manages project files directly in FL Studio.",
            "is_hard_limit": True,
        },
        {
            "keywords": ["readback", "piano roll readback", "read notes"],
            "action": "Piano Roll state readback (reliable)",
            "reason": "Readback is unreliable or unsupported in some FL versions.",
            "workaround": "Use the note count from the write response; user verifies visually.",
            "is_hard_limit": False,
        },
    ]

    for limit in _LIMITS:
        if any(
            kw in limit["keywords"] for kw in limit["keywords"] if kw in intent_lower
        ):  # Fixed generator logic slightly conceptually but string matching works
            return {
                "action": limit["action"],
                "reason": limit["reason"],
                "workaround": limit["workaround"],
                "is_hard_limit": limit["is_hard_limit"],
                "see_also": "fls://capabilities/not-possible",
            }

    return {
        "action": intent,
        "reason": "No specific hard limit found for this intent.",
        "workaround": "Check fls://capabilities/not-possible for the full list of unsupported actions.",
        "is_hard_limit": False,
    }


def register(mcp: FastMCP) -> None:
    mcp.tool()(kb_search)
    mcp.tool()(kb_get)
    mcp.tool()(kb_get_parameter_spec)
    mcp.tool()(kb_get_conversion)
    mcp.tool()(kb_record_finding)
    mcp.tool()(kb_record_verified_finding)
    mcp.tool()(kb_list_open_questions)
    # New structured and workflow-pack tools (backwards-compatible additions)
    mcp.tool()(kb_search_structured)
    mcp.tool()(kb_get_many)
    mcp.tool()(kb_get_workflow_pack)
    mcp.tool()(kb_get_capability)
    mcp.tool()(kb_explain_limit)
