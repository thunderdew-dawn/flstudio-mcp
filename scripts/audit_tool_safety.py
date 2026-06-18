#!/usr/bin/env python3
"""Static safety audit for FastMCP tools.

This is intentionally conservative. It does not prove a write tool is safe; it
flags tools that appear to mutate FL Studio without using the MCP safety layer.
Run it before adding new FL-write capabilities:

    python scripts/audit_tool_safety.py
    python scripts/audit_tool_safety.py --fail-on-gaps
"""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "src" / "fls_pilot" / "tools"
PROTOCOL = ROOT / "src" / "fls_pilot" / "protocol.py"


WRITE_CONSTANTS = {
    "CMD_SET_TEMPO",
    "CMD_SET_TIME_SIG",
    "CMD_GENERAL_UNDO",
    "CMD_MIXER_SET_VOLUME",
    "CMD_MIXER_SET_PAN",
    "CMD_MIXER_SET_MUTE",
    "CMD_MIXER_SET_SOLO",
    "CMD_MIXER_SET_NAME",
    "CMD_MIXER_SELECT_TRACK",
    "CMD_MIXER_SET_STEREO_SEP",
    "CMD_CHANNEL_SET_VOLUME",
    "CMD_CHANNEL_SET_PAN",
    "CMD_CHANNEL_SET_MUTE",
    "CMD_CHANNEL_SET_SOLO",
    "CMD_CHANNEL_SELECT",
    "CMD_CHANNEL_SET_NAME",
    "CMD_CHANNEL_SET_TARGET",
    "CMD_CHANNEL_SET_STEPS",
    "CMD_PATTERN_SELECT",
    "CMD_PATTERN_RENAME",
    "CMD_PATTERN_SET_COLOR",
    "CMD_PATTERN_SET_LENGTH",
    "CMD_PLAYLIST_SET_MUTE",
    "CMD_PLAYLIST_SET_SOLO",
    "CMD_PLAYLIST_SET_NAME",
    "CMD_PLAYLIST_SET_COLOR",
    "CMD_PLAYLIST_SELECT_TRACK",
    "CMD_MIXER_SET_ROUTE",
    "CMD_MIXER_SET_COLOR",
    "CMD_CHANNEL_SET_COLOR",
    "CMD_MIXER_SET_SLOT_MIX",
    "CMD_MIXER_SET_TRACK_SLOTS",
    "CMD_MIXER_SET_SLOT_ENABLED",
    "CMD_MIXER_SET_EQ",
    "CMD_PLUGIN_SET_PARAM",
    "CMD_PLUGIN_PRESET",
    "CMD_ARRANGE_NEW_PATTERN",
    "CMD_ARRANGE_CLONE_PATTERN",
    "CMD_ARRANGE_ADD_MARKER",
}

SAFETY_CLASS_TO_CONTRACT = {
    "read-only": "read-only",
    "transient": "transient",
    "external-write": "external-write",
    "server-state": "server-state",
    "write-safe-required": "write-safe-required",
    "write-gap": "write-gap",
    "needs-review": "needs-review",
    "forbidden": "forbidden",
}

TRANSIENT_CONSTANTS = {
    "CMD_PLAY",
    "CMD_STOP",
    "CMD_PAUSE",
    "CMD_TOGGLE_PLAY",
    "CMD_RECORD",
    "CMD_SET_SONG_POS",
    "CMD_ENSURE_PIANO_ROLL",
}

READ_PREFIXES = ("CMD_GET_", "CMD_MIXER_GET_", "CMD_CHANNEL_GET_", "CMD_PATTERN_GET_")
READ_CONSTANTS = {
    "CMD_PING",
    "CMD_GET_PROJECT_STATE",
    "CMD_MIXER_LIST_TRACKS",
    "CMD_CHANNEL_LIST",
    "CMD_PATTERN_LIST",
    "CMD_PLUGIN_LIST",
    "CMD_PLUGIN_GET_PARAMS",
    "CMD_PLUGIN_LIST_PARAMS",
    "CMD_PLUGIN_GET_PARAM",
    "CMD_PLUGIN_GET_PRESET_NAME",
    "CMD_MIXER_GET_ROUTING",
    "CMD_MIXER_GET_ROUTING_ALL",
    "CMD_CHANNEL_ROUTING_SUMMARY",
    "CMD_CHANNEL_SELECTED",
    "CMD_MIXER_GET_PEAKS",
    "CMD_API_PROBE",
}

SERVER_STATE_TOOLS = {
    "fl_set_dry_run",
    "fl_take_snapshot",
    "fl_rollback_last_change",
    "fl_rollback_change",
}
EXTERNAL_WRITE_TOOLS = {"fl_export_midi", "fl_export_change_log"}
APPROVED_SAFE_WRITE_HELPERS = {"safe_set_steps"}


