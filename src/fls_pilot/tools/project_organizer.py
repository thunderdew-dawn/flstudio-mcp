"""Project Organizer tools for FL Studio Pilot.

Handles broad project standardization, naming conventions, color coding,
and structural cleanup.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .. import kb_policy, operations, safety
from .. import project_templates as templates
from .. import workflow_report as wr
from ..analysis import (
    EVIDENCE_TYPE_NAME_BASED_DETECTION,
    EVIDENCE_TYPE_ROUTING_BASED_DETECTION,
    get_analysis_broker,
    heuristic_validation_metadata,
)
from ..connection import get_bridge
from ..runtime.interactions import InteractionRequest
from .channels import _find_free_mixer_track
from .color import parse_color
from .routing import _bus_rename_entry, _route_write_entry

_ORGANIZER_APPLY_TOOLS = {
    "fl_apply_project_cleanup_step",
    "fl_apply_naming_standard",
    "fl_apply_color_standard",
    "fl_apply_routing_cleanup",
    "fl_apply_bus_layout",
    "fl_group_tracks",
}
ORGANIZER_VALIDATION_REQUEST_ID = "organizer.confirm_cleanup_heuristics"
ORGANIZER_PLAN_APPROVAL_REQUEST_ID = "organizer.approve_organization_plan"
ORGANIZER_STEP_SELECTION_REQUEST_ID = "organizer.approve_step_selection"
ORGANIZER_TEMPLATE_SELECTION_REQUEST_ID = "organizer.choose_target_template"
_PLAN_TTL_SECONDS = 30 * 60
_APPLYABLE_DECISIONS = {"approved_for_apply"}
_SUPPRESSED_DECISIONS = {"rejected", "ignored"}
_SAFE_STEP_TOOLS = {
    "fl_apply_project_cleanup_step",
    "fl_apply_routing_cleanup",
    "fl_apply_bus_layout",
    "fl_group_tracks",
}
_SAFE_RISK_LEVELS = {"low", "medium"}
_SAFE_ACTION_TYPES = {"rename", "color", "route_channel", "group_to_bus", "create_bus_layout"}
_REVIEW_ONLY_BLOCK_REASONS = {"name_based_step_requires_user_confirmation"}
_PLAN_STORE: dict[str, dict] = {}


def _looks_default_channel_name(name) -> bool:
    if not name:
        return True
    return str(name).split(" ")[0] in ("Channel", "Sampler", "Insert", "AudioClip")


def _color_params(spec: str) -> dict:
    rgb = parse_color(spec)
    if rgb is None:
        raise ValueError(f"unknown color {spec!r}; pass a known color name or hex like '#33A1FF'")
    r, g, b = rgb
    return {"r": r, "g": g, "b": b}


def _color_write_entry(channel: int, color_spec: str) -> dict:
    params = {"channel": channel, **_color_params(color_spec)}
    return operations.prepare_operation("channel", "set_color", params).safe_write_group_entry()


def _mixer_color_entry(track: int, color_spec: str) -> dict:
    params = {"track": track, **_color_params(color_spec)}
    return operations.prepare_operation("mixer", "set_color", params).safe_write_group_entry()


def _channel_rename_entry(channel: int, name: str) -> dict:
    return operations.prepare_operation(
        "channel", "set_name", {"channel": channel, "name": name}
    ).safe_write_group_entry()


def _channel_index(row: dict) -> int:
    return int(row.get("channel", row.get("i", row.get("index", 0))))


def _suggest_channel_name(row: dict) -> str:
    idx = _channel_index(row)
    target_name = str(row.get("target_name") or "").strip()
    if target_name and target_name.lower() != "master" and not target_name.startswith("Insert "):
        return target_name
    label = str((row.get("type") or {}).get("label") or "channel").strip() or "channel"
    if label == "audioclip":
        return f"Audio Clip {idx}"
    if label == "genplug":
        return f"Instrument {idx}"
    return f"Channel {idx}"


def _organizer_validation_metadata(evidence_type: str, *, reason: str) -> dict:
    return heuristic_validation_metadata(
        evidence_type=evidence_type,
        interaction_request_id=ORGANIZER_VALIDATION_REQUEST_ID,
        reason=reason,
    )


def _organizer_validation_request(diagnostics: list[dict]) -> dict | None:
    options = [
        {
            "id": str(row.get("id")),
            "label": str(row.get("message") or row.get("id")),
            "reason": dict(row.get("metadata") or {}).get("reason"),
        }
        for row in diagnostics
        if isinstance(row.get("metadata"), dict)
        and row["metadata"].get("human_validation_required")
    ]
    if not options:
        return None
    return InteractionRequest(
        id=ORGANIZER_VALIDATION_REQUEST_ID,
        type="multi_select",
        title="Confirm organizer cleanup candidates",
        prompt=(
            "Which organizer cleanup diagnostics are intentional or should be kept "
            "before applying a cleanup plan?"
        ),
        options=tuple(options),
        allow_remove=True,
        metadata={
            "reason": "heuristic_cleanup_validation",
            "finding_ids": [row["id"] for row in options],
        },
    ).to_dict()


def _utc_timestamp() -> float:
    return time.time()


def _stable_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _store_plan(plan: dict) -> dict:
    _enrich_plan_contract_fields(plan)
    stored = {
        "plan_id": plan["plan_id"],
        "project_fingerprint": plan["project_fingerprint"],
        "plan_hash": plan["plan_hash"],
        "created_at": plan["created_at"],
        "expires_at": plan["expires_at"],
        "steps": [dict(row) for row in plan.get("steps") or []],
        "target_template": dict(plan.get("target_template") or {}),
        "user_decisions": [dict(row) for row in plan.get("user_decisions") or []],
        "snapshot_id": plan.get("snapshot_id"),
        "full_plan": json.loads(_stable_json(plan)),
    }
    _PLAN_STORE[plan["plan_id"]] = stored
    return stored


def _plan_hash_payload(plan: dict) -> dict:
    return {
        "project_fingerprint": plan.get("project_fingerprint"),
        "snapshot_id": plan.get("snapshot_id"),
        "source_observation_ids": plan.get("source_observation_ids") or [],
        "target_template": plan.get("target_template") or {},
        "template_match_status": plan.get("template_match_status"),
        "steps": plan.get("steps") or [],
        "blocked_steps": plan.get("blocked_steps") or [],
        "manual_checks": plan.get("manual_checks") or [],
        "user_decisions": plan.get("user_decisions") or [],
    }


def _decision_subject(decision: dict) -> str:
    for key in ("step_id", "finding_id", "target_id", "id"):
        value = str(decision.get(key) or "").strip()
        if value:
            return value
    selected = decision.get("selected")
    if isinstance(selected, list) and len(selected) == 1:
        return str(selected[0])
    return ""


def _decisions_by_subject(user_decisions: list[dict]) -> dict[str, dict]:
    out = {}
    for row in user_decisions:
        if not isinstance(row, dict):
            continue
        subject = _decision_subject(row)
        if subject:
            out[subject] = dict(row)
    return out


def _merge_user_decisions(existing: list[dict], incoming: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    passthrough: list[dict] = []
    for row in [*existing, *incoming]:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        subject = _decision_subject(item)
        if subject:
            merged[subject] = item
        else:
            passthrough.append(item)
    return [*passthrough, *merged.values()]


def _selected_target_template(user_decisions: list[dict]) -> str | None:
    for row in reversed(user_decisions):
        request_id = str(
            row.get("interaction_request_id") or row.get("interaction_id") or row.get("id") or ""
        ).strip()
        if request_id not in {
            ORGANIZER_TEMPLATE_SELECTION_REQUEST_ID,
            "organizer.confirm_template_profile",
            "template.confirm_profile",
        }:
            continue
        if bool(row.get("skipped")):
            continue
        selected = row.get("selected_template") or row.get("template_slug") or row.get("value")
        if selected is None and isinstance(row.get("selected"), list) and row["selected"]:
            selected = row["selected"][0]
        if selected:
            return str(selected).strip()
    return None


def _profile_track_by_index(profile: dict) -> dict[int, dict]:
    tracks = {}
    for row in profile.get("mixer_tracks") or []:
        if not isinstance(row, dict):
            continue
        idx = row.get("index")
        if isinstance(idx, bool) or idx is None:
            continue
        try:
            tracks[int(idx)] = dict(row)
        except (TypeError, ValueError):
            continue
    return tracks


def _profile_channel_routes(profile: dict) -> dict[int, dict]:
    routes = {}
    for row in profile.get("channel_routes") or []:
        if not isinstance(row, dict):
            continue
        idx = row.get("channel_index")
        if isinstance(idx, bool) or idx is None:
            continue
        try:
            routes[int(idx)] = dict(row)
        except (TypeError, ValueError):
            continue
    return routes


def _mixer_track_index(row: dict) -> int:
    return int(row.get("i", row.get("index", row.get("track", 0))))


def _step_decision_state(step_id: str, user_decisions: list[dict]) -> tuple[str, dict | None]:
    decision = _decisions_by_subject(user_decisions).get(step_id)
    if not decision:
        return "unresolved", None
    value = str(decision.get("decision") or "").strip().lower()
    if value in {"accepted", "selected"}:
        return "accepted", decision
    if value in _SUPPRESSED_DECISIONS:
        return value, decision
    if value in _APPLYABLE_DECISIONS:
        return "approved_for_apply", decision
    return "unresolved", decision


def _organizer_step(
    *,
    id: str,
    action_type: str,
    tool: str,
    target: dict,
    observed_state: dict,
    proposed_state: dict,
    reason: str,
    evidence_type: str,
    confidence: str,
    risk_level: str,
    rollback_unit: str,
    user_decisions: list[dict],
    blocked_reason: str | None = None,
) -> dict:
    decision_state, decision = _step_decision_state(id, user_decisions)
    status = "requires_user_approval"
    if blocked_reason:
        status = "blocked"
    elif decision_state in _SUPPRESSED_DECISIONS:
        status = decision_state
    elif decision_state == "approved_for_apply":
        status = "approved"
        confidence = "confirmed"
    elif decision_state == "accepted":
        status = "requires_user_approval"
    if evidence_type == EVIDENCE_TYPE_NAME_BASED_DETECTION and status != "approved":
        blocked_reason = blocked_reason or "name_based_step_requires_user_confirmation"
    safe_to_apply = (
        status == "approved"
        and action_type in _SAFE_ACTION_TYPES
        and tool in _SAFE_STEP_TOOLS
        and risk_level in _SAFE_RISK_LEVELS
        and not blocked_reason
    )
    if not safe_to_apply and status == "approved":
        status = "blocked"
        blocked_reason = blocked_reason or "step_failed_apply_safety_gate"
    step = {
        "id": id,
        "step_id": id,
        "action_type": action_type,
        "kind": _step_kind(action_type),
        "tool": tool,
        "target": target,
        "targets": [target],
        "observed_state": observed_state,
        "before_state": observed_state,
        "proposed_state": proposed_state,
        "proposed_after_state": proposed_state,
        "reason": reason,
        "title": reason,
        "evidence_type": evidence_type,
        "confidence": confidence,
        "risk_level": risk_level,
        "status": status,
        "blocked_reason": blocked_reason,
        "rollback_unit": rollback_unit,
        "rollback_scope": rollback_unit,
        "safe_to_apply": safe_to_apply,
        "required_user_decision": _required_user_decision(status, blocked_reason),
        "operations": _step_operations(action_type, proposed_state),
        "readback_expectation": (
            "Affected channel, mixer, or routing metadata is read back where supported."
        ),
    }
    if decision:
        step["user_decision"] = dict(decision)
    return step


def _step_kind(action_type: str) -> str:
    return {
        "rename": "rename",
        "color": "color",
        "route_channel": "route",
        "group_to_bus": "group",
        "create_bus_layout": "bus_layout",
    }.get(str(action_type), "manual")


def _required_user_decision(status: str, blocked_reason: str | None) -> dict:
    required = status in {"requires_user_approval", "blocked"} or bool(blocked_reason)
    values = ["approved_for_apply", "rejected", "ignored"]
    if blocked_reason and blocked_reason not in _REVIEW_ONLY_BLOCK_REASONS:
        values = ["manual_check", "rejected", "ignored"]
    return {
        "required": required,
        "allowed_values": values,
        "blocked_reason": blocked_reason,
    }


def _step_operations(action_type: str, proposed_state: dict) -> list[dict]:
    operations = []
    state = dict(proposed_state or {})
    for row in state.get("renames") or []:
        operations.append({"kind": "rename", "target": dict(row)})
    for row in state.get("colors") or []:
        operations.append({"kind": "color", "target": dict(row)})
    for row in state.get("routing") or []:
        operations.append({"kind": "route", "target": dict(row)})
    for row in state.get("buses") or []:
        operations.append({"kind": "bus_layout", "target": dict(row)})
    if not operations:
        operations.append({"kind": _step_kind(action_type), "target": state})
    return operations


def _step_finding_category(step: dict) -> str:
    action_type = str(step.get("action_type") or "")
    target_type = str((step.get("target") or {}).get("type") or "")
    if action_type == "rename" and target_type == "channel":
        return "unnamed_channel"
    if action_type == "rename" and target_type == "mixer":
        return "unnamed_mixer_track"
    if action_type == "color":
        return "inconsistent_color"
    if action_type == "route_channel":
        return "routing_issue"
    if action_type == "create_bus_layout":
        return "missing_bus"
    return "manual_check_required"


def _plan_findings(
    steps: list[dict],
    blocked_steps: list[dict],
    manual_checks: list[dict],
) -> list[dict]:
    findings: list[dict] = []
    for step in [*steps, *blocked_steps]:
        step_id = str(step.get("id") or step.get("step_id") or "")
        if not step_id:
            continue
        findings.append(
            {
                "finding_id": f"finding_{step_id}",
                "category": _step_finding_category(step),
                "severity": "low" if step.get("risk_level") == "low" else "medium",
                "title": str(step.get("reason") or step_id),
                "description": str(step.get("reason") or ""),
                "evidence": {
                    "evidence_type": step.get("evidence_type"),
                    "before_state": step.get("observed_state") or step.get("before_state") or {},
                },
                "affected_targets": list(step.get("targets") or [step.get("target") or {}]),
                "suggested_steps": [step_id],
                "confidence": str(step.get("confidence") or "unknown"),
            }
        )
    for row in manual_checks:
        check_id = str(row.get("id") or row.get("title") or "manual_check")
        findings.append(
            {
                "finding_id": f"finding_{check_id}",
                "category": "manual_check_required",
                "severity": "info",
                "title": str(row.get("title") or check_id),
                "description": str(row.get("reason") or ""),
                "evidence": dict(row),
                "affected_targets": [],
                "suggested_steps": [],
                "confidence": "manual_check",
            }
        )
    return findings


def _decisions_required(plan: dict) -> list[dict]:
    required = []
    for request in plan.get("interaction_requests") or []:
        if isinstance(request, dict):
            required.append(dict(request))
    for step in [*(plan.get("steps") or []), *(plan.get("blocked_steps") or [])]:
        decision = step.get("required_user_decision") or {}
        if isinstance(decision, dict) and decision.get("required"):
            required.append(
                {
                    "id": f"decision_{step.get('id')}",
                    "type": "step_decision",
                    "step_id": step.get("id"),
                    "prompt": step.get("reason"),
                    "allowed_values": list(decision.get("allowed_values") or []),
                    "blocked_reason": decision.get("blocked_reason"),
                }
            )
    return required


def _enrich_plan_contract_fields(plan: dict) -> dict:
    steps = [dict(row) for row in plan.get("steps") or []]
    blocked_steps = [dict(row) for row in plan.get("blocked_steps") or []]
    manual_checks = [dict(row) for row in plan.get("manual_checks") or []]
    plan["steps"] = steps
    plan["blocked_steps"] = blocked_steps
    plan["manual_checks"] = manual_checks
    plan["status"] = plan.get("plan_status", plan.get("status", "draft"))
    plan["source_report_id"] = (
        plan.get("source_report_id")
        or plan.get("snapshot_id")
        or (plan.get("source_observation_ids") or [None])[0]
    )
    plan["findings"] = _plan_findings(steps, blocked_steps, manual_checks)
    plan["decisions_required"] = _decisions_required(plan)
    plan["contract_version"] = "fls-pilot.organization-plan.v1"
    return plan


def _set_plan_hash(plan: dict) -> dict:
    _enrich_plan_contract_fields(plan)
    plan["plan_hash"] = _digest(_plan_hash_payload(plan))
    return plan


def _refresh_plan_decisions(plan: dict, decisions: list[dict]) -> dict:
    merged_decisions = _merge_user_decisions(list(plan.get("user_decisions") or []), decisions)
    refreshed_steps: list[dict] = []
    refreshed_blocked: list[dict] = []
    seen: set[str] = set()
    for original in [*(plan.get("steps") or []), *(plan.get("blocked_steps") or [])]:
        if not isinstance(original, dict):
            continue
        step_id = str(original.get("id") or original.get("step_id") or "")
        if not step_id or step_id in seen:
            continue
        seen.add(step_id)
        item = dict(original)
        decision_state, decision = _step_decision_state(step_id, merged_decisions)
        original_blocked_reason = item.get("blocked_reason")
        blocked_reason = original_blocked_reason
        status = str(item.get("status") or "requires_user_approval")
        confidence = str(item.get("confidence") or "unknown")
        if decision_state == "approved_for_apply":
            status = "approved"
            confidence = "confirmed"
            if blocked_reason in _REVIEW_ONLY_BLOCK_REASONS:
                blocked_reason = None
        elif decision_state in _SUPPRESSED_DECISIONS:
            status = decision_state
        elif decision_state == "accepted":
            status = "requires_user_approval"
        safe_to_apply = (
            status == "approved"
            and item.get("action_type") in _SAFE_ACTION_TYPES
            and item.get("tool") in _SAFE_STEP_TOOLS
            and item.get("risk_level") in _SAFE_RISK_LEVELS
            and not blocked_reason
        )
        if status == "approved" and not safe_to_apply:
            status = "blocked"
            blocked_reason = blocked_reason or "step_failed_apply_safety_gate"
        item.update(
            {
                "status": status,
                "confidence": confidence,
                "blocked_reason": blocked_reason,
                "safe_to_apply": safe_to_apply,
                "required_user_decision": _required_user_decision(status, blocked_reason),
            }
        )
        if decision:
            item["user_decision"] = dict(decision)
        elif "user_decision" in item:
            item.pop("user_decision", None)
        if item["status"] == "blocked":
            refreshed_blocked.append(item)
        else:
            refreshed_steps.append(item)
    plan["steps"] = refreshed_steps
    plan["blocked_steps"] = refreshed_blocked
    plan["user_decisions"] = merged_decisions
    approved_count = sum(1 for row in refreshed_steps if row.get("status") == "approved")
    actionable_count = sum(
        1 for row in refreshed_steps if row.get("status") == "requires_user_approval"
    )
    if refreshed_blocked and not refreshed_steps:
        plan_status = "blocked"
    elif approved_count and approved_count < len(
        [s for s in refreshed_steps if s.get("status") != "ignored"]
    ):
        plan_status = "partially_approved"
    elif approved_count and actionable_count == 0:
        plan_status = "approved"
    elif refreshed_steps or refreshed_blocked or plan.get("interaction_requests"):
        plan_status = "requires_user_approval"
    else:
        plan_status = "draft"
    plan["plan_status"] = plan_status
    plan["template_alignment_score"] = _template_alignment_score(refreshed_steps, refreshed_blocked)
    request = _step_approval_request(refreshed_steps)
    existing_requests = [
        dict(row)
        for row in plan.get("interaction_requests") or []
        if isinstance(row, dict) and row.get("id") != ORGANIZER_STEP_SELECTION_REQUEST_ID
    ]
    if request is not None:
        existing_requests.append(request)
    plan["interaction_requests"] = existing_requests
    return _set_plan_hash(plan)


def _template_interaction_requests(template_context: dict) -> list[dict]:
    options = []
    if template_context.get("ambiguous"):
        options = [
            {"id": str(slug), "label": str(name)}
            for slug, name in zip(
                template_context.get("candidate_slugs") or [],
                template_context.get("candidate_templates") or [],
                strict=False,
            )
        ]
    else:
        options = [
            {
                "id": str(profile.get("template_slug")),
                "label": str(profile.get("template_name") or profile.get("template_slug")),
            }
            for profile in templates.load_profiles()
            if profile.get("template_slug")
        ]
    return [
        InteractionRequest(
            id=ORGANIZER_TEMPLATE_SELECTION_REQUEST_ID,
            type="single_select",
            title="Choose target organization template",
            prompt=(
                "Choose the target template before applying organization changes. "
                "Ambiguous or missing template evidence keeps all steps blocked."
            ),
            options=tuple(options),
            allow_remove=False,
            metadata={"reason": "target_template_required"},
        ).to_dict()
    ]


def _step_approval_request(steps: list[dict]) -> dict | None:
    options = [
        {
            "id": step["id"],
            "label": step.get("reason") or step["id"],
            "risk_level": step.get("risk_level"),
            "tool": step.get("tool"),
        }
        for step in steps
        if step.get("status") == "requires_user_approval"
    ]
    if not options:
        return None
    return InteractionRequest(
        id=ORGANIZER_STEP_SELECTION_REQUEST_ID,
        type="multi_select",
        title="Approve organization plan steps",
        prompt="Approve only the exact reversible organization steps to apply.",
        options=tuple(options),
        allow_remove=True,
        metadata={"decision_values": ["approved_for_apply", "rejected", "ignored"]},
    ).to_dict()


def _template_alignment_score(steps: list[dict], blocked_steps: list[dict]) -> int:
    total = len(steps) + len(blocked_steps)
    if total == 0:
        return 100
    safe_or_clean = sum(1 for step in steps if step.get("safe_to_apply"))
    return max(0, min(100, round((total - len(blocked_steps) + safe_or_clean) / (total * 2) * 100)))


def _step_to_proposed_change(step: dict) -> dict:
    return wr.proposed_change(
        id=str(step["id"]),
        title=str(step.get("reason") or step["id"]),
        tool=str(step.get("tool") or "fl_apply_organization_plan"),
        observed_state=dict(step.get("observed_state") or {}),
        proposed_state=dict(step.get("proposed_state") or {}),
        safety_class="write-safe-required",
        risk_level=str(step.get("risk_level") or "medium"),
        readback_expectation=(
            "Affected channel, mixer, or routing metadata is read back where supported."
        ),
        rollback_expectation=(
            "One named rollback unit is created for the approved organization plan apply."
        ),
        status=str(step.get("status") or "proposed"),
        requires_explicit_approval=True,
    )


def _reject_organization_apply(
    *,
    status: str,
    diagnostic_id: str,
    message: str,
    evidence: dict | None = None,
) -> dict:
    return wr.workflow_report(
        workflow="project_organizer_apply",
        title="Apply Organization Plan",
        mode="rejected",
        status=status,
        summary={"applied_changes": 0},
        diagnostics=[
            wr.diagnostic(
                id=diagnostic_id,
                severity="error",
                message=message,
                evidence=evidence or {},
                source="project_organizer",
            )
        ],
        ok=False,
        safety={
            "read_only": True,
            "requires_explicit_approval": True,
            "approval_received": False,
        },
    )


def _organization_change_history(limit: int = 10) -> list[dict]:
    entries = safety.change_history(limit, include_payload=False).get("entries", [])
    return [
        dict(row)
        for row in entries
        if str(row.get("scope") or "") == "project_organizer"
        or str(row.get("tool") or "") in {"apply_organization_plan", "apply_project_cleanup"}
        or str(row.get("rollback_unit") or "").startswith("organization_plan_")
    ]


def _stored_plan_status(stored: dict) -> dict:
    plan = dict(stored.get("full_plan") or {})
    _enrich_plan_contract_fields(plan)
    steps = [dict(row) for row in plan.get("steps") or []]
    blocked_steps = [dict(row) for row in plan.get("blocked_steps") or []]
    step_status_counts: dict[str, int] = {}
    for step in [*steps, *blocked_steps]:
        status = str(step.get("status") or "unknown")
        step_status_counts[status] = step_status_counts.get(status, 0) + 1
    return {
        "plan_id": stored.get("plan_id"),
        "plan_hash": stored.get("plan_hash"),
        "project_fingerprint": stored.get("project_fingerprint"),
        "created_at": stored.get("created_at"),
        "expires_at": stored.get("expires_at"),
        "status": plan.get("status") or plan.get("plan_status"),
        "plan_status": plan.get("plan_status"),
        "target_template": plan.get("target_template"),
        "template_match_status": plan.get("template_match_status"),
        "steps": len(steps),
        "blocked_steps": len(blocked_steps),
        "manual_checks": len(plan.get("manual_checks") or []),
        "decisions_required": len(plan.get("decisions_required") or []),
        "step_status_counts": step_status_counts,
        "approved_step_ids": [
            step.get("id") for step in steps if step.get("status") == "approved"
        ],
        "safe_step_ids": [step.get("id") for step in steps if step.get("safe_to_apply")],
    }


def _mark_plan_steps_applied(
    plan: dict,
    approved_ids: list[str],
    result: dict,
) -> dict:
    approved = set(approved_ids)
    verified = bool(result.get("after") is not None)
    for step in plan.get("steps") or []:
        if str(step.get("id") or step.get("step_id")) not in approved:
            continue
        step["status"] = "verified" if verified else "applied"
        step["safe_to_apply"] = False
        step["applied_at"] = _utc_timestamp()
        step["change_id"] = result.get("change_id")
        step["rollback_unit_id"] = (result.get("rollback") or {}).get("rollback_unit")
        step["readback_verified"] = verified
        step["required_user_decision"] = _required_user_decision(step["status"], None)
    statuses = [
        str(step.get("status") or "")
        for step in [*(plan.get("steps") or []), *(plan.get("blocked_steps") or [])]
    ]
    if any(status in {"verified", "applied"} for status in statuses):
        remaining = any(
            status in {"requires_user_approval", "approved", "blocked"}
            for status in statuses
        )
        plan["plan_status"] = "partially_applied" if remaining else "completed"
    return _set_plan_hash(plan)


def _prepare_step_writes(step: dict, bridge) -> list[dict]:
    state = dict(step.get("proposed_state") or {})
    writes: list[dict] = []
    for row in state.get("renames") or []:
        if row["type"] == "channel":
            writes.append(_channel_rename_entry(int(row["index"]), str(row["name"])))
        elif row["type"] == "mixer":
            writes.append(_bus_rename_entry(int(row["index"]), str(row["name"])))
        else:
            raise ValueError("rename type must be 'channel' or 'mixer'")
    for row in state.get("colors") or []:
        if row["type"] == "channel":
            writes.append(_color_write_entry(int(row["index"]), str(row["hex"])))
        elif row["type"] == "mixer":
            writes.append(_mixer_color_entry(int(row["index"]), str(row["hex"])))
        else:
            raise ValueError("color type must be 'channel' or 'mixer'")
    reserved_tracks: set[int] = set()
    for row in state.get("routing") or []:
        channel = int(row["channel"])
        if row.get("mode") == "free" or "track" not in row:
            start_track = int(row.get("start_track", 1))
            candidate_start = start_track
            track = None
            while True:
                candidate = _find_free_mixer_track(bridge, start_track=candidate_start)
                if candidate is None:
                    break
                if candidate not in reserved_tracks:
                    track = candidate
                    break
                candidate_start = candidate + 1
            if track is None:
                raise ValueError("no free mixer track available")
        else:
            track = int(row["track"])
        reserved_tracks.add(track)
        writes.append(
            operations.prepare_operation(
                "channel",
                "set_mixer_target",
                {"channel": channel, "track": track},
            ).safe_write_group_entry()
        )
    for bus in state.get("buses") or []:
        bus_track = int(bus["bus_track"])
        source_tracks = [int(source) for source in bus.get("source_tracks", [])]
        for source in source_tracks:
            if source in (0, bus_track):
                continue
            writes.append(_route_write_entry(source, bus_track, True))
            writes.append(_route_write_entry(source, 0, False))
        writes.append(_route_write_entry(bus_track, 0, True))
        if bus.get("name"):
            writes.append(_bus_rename_entry(bus_track, str(bus["name"])))
    return writes


def _target_template_context(profile: dict | None, *, selected_by_user: bool) -> dict:
    if not profile:
        return {
            "template_name": None,
            "template_slug": None,
            "selected_by_user": selected_by_user,
        }
    return {
        "template_name": profile.get("template_name"),
        "template_slug": profile.get("template_slug"),
        "selected_by_user": selected_by_user,
        "profile_path": profile.get("_profile_path"),
    }


def build_template_alignment_plan(
    snapshot,
    target_profile: dict | None,
    user_decisions: list[dict] | None = None,
    *,
    target_selected_by_user: bool = False,
    scope: list[str] | None = None,
) -> dict:
    """Build a read-only, template-aware organizer plan from a static snapshot."""
    decisions = [dict(row) for row in user_decisions or [] if isinstance(row, dict)]
    scope_set = {str(item) for item in (scope or ["naming", "channel_routing", "bus_layout"])}
    template_context = dict(snapshot.template_context or {})
    created_at = _utc_timestamp()
    steps: list[dict] = []
    blocked_steps: list[dict] = []
    manual_checks = []
    interaction_requests = []
    current_template = templates.compact_context(template_context) or {
        "template_name": None,
        "template_slug": None,
        "matched": False,
        "ambiguous": bool(template_context.get("ambiguous")),
    }

    if target_profile is None:
        interaction_requests.extend(_template_interaction_requests(template_context))
        manual_checks.append(
            {
                "id": "target_template_required",
                "title": "Choose target template",
                "reason": "No unambiguous target template is available for apply-capable planning.",
            }
        )
        if "naming" in scope_set:
            for row in snapshot.channels:
                idx = _channel_index(row)
                if not _looks_default_channel_name(row.get("name")):
                    continue
                suggested = _suggest_channel_name(row)
                blocked_steps.append(
                    _organizer_step(
                        id=f"name_based_rename_channel_{idx}",
                        action_type="rename",
                        tool="fl_apply_project_cleanup_step",
                        target={"type": "channel", "index": idx},
                        observed_state={"name": row.get("name")},
                        proposed_state={
                            "renames": [
                                {
                                    "type": "channel",
                                    "index": idx,
                                    "from": row.get("name"),
                                    "name": suggested,
                                }
                            ]
                        },
                        reason="Default-looking channel name needs producer confirmation.",
                        evidence_type=EVIDENCE_TYPE_NAME_BASED_DETECTION,
                        confidence="low",
                        risk_level="low",
                        rollback_unit="organization_plan_name_heuristic",
                        user_decisions=decisions,
                        blocked_reason="name_based_step_requires_user_confirmation",
                    )
                )
    else:
        channel_routes = _profile_channel_routes(target_profile)
        mixer_targets = _profile_track_by_index(target_profile)
        channels_by_index = {_channel_index(row): dict(row) for row in snapshot.channels}
        mixer_by_index = {_mixer_track_index(row): dict(row) for row in snapshot.mixer_tracks}

        if "naming" in scope_set:
            for idx, expected in channel_routes.items():
                current = channels_by_index.get(idx)
                if current is None:
                    continue
                expected_name = str(expected.get("channel_name") or "").strip()
                current_name = str(current.get("name") or "").strip()
                if expected_name and current_name != expected_name:
                    steps.append(
                        _organizer_step(
                            id=f"template_rename_channel_{idx}",
                            action_type="rename",
                            tool="fl_apply_project_cleanup_step",
                            target={"type": "channel", "index": idx},
                            observed_state={"name": current_name},
                            proposed_state={
                                "renames": [
                                    {
                                        "type": "channel",
                                        "index": idx,
                                        "from": current_name,
                                        "name": expected_name,
                                    }
                                ]
                            },
                            reason=f"Align channel {idx} name with target template.",
                            evidence_type="template_profile",
                            confidence="high" if target_selected_by_user else "medium",
                            risk_level="low",
                            rollback_unit="organization_plan_naming",
                            user_decisions=decisions,
                        )
                    )
            for idx, expected in mixer_targets.items():
                role = str(expected.get("role") or "")
                if role == templates.PROFILE_RESERVED_ROLE:
                    continue
                current = mixer_by_index.get(idx)
                if current is None:
                    continue
                expected_name = str(expected.get("name") or "").strip()
                current_name = str(current.get("name") or "").strip()
                if expected_name and current_name != expected_name:
                    steps.append(
                        _organizer_step(
                            id=f"template_rename_mixer_{idx}",
                            action_type="rename",
                            tool="fl_apply_project_cleanup_step",
                            target={"type": "mixer", "index": idx, "role": role},
                            observed_state={"name": current_name},
                            proposed_state={
                                "renames": [
                                    {
                                        "type": "mixer",
                                        "index": idx,
                                        "from": current_name,
                                        "name": expected_name,
                                    }
                                ]
                            },
                            reason=f"Align mixer track {idx} name with target template.",
                            evidence_type="template_profile",
                            confidence="high" if target_selected_by_user else "medium",
                            risk_level="low",
                            rollback_unit="organization_plan_naming",
                            user_decisions=decisions,
                        )
                    )

        if "channel_routing" in scope_set:
            for idx, expected in channel_routes.items():
                current = channels_by_index.get(idx)
                if current is None:
                    continue
                target_track = expected.get("target_mixer_track")
                try:
                    target_track = int(target_track)
                except (TypeError, ValueError):
                    continue
                if templates.is_reserved_placeholder(template_context, target_track):
                    blocked_steps.append(
                        _organizer_step(
                            id=f"blocked_route_channel_{idx}_reserved_{target_track}",
                            action_type="route_channel",
                            tool="fl_apply_project_cleanup_step",
                            target={"type": "channel", "index": idx},
                            observed_state={
                                "target_mixer_track": current.get("target_mixer_track")
                            },
                            proposed_state={"routing": [{"channel": idx, "track": target_track}]},
                            reason=(
                                "Template target is a reserved placeholder and is not a "
                                "cleanup target."
                            ),
                            evidence_type="template_profile",
                            confidence="high",
                            risk_level="unsupported",
                            rollback_unit="organization_plan_routing",
                            user_decisions=decisions,
                            blocked_reason="reserved_placeholder_target",
                        )
                    )
                    continue
                if current.get("target_mixer_track") != target_track:
                    steps.append(
                        _organizer_step(
                            id=f"template_route_channel_{idx}_to_{target_track}",
                            action_type="route_channel",
                            tool="fl_apply_project_cleanup_step",
                            target={"type": "channel", "index": idx},
                            observed_state={
                                "target_mixer_track": current.get("target_mixer_track")
                            },
                            proposed_state={"routing": [{"channel": idx, "track": target_track}]},
                            reason=f"Align channel {idx} mixer target with target template.",
                            evidence_type="template_profile",
                            confidence="high" if target_selected_by_user else "medium",
                            risk_level="low",
                            rollback_unit="organization_plan_routing",
                            user_decisions=decisions,
                        )
                    )

        if "bus_layout" in scope_set:
            for idx, expected in mixer_targets.items():
                role = str(expected.get("role") or "")
                if role not in {"stem_bus", "premaster"}:
                    continue
                source_tracks = [
                    int(source)
                    for source in expected.get("receives_from") or []
                    if source not in (None, 0, idx)
                ]
                if not source_tracks:
                    continue
                step_id = f"template_bus_layout_{idx}"
                steps.append(
                    _organizer_step(
                        id=step_id,
                        action_type="create_bus_layout",
                        tool="fl_apply_bus_layout",
                        target={"type": "mixer", "index": idx, "role": role},
                        observed_state={"source_tracks": source_tracks},
                        proposed_state={
                            "buses": [
                                {
                                    "bus_track": idx,
                                    "name": expected.get("name"),
                                    "source_tracks": source_tracks,
                                }
                            ]
                        },
                        reason=f"Route template source tracks through {expected.get('name')}.",
                        evidence_type="template_profile",
                        confidence="high" if target_selected_by_user else "medium",
                        risk_level="medium",
                        rollback_unit=f"organization_plan_bus_layout_{idx}",
                        user_decisions=decisions,
                    )
                )

    for row in steps:
        if row.get("status") == "blocked":
            blocked_steps.append(row)
    steps = [row for row in steps if row.get("status") != "blocked"]
    request = _step_approval_request(steps)
    if request is not None:
        interaction_requests.append(request)

    approved_count = sum(1 for row in steps if row.get("status") == "approved")
    actionable_count = sum(1 for row in steps if row.get("status") == "requires_user_approval")
    plan_status = "draft"
    if blocked_steps and not steps:
        plan_status = "blocked"
    elif approved_count and approved_count < len(
        [s for s in steps if s.get("status") != "ignored"]
    ):
        plan_status = "partially_approved"
    elif approved_count and actionable_count == 0:
        plan_status = "approved"
    elif steps or blocked_steps or interaction_requests:
        plan_status = "requires_user_approval"

    target_template = _target_template_context(
        target_profile,
        selected_by_user=target_selected_by_user,
    )
    match_status = "target_selected" if target_profile else "target_required"
    if template_context.get("ambiguous") and not target_selected_by_user:
        match_status = "ambiguous_requires_user_selection"
    plan = {
        "plan_id": f"orgplan_{uuid.uuid4().hex[:12]}",
        "created_at": created_at,
        "expires_at": created_at + _PLAN_TTL_SECONDS,
        "project_fingerprint": snapshot.project_fingerprint,
        "snapshot_id": snapshot.snapshot_id,
        "source_observation_ids": list(snapshot.source_observation_ids),
        "current_template_context": current_template,
        "target_template": target_template,
        "template_match_status": match_status,
        "template_match_confidence": (
            "confirmed"
            if target_selected_by_user
            else str((template_context or {}).get("confidence_level") or "unknown")
        ),
        "template_selected_by_user": target_selected_by_user,
        "template_alignment_score": _template_alignment_score(steps, blocked_steps),
        "plan_status": plan_status,
        "steps": steps,
        "blocked_steps": blocked_steps,
        "manual_checks": manual_checks,
        "interaction_requests": interaction_requests,
        "user_decisions": decisions,
        "safety": {
            "read_only": True,
            "requires_explicit_approval": True,
            "plan_store_required_for_apply": True,
            "blocked_statuses": ["blocked", "rejected", "ignored"],
            "allowed_tools": sorted(_SAFE_STEP_TOOLS),
        },
    }
    return _set_plan_hash(plan)


def _cleanup_proposal(
    *,
    id: str,
    title: str,
    reason: str,
    risk: str,
    params: dict,
    target: dict,
    tool: str = "fl_apply_project_cleanup_step",
    manual_review: bool = False,
) -> dict:
    proposal_params = dict(params)
    if tool in _ORGANIZER_APPLY_TOOLS:
        proposal_params["approved"] = True
    return wr.proposed_change(
        id=id,
        title=title,
        tool=tool,
        observed_state=target,
        proposed_state=proposal_params,
        safety_class="write-safe-required" if tool in _ORGANIZER_APPLY_TOOLS else "read-only",
        risk_level=risk,
        readback_expectation="Affected channel or mixer metadata is read back where supported.",
        rollback_expectation="MCP changelog rollback restores the prior metadata.",
        requires_explicit_approval=True,
    )


def _proposal_for_rename(kind: str, index: int, before_name: str, after_name: str) -> dict:
    return _cleanup_proposal(
        id=f"rename_{kind}_{index}",
        title=f"Rename {kind} {index} to {after_name}",
        reason=f"{kind.title()} name is empty, default, or duplicated.",
        risk="low",
        params={"renames": [{"type": kind, "index": index, "name": after_name}]},
        target={"type": kind, "index": index, "before_name": before_name, "after_name": after_name},
    )


def _proposal_for_color(kind: str, index: int, color: str) -> dict:
    return _cleanup_proposal(
        id=f"color_{kind}_{index}",
        title=f"Color {kind} {index} {color}",
        reason="Color proposal supplied by the user or active cleanup standard.",
        risk="low",
        params={"colors": [{"type": kind, "index": index, "hex": color}]},
        target={"type": kind, "index": index, "hex": color},
    )


def _proposal_for_channel_routing(
    channel: int,
    track: int | None = None,
    *,
    start_track: int = 1,
) -> dict:
    route = {"channel": channel}
    target = {"type": "channel", "index": channel}
    if track is None:
        route.update({"mode": "free", "start_track": start_track})
        target["target_mixer_track"] = "next_free"
        title = f"Assign channel {channel} to a free mixer track"
    else:
        route["track"] = track
        target["target_mixer_track"] = track
        title = f"Assign channel {channel} to mixer track {track}"
    return _cleanup_proposal(
        id=f"route_channel_{channel}_mixer_target",
        title=title,
        reason="Channel is routed only to Master or has unknown routing.",
        risk="low",
        params={"routing": [route]},
        target=target,
    )


def _apply_report(
    *,
    title: str,
    tool_name: str,
    rollback_unit: str,
    writes: list[dict],
    requested_changes: list[dict],
    approved: bool,
    bridge,
    kb_rule_ids: list[str],
    approval_changes: list[dict] | None = None,
) -> dict:
    if not requested_changes:
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="no_op",
            status="No valid organizer changes requested",
            summary={"proposed_changes": 0, "applied_changes": 0},
            notes=["No FL Studio project state was changed."],
            ok=False,
        )
    if not approved:
        return wr.approval_required_report(
            workflow="project_organizer_apply",
            title=title,
            proposed_changes=approval_changes or requested_changes,
        )
    if not writes:
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="rejected",
            status="No valid writes could be prepared",
            summary={"proposed_changes": len(requested_changes), "applied_changes": 0},
            proposed_changes=requested_changes,
            ok=False,
        )
    res = safety.safe_write_group(
        bridge,
        tool=tool_name,
        scope="project_organizer",
        writes=writes,
        rollback_unit=rollback_unit,
    )
    if res.get("dry_run"):
        dry_run_changes = approval_changes or requested_changes
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title=title,
            mode="dry_run",
            status="Dry-run only",
            summary={"proposed_changes": len(dry_run_changes), "applied_changes": 0},
            proposed_changes=dry_run_changes,
            notes=["Dry-run mode is enabled; no FL Studio project state was changed."],
            kb_policy_refs=kb_policy.rule_refs(kb_rule_ids),
            safety={"read_only": True, "requires_explicit_approval": True},
        )
    before = res.get("before") or []
    after = res.get("after") or []
    risk = "medium" if len(requested_changes) > 1 else "low"
    applied = []
    for index, proposal in enumerate(requested_changes):
        applied.append(
            wr.applied_change(
                id=proposal["id"],
                title=proposal["title"],
                tool=tool_name,
                before=before[index] if index < len(before) else None,
                requested_change=proposal.get("proposed_state") or proposal.get("params") or {},
                after=after[index] if index < len(after) else None,
                safety_class="write-safe-required",
                risk_level=risk,
                change_id=res.get("change_id"),
                readback_ok=index < len(after),
                rollback=res.get("rollback"),
            )
        )
    return wr.workflow_report(
        workflow="project_organizer_apply",
        title=title,
        mode="applied",
        status="Applied",
        summary={"proposed_changes": 0, "applied_changes": len(applied)},
        applied_changes=applied,
        notes=["Rollback with fl_rollback_last_change if the result is not intended."],
        kb_policy_refs=kb_policy.rule_refs(kb_rule_ids),
        safety={
            "read_only": False,
            "requires_explicit_approval": False,
            "approval_received": True,
        },
    )


def register(mcp: FastMCP) -> None:
    _RO = {
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "read-only",
    }
    _WR = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
        "safetyClass": "write-safe-required",
    }
    _SS = {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
        "safetyClass": "server-state",
    }

    @mcp.tool(annotations={"title": "Analyze Project Organization", **_RO})
    def fl_analyze_project_organization() -> dict:
        """Analyze project to find unnamed channels, uncolored channels, and unassigned tracks.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        chans = {"channels": list(snapshot.channels)}
        template_context = snapshot.template_context

        diagnostics = []
        unnamed = []
        ungrouped = []

        for c in chans.get("channels", []):
            if _looks_default_channel_name(c.get("name")):
                unnamed.append(c)
                idx = _channel_index(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"default_channel_name_{idx}",
                        severity="low",
                        message=f"Channel {idx} has a default or empty name.",
                        evidence={"name": c.get("name")},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )

            # Simple heuristic for uncolored (assuming default FL color or no color)
            # We don't have color in routing summary currently, we'd need to fetch or assume.
            # But the agent can use this as a structural check.

            tgt = c.get("target_mixer_track")
            if (
                not isinstance(tgt, int)
                or tgt == 0
                and not templates.is_template_bus(template_context, tgt)
            ):
                ungrouped.append(c)
                idx = _channel_index(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"master_routed_channel_{idx}",
                        severity="medium",
                        message=f"Channel {idx} is routed only to Master or has unknown routing.",
                        evidence={"target_mixer_track": tgt},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                    )
                )

        payload = wr.workflow_report(
            workflow="project_organizer",
            title="Project Organization Analysis",
            mode="diagnostic",
            status="Organization analysis generated",
            summary={
                "unnamed_channels": len(unnamed),
                "ungrouped_channels": len(ungrouped),
                "diagnostics": len(diagnostics),
            },
            diagnostics=diagnostics,
            notes=[
                "Use fl_plan_project_cleanup to generate proposal-first cleanup actions.",
                "Preserve linked Channel, Playlist, and Mixer naming/coloring where it is already evident.",  # noqa: E501
                "Do not infer Channel, Playlist Track, and Mixer Track links from numeric index alone.",  # noqa: E501
                "Only apply cleanup through rollback-safe wrappers.",
            ],
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "channel_rack_workflow_requires_routing_inference",
                ]
            ),
            metadata={
                "unnamed_channels": unnamed,
                "ungrouped_channels": ungrouped,
                "template_context": templates.compact_context(template_context),
            },
            safety={"read_only": True, "requires_explicit_approval": False},
        )
        payload["project_fingerprint"] = snapshot.project_fingerprint
        payload["source_observations"] = list(snapshot.source_observation_ids)
        return payload

    @mcp.tool(annotations={"title": "Scan Project Organization", **_RO})
    def fl_scan_project_organization() -> dict:
        """Scan project organization and return read-only findings.

        Safety: Read-Only.
        """
        return fl_analyze_project_organization()

    @mcp.tool(annotations={"title": "Plan Project Cleanup", **_RO})
    def fl_plan_project_cleanup() -> dict:
        """Create a dry-run plan for project cleanup.

        Safety: Read-Only.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        chans = list(snapshot.channels)
        mixer_tracks = list(snapshot.mixer_tracks)
        template_context = snapshot.template_context

        diagnostics = []
        proposed_changes = []
        for c in chans:
            idx = _channel_index(c)
            if _looks_default_channel_name(c.get("name")):
                suggested = _suggest_channel_name(c)
                diagnostics.append(
                    wr.diagnostic(
                        id=f"default_channel_name_{idx}",
                        severity="low",
                        message=f"Channel {idx} has a default or empty name.",
                        evidence={"name": c.get("name"), "suggested_name": suggested},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                        metadata=_organizer_validation_metadata(
                            EVIDENCE_TYPE_NAME_BASED_DETECTION,
                            reason="default_channel_name",
                        ),
                    )
                )
                proposed_changes.append(
                    _proposal_for_rename("channel", idx, str(c.get("name") or ""), suggested)
                )
            target = c.get("target_mixer_track")
            if (
                not isinstance(target, int)
                or target == 0
                and not templates.is_template_bus(template_context, target)
            ):
                diagnostics.append(
                    wr.diagnostic(
                        id=f"master_routed_channel_{idx}",
                        severity="medium",
                        message=f"Channel {idx} is routed only to Master or has unknown routing.",
                        evidence={"target_mixer_track": target},
                        target={"type": "channel", "index": idx},
                        source="project_organizer",
                        metadata=_organizer_validation_metadata(
                            EVIDENCE_TYPE_ROUTING_BASED_DETECTION,
                            reason="master_or_unknown_routing",
                        ),
                    )
                )
                proposed_changes.append(_proposal_for_channel_routing(idx))

        duplicate_mixer_names = {}
        for row in mixer_tracks:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            duplicate_mixer_names.setdefault(name, []).append(row)
        for name, rows in duplicate_mixer_names.items():
            if len(rows) < 2:
                continue
            for row in rows[1:]:
                idx = int(row.get("i", row.get("index", 0)))
                suggested = f"{name} ({idx})"
                diagnostics.append(
                    wr.diagnostic(
                        id=f"duplicate_mixer_name_{idx}",
                        severity="low",
                        message=f"Mixer track {idx} duplicates the name {name}.",
                        evidence={"name": name, "suggested_name": suggested},
                        target={"type": "mixer", "index": idx},
                        source="project_organizer",
                        metadata=_organizer_validation_metadata(
                            EVIDENCE_TYPE_NAME_BASED_DETECTION,
                            reason="duplicate_mixer_name",
                        ),
                    )
                )
                proposed_changes.append(_proposal_for_rename("mixer", idx, name, suggested))

        interaction_request = _organizer_validation_request(diagnostics)
        payload = wr.workflow_report(
            workflow="project_organizer",
            title="Project Cleanup Proposal",
            mode="proposal",
            status="Project cleanup proposals generated",
            summary={
                "diagnostics": len(diagnostics),
                "proposed_changes": len(proposed_changes),
                "channels_scanned": len(chans),
                "mixer_tracks_scanned": len(mixer_tracks),
            },
            diagnostics=diagnostics,
            proposed_changes=proposed_changes,
            notes=[
                "This tool is read-only and applies no FL changes.",
                "Apply only one approved proposal or one named rollback unit at a time.",
                "Do not move playlist clips, delete clips/patterns, or load plugins.",
            ],
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "instrument_audio_track_workflow",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
            metadata={"template_context": templates.compact_context(template_context)},
            interaction_requests=(
                [interaction_request] if interaction_request is not None else []
            ),
            safety={"read_only": True, "requires_explicit_approval": bool(proposed_changes)},
        )
        payload["project_fingerprint"] = snapshot.project_fingerprint
        payload["source_observations"] = list(snapshot.source_observation_ids)
        return payload

    @mcp.tool(annotations={"title": "Plan Project Organization", **_RO})
    def fl_plan_project_organization(
        target_template: Annotated[
            str | None,
            Field(description="Optional target template slug, for example 'psytrance'."),
        ] = None,
        style: Annotated[
            str,
            Field(
                description="Template style hint. Use 'auto' unless the producer selects a style."
            ),
        ] = "auto",
        scope: Annotated[
            list[str] | None,
            Field(description="Optional scopes: naming, color, channel_routing, bus_layout."),
        ] = None,
        user_decisions: Annotated[
            list[dict] | None,
            Field(description="Optional user decisions from organizer interaction requests."),
        ] = None,
    ) -> dict:
        """Create a stored, template-aware project organization plan.

        Safety: Read-Only. The returned plan is stored server-side and can only be
        applied later through fl_apply_organization_plan with explicit approval.
        """
        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        decisions = [dict(row) for row in user_decisions or [] if isinstance(row, dict)]
        template_context = templates.resolve_with_user_decisions(
            snapshot.template_context,
            decisions,
            mixer_tracks=snapshot.mixer_tracks,
            routing_rows=snapshot.routing,
            channel_rows=snapshot.channels,
        )
        selected_slug = (
            str(target_template or "").strip()
            or _selected_target_template(decisions)
            or (str(style).strip() if str(style).strip().lower() != "auto" else "")
        )
        target_selected_by_user = bool(selected_slug)
        if (
            not selected_slug
            and template_context.get("matched")
            and not template_context.get("ambiguous")
        ):
            selected_slug = str(template_context.get("template_slug") or "").strip()
        target_profile = templates.profile_by_slug(selected_slug) if selected_slug else None
        if selected_slug and target_profile is None:
            plan = build_template_alignment_plan(
                snapshot,
                None,
                decisions,
                target_selected_by_user=target_selected_by_user,
                scope=scope,
            )
            plan["manual_checks"].append(
                {
                    "id": "unknown_target_template",
                    "title": "Unknown target template",
                    "reason": f"Template profile {selected_slug!r} is not installed.",
                }
            )
            plan["template_match_status"] = "unknown_target_template"
            _set_plan_hash(plan)
        else:
            plan_snapshot = snapshot
            if template_context != snapshot.template_context:
                plan_snapshot = type(snapshot)(
                    created_at=snapshot.created_at,
                    project_fingerprint=snapshot.project_fingerprint,
                    snapshot_id=snapshot.snapshot_id,
                    project_state=snapshot.project_state,
                    channels=snapshot.channels,
                    mixer_tracks=snapshot.mixer_tracks,
                    routing=snapshot.routing,
                    patterns=snapshot.patterns,
                    playlist_tracks=snapshot.playlist_tracks,
                    template_context=template_context,
                    counts=snapshot.counts,
                    coverage=snapshot.coverage,
                    source_observation_ids=snapshot.source_observation_ids,
                    errors=snapshot.errors,
                    metadata=snapshot.metadata,
                    observation_id=snapshot.observation_id,
                )
            plan = build_template_alignment_plan(
                plan_snapshot,
                target_profile,
                decisions,
                target_selected_by_user=target_selected_by_user,
                scope=scope,
            )
        _store_plan(plan)
        proposed_changes = [_step_to_proposed_change(step) for step in plan.get("steps") or []]
        payload = wr.workflow_report(
            workflow="project_organizer",
            title="Project Organization Plan",
            mode="proposal",
            status="Template-aware organization plan generated",
            summary={
                "steps": len(plan.get("steps") or []),
                "blocked_steps": len(plan.get("blocked_steps") or []),
                "manual_checks": len(plan.get("manual_checks") or []),
                "template_alignment_score": plan.get("template_alignment_score"),
                "plan_status": plan.get("plan_status"),
            },
            proposed_changes=proposed_changes,
            manual_checks=list(plan.get("manual_checks") or []),
            notes=[
                "This tool is read-only and stores a short-lived plan for later approval.",
                (
                    "Name-based or ambiguous template assumptions are not apply-capable "
                    "until confirmed."
                ),
                "Rejected, ignored, blocked, expired, or stale-fingerprint steps will not apply.",
            ],
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
            metadata={
                "organizer_plan": plan,
                "plan_store": {
                    "plan_id": plan["plan_id"],
                    "expires_at": plan["expires_at"],
                    "stored": True,
                },
            },
            interaction_requests=list(plan.get("interaction_requests") or []),
            user_decisions=decisions,
            safety=plan["safety"],
        )
        payload.update(
            {
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "project_fingerprint": plan["project_fingerprint"],
                "snapshot_id": plan["snapshot_id"],
                "source_report_id": plan["source_report_id"],
                "source_observation_ids": plan["source_observation_ids"],
                "current_template_context": plan["current_template_context"],
                "target_template": plan["target_template"],
                "template_match_status": plan["template_match_status"],
                "template_alignment_score": plan["template_alignment_score"],
                "organization_plan_status": plan["status"],
                "organization_plan_contract_version": plan["contract_version"],
                "plan_status": plan["plan_status"],
                "findings": plan["findings"],
                "decisions_required": plan["decisions_required"],
                "steps": plan["steps"],
                "blocked_steps": plan["blocked_steps"],
                "manual_checks": plan["manual_checks"],
                "interaction_requests": plan["interaction_requests"],
                "user_decisions": plan["user_decisions"],
                "safety": plan["safety"],
            }
        )
        return payload

    @mcp.tool(annotations={"title": "Update Organization Plan Decision", **_SS})
    def fl_update_organization_plan_decision(
        plan_id: Annotated[
            str,
            Field(description="Stored organizer plan id returned by fl_plan_project_organization."),
        ],
        user_decisions: Annotated[
            list[dict] | None,
            Field(description="Decision rows to merge into the stored plan."),
        ] = None,
        approve_step_ids: Annotated[
            list[str] | None,
            Field(description="Exact step ids to mark approved_for_apply."),
        ] = None,
        reject_step_ids: Annotated[
            list[str] | None,
            Field(description="Exact step ids to reject."),
        ] = None,
        ignore_step_ids: Annotated[
            list[str] | None,
            Field(description="Exact step ids to ignore for this plan."),
        ] = None,
        selected_template: Annotated[
            str | None,
            Field(description="Optional selected target template slug; rebuilds the stored plan."),
        ] = None,
    ) -> dict:
        """Merge producer decisions into a stored organization plan.

        Safety: Server-State. This updates only the MCP server-local plan store.
        If selected_template is supplied, the plan is rebuilt from a read-only
        static snapshot and remains blocked if the project fingerprint is stale.
        """
        stored = _PLAN_STORE.get(str(plan_id))
        if stored is None:
            return _reject_organization_apply(
                status="Stored organization plan not found",
                diagnostic_id="organization_plan_not_found",
                message="Run fl_plan_project_organization before updating plan decisions.",
                evidence={"plan_id": plan_id},
            )
        incoming = [dict(row) for row in user_decisions or [] if isinstance(row, dict)]
        for step_id in approve_step_ids or []:
            incoming.append(
                {
                    "interaction_request_id": ORGANIZER_STEP_SELECTION_REQUEST_ID,
                    "step_id": str(step_id),
                    "decision": "approved_for_apply",
                }
            )
        for step_id in reject_step_ids or []:
            incoming.append(
                {
                    "interaction_request_id": ORGANIZER_STEP_SELECTION_REQUEST_ID,
                    "step_id": str(step_id),
                    "decision": "rejected",
                }
            )
        for step_id in ignore_step_ids or []:
            incoming.append(
                {
                    "interaction_request_id": ORGANIZER_STEP_SELECTION_REQUEST_ID,
                    "step_id": str(step_id),
                    "decision": "ignored",
                }
            )
        selected_slug = str(selected_template or "").strip()
        if selected_slug:
            incoming.append(
                {
                    "interaction_request_id": ORGANIZER_TEMPLATE_SELECTION_REQUEST_ID,
                    "selected_template": selected_slug,
                    "decision": "selected",
                }
            )
            bridge = get_bridge()
            snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
            if snapshot.project_fingerprint != stored.get("project_fingerprint"):
                return _reject_organization_apply(
                    status="Organization plan project fingerprint is stale",
                    diagnostic_id="organization_plan_stale_project_fingerprint",
                    message="Re-run fl_plan_project_organization before updating this plan.",
                    evidence={
                        "plan_project_fingerprint": stored.get("project_fingerprint"),
                        "current_project_fingerprint": snapshot.project_fingerprint,
                    },
                )
            target_profile = templates.profile_by_slug(selected_slug)
            if target_profile is None:
                plan = dict(stored.get("full_plan") or {})
                plan["manual_checks"] = [
                    *list(plan.get("manual_checks") or []),
                    {
                        "id": "unknown_target_template",
                        "title": "Unknown target template",
                        "reason": f"Template profile {selected_slug!r} is not installed.",
                    },
                ]
                plan["template_match_status"] = "unknown_target_template"
                plan = _refresh_plan_decisions(plan, incoming)
            else:
                decisions = _merge_user_decisions(
                    list((stored.get("full_plan") or {}).get("user_decisions") or []),
                    incoming,
                )
                plan = build_template_alignment_plan(
                    snapshot,
                    target_profile,
                    decisions,
                    target_selected_by_user=True,
                )
                plan["plan_id"] = str(plan_id)
                _set_plan_hash(plan)
        else:
            plan = _refresh_plan_decisions(dict(stored.get("full_plan") or {}), incoming)
        _store_plan(plan)
        return {
            "ok": True,
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "project_fingerprint": plan["project_fingerprint"],
            "status": plan["status"],
            "plan_status": plan["plan_status"],
            "steps": plan["steps"],
            "blocked_steps": plan["blocked_steps"],
            "manual_checks": plan["manual_checks"],
            "decisions_required": plan["decisions_required"],
            "user_decisions": plan["user_decisions"],
            "safety": {
                "read_only": False,
                "safety_class": "server-state",
                "project_changes": False,
                "requires_explicit_approval": False,
            },
        }

    @mcp.tool(annotations={"title": "Get Organization Status", **_RO})
    def fl_get_organization_status(
        plan_id: Annotated[
            str | None,
            Field(description="Optional stored organizer plan id."),
        ] = None,
        include_history: Annotated[
            bool,
            Field(description="Include recent organizer change history and rollback ids."),
        ] = True,
    ) -> dict:
        """Return stored plan status and organizer rollback availability.

        Safety: Read-Only.
        """
        if plan_id:
            stored = _PLAN_STORE.get(str(plan_id))
            if stored is None:
                return {
                    "ok": False,
                    "status": "Stored organization plan not found",
                    "plan_id": plan_id,
                    "plans": [],
                }
            plans = [_stored_plan_status(stored)]
        else:
            plans = [_stored_plan_status(row) for row in _PLAN_STORE.values()]
        history = _organization_change_history() if include_history else []
        return {
            "ok": True,
            "plans": plans,
            "active_plan_count": len(plans),
            "change_history": history,
            "available_rollbacks": [
                {
                    "change_id": row.get("change_id"),
                    "rollback_unit_id": row.get("rollback_unit"),
                    "tool": row.get("tool"),
                    "undo": row.get("undo"),
                }
                for row in history
            ],
            "safety": {
                "read_only": True,
                "rollback_path": "fl_rollback_organization_change or fl_rollback_change",
            },
        }

    @mcp.tool(
        annotations={
            "title": "Rollback Organization Change",
            **_SS,
            "destructiveHint": True,
        }
    )
    def fl_rollback_organization_change(
        change_id: Annotated[
            str | None,
            Field(description="Organizer change id to roll back; must be latest for safe LIFO."),
        ] = None,
        rollback_unit_id: Annotated[
            str | None,
            Field(description="Rollback unit id from organization status/change history."),
        ] = None,
    ) -> dict:
        """Rollback an organizer change through the existing MCP changelog.

        Safety: Server-State. This delegates to the standard LIFO rollback path
        and refuses non-latest change ids through safety.rollback_change.
        """
        bridge = get_bridge()
        if change_id:
            return safety.rollback_change(bridge, str(change_id))
        if rollback_unit_id:
            history = _organization_change_history(limit=50)
            matches = [
                row for row in reversed(history) if row.get("rollback_unit") == rollback_unit_id
            ]
            if not matches:
                return {
                    "ok": False,
                    "error": "rollback_unit_id not found in recent organizer change history",
                    "rollback_unit_id": rollback_unit_id,
                }
            return safety.rollback_change(bridge, str(matches[0].get("change_id")))
        history = _organization_change_history(limit=50)
        if not history:
            return {
                "ok": False,
                "error": "no recent organizer change found to roll back",
            }
        return safety.rollback_change(bridge, str(history[-1].get("change_id")))

    @mcp.tool(annotations={"title": "Apply Project Cleanup Step", **_WR})
    def fl_apply_project_cleanup_step(
        renames: Annotated[
            list[dict],
            Field(description="List of {type: 'channel'|'mixer', index: int, name: str}"),
        ] = None,
        colors: Annotated[
            list[dict], Field(description="List of {type: 'channel'|'mixer', index: int, hex: str}")
        ] = None,
        routing: Annotated[
            list[dict],
            Field(
                description=(
                    "List of {channel: int, track: int} or "
                    "{channel: int, mode: 'free', start_track?: int}"
                )
            ),
        ] = None,
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this exact cleanup step."),
        ] = False,
    ) -> dict:
        """Apply a batch of names, colors, and channel routing in one rollback unit.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []

        if renames:
            try:
                for r in renames:
                    if r["type"] == "channel":
                        writes.append(_channel_rename_entry(r["index"], r["name"]))
                        requested_changes.append(
                            _proposal_for_rename(
                                "channel", r["index"], str(r.get("from", "")), r["name"]
                            )
                        )
                    elif r["type"] == "mixer":
                        writes.append(_bus_rename_entry(r["index"], r["name"]))
                        requested_changes.append(
                            _proposal_for_rename(
                                "mixer", r["index"], str(r.get("from", "")), r["name"]
                            )
                        )
                    else:
                        raise ValueError("rename type must be 'channel' or 'mixer'")
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid rename request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_rename",
                            severity="error",
                            message=str(e),
                            evidence={"renames": renames},
                        )
                    ],
                    ok=False,
                )

        if colors:
            try:
                for c in colors:
                    if c["type"] == "channel":
                        writes.append(_color_write_entry(c["index"], c["hex"]))
                        requested_changes.append(
                            _proposal_for_color("channel", c["index"], c["hex"])
                        )
                    elif c["type"] == "mixer":
                        writes.append(_mixer_color_entry(c["index"], c["hex"]))
                        requested_changes.append(_proposal_for_color("mixer", c["index"], c["hex"]))
                    else:
                        raise ValueError("color type must be 'channel' or 'mixer'")
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid color request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_color",
                            severity="error",
                            message=str(e),
                            evidence={"colors": colors},
                        )
                    ],
                    ok=False,
                )

        if routing:
            reserved_tracks: set[int] = set()
            try:
                for r in routing:
                    channel = int(r["channel"])
                    if r.get("mode") == "free" or "track" not in r:
                        start_track = int(r.get("start_track", 1))
                        candidate_start = start_track
                        track = None
                        while True:
                            candidate = _find_free_mixer_track(bridge, start_track=candidate_start)
                            if candidate is None:
                                break
                            if candidate not in reserved_tracks:
                                track = candidate
                                break
                            candidate_start = candidate + 1
                        if track is None:
                            raise ValueError("no free mixer track available")
                    else:
                        track = int(r["track"])
                    reserved_tracks.add(track)
                    prepared = operations.prepare_operation(
                        "channel",
                        "set_mixer_target",
                        {"channel": channel, "track": track},
                    )
                    writes.append(prepared.safe_write_group_entry())
                    requested_changes.append(_proposal_for_channel_routing(channel, track))
            except (KeyError, ValueError, operations.OperationValidationError) as e:
                return wr.workflow_report(
                    workflow="project_organizer_apply",
                    title="Apply Project Cleanup Step",
                    mode="rejected",
                    status="Invalid routing request",
                    summary={"applied_changes": 0},
                    diagnostics=[
                        wr.diagnostic(
                            id="invalid_cleanup_routing",
                            severity="error",
                            message=str(e),
                            evidence={"routing": routing},
                        )
                    ],
                    ok=False,
                )

        return _apply_report(
            title="Apply Project Cleanup Step",
            tool_name="apply_project_cleanup",
            rollback_unit="project_cleanup_step",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
        )

    @mcp.tool(annotations={"title": "Apply Organization Plan", **_WR})
    def fl_apply_organization_plan(
        plan_id: Annotated[
            str,
            Field(description="Stored organizer plan id returned by fl_plan_project_organization."),
        ],
        approved_step_ids: Annotated[
            list[str],
            Field(description="Exact organizer step ids approved by the producer."),
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of these exact plan steps."),
        ] = False,
    ) -> dict:
        """Apply approved steps from a stored organization plan.

        Safety: Write-Safe-Required with Rollback. The tool refuses ad hoc
        parameters, expired plans, stale project fingerprints, blocked steps,
        rejected steps, ignored steps, unknown step ids, and unapproved calls.
        """
        stored = _PLAN_STORE.get(str(plan_id))
        if stored is None:
            return _reject_organization_apply(
                status="Stored organization plan not found",
                diagnostic_id="organization_plan_not_found",
                message="Run fl_plan_project_organization before applying an organization plan.",
                evidence={"plan_id": plan_id},
            )
        plan = dict(stored.get("full_plan") or {})
        expected_hash = _digest(_plan_hash_payload(plan))
        if expected_hash != stored.get("plan_hash") or expected_hash != plan.get("plan_hash"):
            return _reject_organization_apply(
                status="Stored organization plan hash mismatch",
                diagnostic_id="organization_plan_hash_mismatch",
                message="The stored organization plan hash no longer matches its contents.",
                evidence={"plan_id": plan_id},
            )
        if _utc_timestamp() > float(stored.get("expires_at") or 0):
            return _reject_organization_apply(
                status="Stored organization plan expired",
                diagnostic_id="organization_plan_expired",
                message="Re-run fl_plan_project_organization before applying an expired plan.",
                evidence={"plan_id": plan_id, "expires_at": stored.get("expires_at")},
            )
        approved_ids = [str(step_id) for step_id in approved_step_ids or []]
        if not approved_ids:
            return _reject_organization_apply(
                status="No organization plan steps selected",
                diagnostic_id="organization_plan_no_steps_selected",
                message="Pass the exact approved_step_ids to apply.",
                evidence={"plan_id": plan_id},
            )
        steps_by_id = {str(step.get("id")): dict(step) for step in plan.get("steps") or []}
        unknown = [step_id for step_id in approved_ids if step_id not in steps_by_id]
        if unknown:
            return _reject_organization_apply(
                status="Unknown organization plan step id",
                diagnostic_id="organization_plan_unknown_step",
                message="Every approved_step_id must exist in the stored plan.",
                evidence={"plan_id": plan_id, "unknown_step_ids": unknown},
            )
        selected_steps = [steps_by_id[step_id] for step_id in approved_ids]
        blocked = [
            step
            for step in selected_steps
            if step.get("status") in {"blocked", "rejected", "ignored"}
            or not step.get("safe_to_apply")
            or step.get("tool") not in _SAFE_STEP_TOOLS
            or step.get("risk_level") not in _SAFE_RISK_LEVELS
        ]
        if blocked:
            return _reject_organization_apply(
                status="Organization plan contains non-applyable selected steps",
                diagnostic_id="organization_plan_step_blocked",
                message=(
                    "Blocked, rejected, ignored, unsafe, or unapproved steps cannot be "
                    "applied."
                ),
                evidence={"blocked_step_ids": [step.get("id") for step in blocked]},
            )
        if not all(step.get("status") == "approved" for step in selected_steps):
            return _reject_organization_apply(
                status="Organization plan steps require explicit step approval",
                diagnostic_id="organization_plan_step_not_approved",
                message=(
                    "Each selected step must have a user_decision of "
                    "approved_for_apply in the stored plan."
                ),
                evidence={
                    "step_statuses": {
                        step.get("id"): step.get("status") for step in selected_steps
                    }
                },
            )
        proposed_changes = [_step_to_proposed_change(step) for step in selected_steps]
        if not approved:
            return wr.approval_required_report(
                workflow="project_organizer_apply",
                title="Apply Organization Plan",
                proposed_changes=proposed_changes,
                notes=[
                    "This applies only steps already marked approved_for_apply in the stored plan.",
                    "No FL Studio project state was changed.",
                ],
            )

        bridge = get_bridge()
        snapshot = get_analysis_broker().get_static_project_snapshot(bridge)
        if snapshot.project_fingerprint != stored.get("project_fingerprint"):
            return _reject_organization_apply(
                status="Organization plan project fingerprint is stale",
                diagnostic_id="organization_plan_stale_project_fingerprint",
                message="The current FL Studio project state no longer matches the stored plan.",
                evidence={
                    "plan_project_fingerprint": stored.get("project_fingerprint"),
                    "current_project_fingerprint": snapshot.project_fingerprint,
                },
            )

        writes = []
        try:
            for step in selected_steps:
                writes.extend(_prepare_step_writes(step, bridge))
        except (KeyError, TypeError, ValueError, operations.OperationValidationError) as exc:
            return _reject_organization_apply(
                status="Organization plan write preparation failed",
                diagnostic_id="organization_plan_write_prepare_failed",
                message=str(exc),
                evidence={"plan_id": plan_id, "approved_step_ids": approved_ids},
            )
        if not writes:
            return _reject_organization_apply(
                status="Organization plan selected no valid writes",
                diagnostic_id="organization_plan_no_writes",
                message="Selected steps did not produce any safe write entries.",
                evidence={"plan_id": plan_id, "approved_step_ids": approved_ids},
            )
        res = safety.safe_write_group(
            bridge,
            tool="apply_organization_plan",
            scope="project_organizer",
            writes=writes,
            rollback_unit=f"organization_plan_{plan_id}",
        )
        if res.get("dry_run"):
            return wr.workflow_report(
                workflow="project_organizer_apply",
                title="Apply Organization Plan",
                mode="dry_run",
                status="Dry-run only",
                summary={
                    "approved_steps": len(selected_steps),
                    "write_entries": len(writes),
                    "applied_changes": 0,
                },
                proposed_changes=proposed_changes,
                notes=["Dry-run mode is enabled; no FL Studio project state was changed."],
                safety={"read_only": True, "requires_explicit_approval": True},
            )
        plan = _mark_plan_steps_applied(plan, approved_ids, res)
        _store_plan(plan)
        applied = [
            wr.applied_change(
                id=str(step["id"]),
                title=str(step.get("reason") or step["id"]),
                tool="fl_apply_organization_plan",
                before=res.get("before"),
                requested_change=step.get("proposed_state") or {},
                after=res.get("after"),
                safety_class="write-safe-required",
                risk_level=str(step.get("risk_level") or "medium"),
                change_id=res.get("change_id"),
                readback_ok=bool(res.get("after") is not None),
                rollback=res.get("rollback"),
                rollback_command=res.get("undo"),
            )
            for step in selected_steps
        ]
        return wr.workflow_report(
            workflow="project_organizer_apply",
            title="Apply Organization Plan",
            mode="applied",
            status="Organization plan steps applied",
            summary={
                "approved_steps": len(selected_steps),
                "write_entries": len(writes),
                "applied_changes": len(applied),
            },
            applied_changes=applied,
            notes=["Rollback with fl_rollback_last_change if the result is not intended."],
            metadata={
                "plan_id": plan_id,
                "plan_hash": plan.get("plan_hash"),
                "project_fingerprint": snapshot.project_fingerprint,
                "applied_step_ids": approved_ids,
            },
            kb_policy_refs=kb_policy.rule_refs(
                [
                    "preserve_existing_structure_first",
                    "channel_rack_workflow_requires_routing_inference",
                    "routing_ui_guidance_vs_mcp_write",
                ]
            ),
            safety={
                "read_only": False,
                "requires_explicit_approval": False,
                "approval_received": True,
            },
        )

    @mcp.tool(annotations={"title": "Apply Naming Standard", **_WR})
    def fl_apply_naming_standard(
        style: Annotated[
            str, Field(description="Naming schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict],
            Field(description="Specific rewrite rules applied by LLM: {type, index, name}"),
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this naming batch."),
        ] = False,
    ) -> dict:
        """Batch apply standardized names across the project.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_channel_rename_entry(r["index"], r["name"]))
                    requested_changes.append(
                        _proposal_for_rename(
                            "channel", r["index"], str(r.get("from", "")), r["name"]
                        )
                    )
                elif r["type"] == "mixer":
                    writes.append(_bus_rename_entry(r["index"], r["name"]))
                    requested_changes.append(
                        _proposal_for_rename("mixer", r["index"], str(r.get("from", "")), r["name"])
                    )
                else:
                    raise ValueError("rule type must be 'channel' or 'mixer'")
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return wr.workflow_report(
                workflow="project_organizer_apply",
                title="Apply Naming Standard",
                mode="rejected",
                status="Invalid naming rule",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="invalid_naming_rule",
                        severity="error",
                        message=str(e),
                        evidence={"rules": rules},
                    )
                ],
                ok=False,
            )

        return _apply_report(
            title="Apply Naming Standard",
            tool_name="apply_naming_standard",
            rollback_unit=f"naming_standard_{style}",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
            approval_changes=[
                _cleanup_proposal(
                    id=f"naming_standard_{style}",
                    title=f"Apply {style} naming standard",
                    reason="Batch naming standard requires explicit approval.",
                    risk="medium" if len(requested_changes) > 1 else "low",
                    tool="fl_apply_naming_standard",
                    params={"style": style, "rules": rules},
                    target={"rules": len(rules)},
                )
            ],
        )

    @mcp.tool(annotations={"title": "Apply Color Standard", **_WR})
    def fl_apply_color_standard(
        style: Annotated[
            str, Field(description="Color schema (e.g. 'psytrance', 'default', 'dynamic')")
        ],
        rules: Annotated[
            list[dict], Field(description="Specific color rules applied by LLM: {type, index, hex}")
        ],
        approved: Annotated[
            bool,
            Field(description="Must be true after explicit approval of this color batch."),
        ] = False,
    ) -> dict:
        """Batch apply standardized colors across the project. Hex should be e.g. '#FF0000'.

        Safety: Write-Safe-Required with Rollback.
        """
        bridge = get_bridge()
        writes = []
        requested_changes = []
        try:
            for r in rules:
                if r["type"] == "channel":
                    writes.append(_color_write_entry(r["index"], r["hex"]))
                    requested_changes.append(_proposal_for_color("channel", r["index"], r["hex"]))
                elif r["type"] == "mixer":
                    writes.append(_mixer_color_entry(r["index"], r["hex"]))
                    requested_changes.append(_proposal_for_color("mixer", r["index"], r["hex"]))
                else:
                    raise ValueError("rule type must be 'channel' or 'mixer'")
        except (KeyError, ValueError, operations.OperationValidationError) as e:
            return wr.workflow_report(
                workflow="project_organizer_apply",
                title="Apply Color Standard",
                mode="rejected",
                status="Invalid color rule",
                summary={"applied_changes": 0},
                diagnostics=[
                    wr.diagnostic(
                        id="invalid_color_rule",
                        severity="error",
                        message=str(e),
                        evidence={"rules": rules},
                    )
                ],
                ok=False,
            )

        return _apply_report(
            title="Apply Color Standard",
            tool_name="apply_color_standard",
            rollback_unit=f"color_standard_{style}",
            writes=writes,
            requested_changes=requested_changes,
            approved=approved,
            bridge=bridge,
            kb_rule_ids=["preserve_existing_structure_first", "instrument_audio_track_workflow"],
            approval_changes=[
                _cleanup_proposal(
                    id=f"color_standard_{style}",
                    title=f"Apply {style} color standard",
                    reason="Batch color standard requires explicit approval.",
                    risk="medium" if len(requested_changes) > 1 else "low",
                    tool="fl_apply_color_standard",
                    params={"style": style, "rules": rules},
                    target={"rules": len(rules)},
                )
            ],
        )
