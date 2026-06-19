#!/usr/bin/env python3
"""Validate evals/evals.json as a prompt/tool-surface contract."""

import json
import re
import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fls_pilot import server as server_module

EVALS_FILE = ROOT / "evals" / "evals.json"

ALLOWED_ROOT_FIELDS = {
    "schema_version",
    "suite",
    "description",
    "evals",
    "target_package",
    "target_version",
    "last_updated",
    "source_of_truth",
    "surface_baseline",
    "global_expectations"
}

ALLOWED_EVAL_FIELDS = {
    "id",
    "prompt",
    "expected_tools",
    "expected_tool_actions",
    "safety_expectations",
    "expected_prompts",
    "expected_resources",
    "not_expected_tools",
    "success_criteria"
}

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ACTION_PATTERN = re.compile(r"^([^:]+):\s*(.+)$")

def print_error(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)

def get_public_tools() -> set[str]:
    mcp = server_module.build_server()
    async def list_tools():
        return list(await mcp.list_tools())
    tools = asyncio.run(list_tools())
    return {tool.name for tool in tools}

def validate_evals() -> int:
    if not EVALS_FILE.exists():
        print_error(f"{EVALS_FILE} does not exist.")
        return 1

    try:
        with open(EVALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in {EVALS_FILE}: {e}")
        return 1

    if not isinstance(data, dict):
        print_error("Root value is not an object.")
        return 1

    for key in ["schema_version", "suite", "evals"]:
        if key not in data:
            print_error(f"Missing required root field: '{key}'")
            return 1

    if data["schema_version"] not in (1, 2):
        print_error(f"Unsupported schema_version: {data['schema_version']}")
        return 1

    if not isinstance(data["suite"], str) or not data["suite"]:
        print_error("'suite' must be a non-empty string.")
        return 1

    if not isinstance(data["evals"], list) or not data["evals"]:
        print_error("'evals' must be a non-empty array.")
        return 1

    for key in data.keys():
        if key not in ALLOWED_ROOT_FIELDS:
            print_error(f"Unknown root field: '{key}'")
            return 1

    public_tools = get_public_tools()
    seen_ids = set()

    for i, eval_entry in enumerate(data["evals"]):
        if not isinstance(eval_entry, dict):
            print_error(f"Eval entry at index {i} is not an object.")
            return 1

        eval_id = eval_entry.get("id")
        if not isinstance(eval_id, str) or not eval_id:
            print_error(f"Eval entry at index {i} has missing or empty 'id'.")
            return 1

        if eval_id in seen_ids:
            print_error(f"Duplicate eval id '{eval_id}'.")
            return 1
        seen_ids.add(eval_id)

        if not ID_PATTERN.match(eval_id):
            print_error(f"Eval id '{eval_id}' does not match required pattern.")
            return 1

        prompt = eval_entry.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            print_error(f"Eval id '{eval_id}' has missing or empty 'prompt'.")
            return 1

        expected_tools = eval_entry.get("expected_tools")
        if not isinstance(expected_tools, list) or not expected_tools:
            print_error(f"Eval id '{eval_id}' has missing or empty 'expected_tools'.")
            return 1

        seen_tools = set()
        for tool in expected_tools:
            if not isinstance(tool, str) or not tool:
                print_error(f"Eval id '{eval_id}' has an empty string in 'expected_tools'.")
                return 1
            if tool in seen_tools:
                print_error(f"Eval id '{eval_id}' has duplicate expected tool '{tool}'.")
                return 1
            seen_tools.add(tool)

            if tool not in public_tools:
                print_error(f"Eval id '{eval_id}' references unknown tool '{tool}'.")
                return 1

        safety_expectations = eval_entry.get("safety_expectations")
        if not isinstance(safety_expectations, list) or not safety_expectations:
            print_error(f"Eval id '{eval_id}' has missing or empty 'safety_expectations'.")
            return 1
        for sf in safety_expectations:
            if not isinstance(sf, str) or not sf:
                print_error(f"Eval id '{eval_id}' has an empty string in 'safety_expectations'.")
                return 1

        expected_tool_actions = eval_entry.get("expected_tool_actions", [])
        if not isinstance(expected_tool_actions, list):
            print_error(f"Eval id '{eval_id}' 'expected_tool_actions' must be an array.")
            return 1
        for action in expected_tool_actions:
            if not isinstance(action, str) or not action:
                print_error(f"Eval id '{eval_id}' has an empty string in 'expected_tool_actions'.")
                return 1
            
            match = ACTION_PATTERN.match(action)
            if not match:
                print_error(f"Eval id '{eval_id}' action '{action}' does not match format '<tool>: <action>'.")
                return 1
            
            tool_part, action_part = match.groups()
            tool_part = tool_part.strip()
            if tool_part not in expected_tools:
                print_error(f"Eval id '{eval_id}' action '{action}' references tool '{tool_part}' not in 'expected_tools'.")
                return 1

        for key in eval_entry.keys():
            if key not in ALLOWED_EVAL_FIELDS:
                print_error(f"eval id '{eval_id}': unknown field '{key}'")
                return 1

    print("evals contract check passed")
    return 0

if __name__ == "__main__":
    sys.exit(validate_evals())