@dataclass
class ToolAudit:
    name: str
    title: str
    path: Path
    line: int
    read_only_hint: bool | None
    destructive_hint: bool | None
    safety_class_annotation: str | None
    contract_safety_class: str
    has_safety_doc: bool
    status: str
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "path": _rel(self.path),
            "line": self.line,
            "read_only_hint": self.read_only_hint,
            "destructive_hint": self.destructive_hint,
            "safety_class_annotation": self.safety_class_annotation,
            "contract_safety_class": self.contract_safety_class,
            "has_safety_doc": self.has_safety_doc,
            "status": self.status,
            "evidence": self.evidence,
        }


def _literal(value: ast.AST) -> Any:
    try:
        return ast.literal_eval(value)
    except Exception:
        return None


def _dict_from_ast(node: ast.AST, known_dicts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if isinstance(node, ast.Name):
        return dict(known_dicts.get(node.id, {}))
    if not isinstance(node, ast.Dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in zip(node.keys, node.values, strict=False):
        if key is None:
            if isinstance(value, ast.Name):
                out.update(known_dicts.get(value.id, {}))
            continue
        k = _literal(key)
        if isinstance(k, str):
            out[k] = _literal(value)
    return out


def _collect_known_dicts(tree: ast.AST) -> dict[str, dict[str, Any]]:
    known: dict[str, dict[str, Any]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = _dict_from_ast(node.value, known)
        if not value:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                known[target.id] = value
    return known


def _is_mcp_tool_decorator(node: ast.AST) -> ast.Call | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "tool":
        return node
    return None


def _tool_annotations(call: ast.Call, known_dicts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    for kw in call.keywords:
        if kw.arg == "annotations":
            return _dict_from_ast(kw.value, known_dicts)
    return {}


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Attribute):
        base = _call_name(func.value) if isinstance(func.value, ast.Call) else ""
        if isinstance(func.value, ast.Name):
            base = func.value.id
        return f"{base}.{func.attr}" if base else func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _protocol_constants(node: ast.AST) -> set[str]:
    constants: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "protocol"
            and child.attr.startswith("CMD_")
        ):
            constants.add(child.attr)
    return constants


def _constant_class(name: str) -> str:
    if name in WRITE_CONSTANTS:
        return "write"
    if name in TRANSIENT_CONSTANTS:
        return "transient"
    if name in READ_CONSTANTS or name.startswith(READ_PREFIXES):
        return "read"
    if name.startswith("CMD_") and "_SET_" in name:
        return "write"
    if name.startswith("CMD_") and ("_GET_" in name or "_LIST" in name):
        return "read"
    return "unknown"


@dataclass
class FunctionEffects:
    uses_safe: bool
    uses_apply_notes: bool
    protocol_constants: set[str]


def _function_effects(fn: ast.FunctionDef) -> FunctionEffects:
    calls = [_call_name(n) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    constants = _protocol_constants(fn)
    has_safe = any(
        name.endswith(
            ("safety.safe_write", "safety.safe_write_group", "safety.safe_piano_roll_write")
        )
        or name in APPROVED_SAFE_WRITE_HELPERS
        for name in calls
    )
    has_apply_notes = any(name.endswith("apply_notes") for name in calls)
    return FunctionEffects(has_safe, has_apply_notes, constants)


def _classify_tool(
    fn: ast.FunctionDef,
    annotations: dict[str, Any],
    helper_effects: dict[str, FunctionEffects],
) -> tuple[str, str]:
    calls = [_call_name(n) for n in ast.walk(fn) if isinstance(n, ast.Call)]
    effects = _function_effects(fn)
    constants = set(effects.protocol_constants)
    helper_calls = sorted({name for name in calls if name in helper_effects})
    for name in helper_calls:
        helper = helper_effects[name]
        constants.update(helper.protocol_constants)
    classes = {_constant_class(c) for c in constants}

    has_safe = effects.uses_safe or any(helper_effects[name].uses_safe for name in helper_calls)
    has_apply_notes = effects.uses_apply_notes or any(
        helper_effects[name].uses_apply_notes for name in helper_calls
    )

    evidence_bits: list[str] = []
    if annotations:
        evidence_bits.append(
            "annotation readOnlyHint={!r} destructiveHint={!r}".format(
                annotations.get("readOnlyHint"), annotations.get("destructiveHint")
            )
        )
    if constants:
        evidence_bits.append(f"protocol={','.join(sorted(constants))}")
    if has_safe:
        evidence_bits.append("uses safety layer")
    if has_apply_notes:
        evidence_bits.append("uses piano-roll apply_notes")
    if helper_calls:
        evidence_bits.append(f"helper_calls={','.join(sorted(helper_calls))}")

    if fn.name in SERVER_STATE_TOOLS:
        return "server-state", "; ".join(evidence_bits) or "server-only state"
    if fn.name in EXTERNAL_WRITE_TOOLS:
        return "external-write", "; ".join(evidence_bits) or "writes outside FL"
    if has_safe:
        return "write-safe-required", "; ".join(evidence_bits)
    if has_apply_notes:
        return "write-gap", "; ".join(evidence_bits)
    if "write" in classes:
        return "write-gap", "; ".join(evidence_bits)
    if "transient" in classes and classes <= {"transient", "read"}:
        return "transient", "; ".join(evidence_bits)
    if annotations.get("readOnlyHint") is False:
        return "needs-review", "; ".join(evidence_bits)
    if constants and classes <= {"read"}:
        return "read-only", "; ".join(evidence_bits)
    if annotations.get("readOnlyHint") is True:
        return "read-only", "; ".join(evidence_bits)
    return "needs-review", "; ".join(evidence_bits) or "no static evidence"


def _expected_safety_class(status: str) -> str:
    return {
        "read-only": "read-only",
        "transient": "transient",
        "external-write": "external-write",
        "server-state": "server-state",
        "write-safe-required": "write-safe-required",
        "write-gap": "write-gap",
        "needs-review": "needs-review",
        "forbidden": "forbidden",
    }.get(status, status)


def _contract_safety_class(status: str) -> str:
    return SAFETY_CLASS_TO_CONTRACT.get(status, status)


def audit_file(path: Path) -> list[ToolAudit]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    known_dicts = _collect_known_dicts(tree)
    helper_effects = {
        node.name: _function_effects(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    audits: list[ToolAudit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        decos = [_is_mcp_tool_decorator(d) for d in node.decorator_list]
        decos = [d for d in decos if d is not None]
        if not decos:
            continue
        annotations = _tool_annotations(decos[0], known_dicts)
        status, evidence = _classify_tool(node, annotations, helper_effects)
        doc = ast.get_docstring(node) or ""
        safety_class = annotations.get("safetyClass")
        expected_safety = _expected_safety_class(status)
        if safety_class:
            evidence = (
                f"{evidence}; safetyClass={safety_class!r}"
                if evidence
                else f"safetyClass={safety_class!r}"
            )
        if safety_class and safety_class != expected_safety:
            evidence = f"{evidence}; safetyClass expected {expected_safety!r}"
        if "Safety:" in doc:
            evidence = f"{evidence}; doc_safety=True" if evidence else "doc_safety=True"
        audits.append(
            ToolAudit(
                name=node.name,
                title=str(annotations.get("title") or ""),
                path=path,
                line=node.lineno,
                read_only_hint=annotations.get("readOnlyHint"),
                destructive_hint=annotations.get("destructiveHint"),
                safety_class_annotation=safety_class,
                contract_safety_class=_contract_safety_class(status),
                has_safety_doc="Safety:" in doc,
                status=status,
                evidence=evidence,
            )
        )
    return audits


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def print_markdown(audits: list[ToolAudit]) -> None:
    counts = count_by_status(audits)

    print("# Tool Safety Audit")
    print()
    for key in sorted(counts):
        print(f"- `{key}`: {counts[key]}")
    print()
    print("| Status | Contract | Tool | Location | Evidence |")
    print("|---|---|---|---|---|")
    for audit in sorted(audits, key=lambda a: (a.status, _rel(a.path), a.line)):
        location = f"{_rel(audit.path)}:{audit.line}"
        evidence = audit.evidence.replace("|", "\\|")
        title = f" ({audit.title})" if audit.title else ""
        print(
            f"| `{audit.status}` | `{audit.contract_safety_class}` | "
            f"`{audit.name}`{title} | `{location}` | {evidence} |"
        )


def count_by_status(audits: list[ToolAudit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for audit in audits:
        counts[audit.status] = counts.get(audit.status, 0) + 1
    return counts


def print_json(audits: list[ToolAudit]) -> None:
    payload = {
        "summary": count_by_status(audits),
        "tools": [
            audit.to_dict() for audit in sorted(audits, key=lambda a: (_rel(a.path), a.line))
        ],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-on-gaps",
        action="store_true",
        help="Exit non-zero if write gaps or unresolved needs-review tools are found.",
    )
    parser.add_argument(
        "--max-write-gaps", type=int, help="Exit non-zero if write gaps exceed this baseline."
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format. Default: markdown.",
    )
    parser.add_argument(
        "--fail-on-missing-safety-docs",
        action="store_true",
        help="Exit non-zero if tools lack Safety: docstrings or safetyClass annotations.",
    )
    args = parser.parse_args()

    audits: list[ToolAudit] = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        audits.extend(audit_file(path))

    if args.format == "json":
        print_json(audits)
    else:
        print_markdown(audits)

    gap_count = count_by_status(audits).get("write-gap", 0)
    if args.fail_on_gaps and any(a.status in {"write-gap", "needs-review"} for a in audits):
        return 1
    if args.fail_on_missing_safety_docs:
        missing = [
            a
            for a in audits
            if not a.has_safety_doc or a.safety_class_annotation != _expected_safety_class(a.status)
        ]
        if missing:
            return 1
    if args.max_write_gaps is not None and gap_count > args.max_write_gaps:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
