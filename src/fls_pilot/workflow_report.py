"""Shared workflow report/proposal contract for user-facing diagnostics."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

CONTRACT_VERSION = "fls-pilot.workflow-report.v1"
RISK_LEVELS = {"read-only", "low", "medium", "high", "unsupported"}


def _compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _compact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_compact_value(v) for v in value]
    return value


def diagnostic(
    *,
    id: str,
    severity: str,
    message: str,
    evidence: Any = None,
    target: Mapping[str, Any] | None = None,
    source: str | None = None,
    kb_rule_ids: list[str] | tuple[str, ...] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(id),
        "severity": str(severity),
        "message": str(message),
        "evidence": _compact_value(evidence),
        "target": dict(target or {}),
        "source": source,
    }
    if kb_rule_ids:
        row["kb_rule_ids"] = [str(rule_id) for rule_id in kb_rule_ids if rule_id]
    if metadata:
        row["metadata"] = _compact_value(dict(metadata))
    return row


def risk_level(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in RISK_LEVELS:
        raise ValueError(f"invalid risk level: {value!r}")
    return normalized


def proposed_change(
    *,
    id: str,
    title: str,
    tool: str,
    observed_state: Any,
    proposed_state: Any,
    safety_class: str,
    risk_level: str,
    readback_expectation: str,
    rollback_expectation: str,
    limitations: list[str] | None = None,
    skipped_changes: list[str] | None = None,
    status: str = "proposed",
    requires_explicit_approval: bool = True,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(id),
        "status": str(status),
        "title": str(title),
        "tool": str(tool),
        "observed_state": _compact_value(observed_state),
        "proposed_state": _compact_value(proposed_state),
        "safety_class": str(safety_class),
        "risk_level": globals()["risk_level"](risk_level),
        "readback_expectation": str(readback_expectation),
        "rollback_expectation": str(rollback_expectation),
        "requires_explicit_approval": bool(requires_explicit_approval),
    }
    if limitations:
        row["limitations"] = [str(x) for x in limitations]
    if skipped_changes:
        row["skipped_changes"] = _compact_value(skipped_changes)
    return row


def applied_change(
    *,
    id: str,
    title: str,
    tool: str,
    before: Any,
    requested_change: Any,
    after: Any,
    safety_class: str,
    risk_level: str,
    change_id: str | None,
    readback_ok: bool | None,
    rollback: Mapping[str, Any] | None = None,
    rollback_command: str | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": str(id),
        "status": "applied",
        "title": str(title),
        "tool": str(tool),
        "before": _compact_value(before),
        "requested_change": _compact_value(requested_change),
        "after": _compact_value(after),
        "safety_class": str(safety_class),
        "risk_level": globals()["risk_level"](risk_level),
        "change_id": change_id,
        "readback_ok": readback_ok,
    }
    if rollback:
        row["rollback"] = _compact_value(dict(rollback))
    if rollback_command:
        row["rollback_command"] = str(rollback_command)
    if limitations:
        row["limitations"] = [str(x) for x in limitations]
    return row


def render_markdown(report: Mapping[str, Any]) -> str:
    title = report.get("title") or report.get("workflow") or "Workflow report"
    lines = [f"# {title}", ""]
    lines.append(f"- Contract: `{report.get('contract_version')}`")
    lines.append(f"- Workflow: `{report.get('workflow')}`")
    lines.append(f"- Mode: `{report.get('mode')}`")
    status = report.get("status")
    if status:
        lines.append(f"- Status: {status}")
    summary = report.get("summary")
    if summary:
        lines.append(f"- Summary: {_summary_text(summary)}")

    _append_rows(lines, "Diagnostics", report.get("diagnostics") or [], _diagnostic_line)
    _append_rows(
        lines,
        "Proposed Changes",
        report.get("proposed_changes") or [],
        _proposed_change_line,
    )
    _append_rows(
        lines,
        "Applied Changes",
        report.get("applied_changes") or [],
        _applied_change_line,
    )
    _append_rows(lines, "Manual Checks", report.get("manual_checks") or [], _manual_check_line)

    notes = report.get("notes") or []
    if notes:
        lines.extend(["", "## Notes"])
        for note in notes:
            lines.append(f"- {note}")

    return "\n".join(lines).rstrip() + "\n"


def workflow_report(
    *,
    workflow: str,
    title: str,
    mode: str,
    status: str,
    summary: Mapping[str, Any] | str | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    proposed_changes: list[dict[str, Any]] | None = None,
    applied_changes: list[dict[str, Any]] | None = None,
    skipped_changes: list[dict[str, Any]] | None = None,
    manual_checks: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
    limits: list[str] | None = None,
    kb_policy_refs: list[dict[str, Any]] | None = None,
    ok: bool = True,
    safety: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ok": bool(ok),
        "contract_version": CONTRACT_VERSION,
        "workflow": str(workflow),
        "title": str(title),
        "mode": str(mode),
        "status": str(status),
        "summary": _compact_value(summary or {}),
        "diagnostics": diagnostics or [],
        "proposed_changes": proposed_changes or [],
        "applied_changes": applied_changes or [],
        "skipped_changes": skipped_changes or [],
        "manual_checks": manual_checks or [],
        "notes": notes or [],
        "limits": limits or [],
        "safety": {
            "read_only": not bool(applied_changes),
            "requires_explicit_approval": bool(proposed_changes),
            "proposal_first": True,
            **dict(safety or {}),
        },
        "kb_policy_refs": kb_policy_refs or [],
        "metadata": _compact_value(dict(metadata or {})),
    }
    json_report = deepcopy(base)
    base["json_report"] = json_report
    base["markdown_report"] = render_markdown(json_report)
    return base


def approval_required_report(
    *,
    workflow: str,
    title: str,
    proposed_changes: list[dict[str, Any]],
    notes: list[str] | None = None,
) -> dict[str, Any]:
    return workflow_report(
        workflow=workflow,
        title=title,
        mode="approval_required",
        status="Approval required",
        summary={"proposed_changes": len(proposed_changes), "applied_changes": 0},
        proposed_changes=proposed_changes,
        notes=[
            "No FL Studio project state was changed.",
            "Re-call the apply tool with approved=True only after explicit user approval.",
            *(notes or []),
        ],
        ok=False,
        safety={
            "read_only": True,
            "requires_explicit_approval": True,
            "approval_received": False,
        },
    )


def _summary_text(summary: Any) -> str:
    if isinstance(summary, dict):
        return ", ".join(f"{key}={value}" for key, value in summary.items())
    return str(summary)


def _append_rows(lines, heading, rows, formatter):
    if not rows:
        return
    lines.extend(["", f"## {heading}"])
    for row in rows:
        lines.append(formatter(row))


def _diagnostic_line(row):
    evidence = row.get("evidence")
    suffix = f" Evidence: {evidence}" if evidence not in (None, "", {}) else ""
    return f"- [{row.get('severity')}] `{row.get('id')}`: {row.get('message')}{suffix}"


def _proposed_change_line(row):
    tool = row.get("tool")
    msg = (
        f"- [risk: {row.get('risk_level')}] `{row.get('id')}`: "
        f"{row.get('title')} via `{tool}`. Approval required: "
        f"{str(row.get('requires_explicit_approval')).lower()}"
    )
    hints = []
    if row.get("readback_expectation"):
        hints.append(f"readback: {row.get('readback_expectation')}")
    if row.get("rollback_expectation"):
        hints.append(f"rollback: {row.get('rollback_expectation')}")
    if hints:
        msg += f" ({', '.join(hints)})"
    return msg


def _applied_change_line(row):
    change = row.get("change_id") or "no change_id"
    msg = (
        f"- [risk: {row.get('risk_level')}] `{row.get('id')}`: "
        f"{row.get('title')} via `{row.get('tool')}`. Change: `{change}`"
    )
    hints = []
    if row.get("readback_ok") is not None:
        hints.append(f"readback_ok: {str(row.get('readback_ok')).lower()}")
    if row.get("rollback_command"):
        hints.append(f"rollback: {row.get('rollback_command')}")
    elif row.get("rollback"):
        hints.append("rollback: available")
    if hints:
        msg += f" ({', '.join(hints)})"
    return msg


def _manual_check_line(row):
    topic = row.get("topic") or row.get("id") or "manual_check"
    check = row.get("check") or row.get("message") or row
    return f"- `{topic}`: {check}"
