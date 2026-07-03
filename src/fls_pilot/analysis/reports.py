"""Canonical AnalysisReport serialization helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .runtime import get_report_store
from .schema import AnalysisReport

_CANONICAL_KEYS = frozenset(AnalysisReport(
    workflow="_schema",
    title="_schema",
    analysis_mode="static_snapshot",
).to_dict())


def serialize_analysis_report(report: AnalysisReport) -> dict[str, Any]:
    """Store and serialize one canonical report."""
    get_report_store().add_report(report)
    return report.to_dict()


def analysis_report_for_control_center(
    report: AnalysisReport,
    ui_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one canonical report with optional UI detail fields."""
    payload = serialize_analysis_report(report)
    ui = deepcopy(ui_payload or {})
    details = ui.get("details")
    if isinstance(details, dict):
        details.pop("analysis_report", None)
    for key, value in ui.items():
        if key not in _CANONICAL_KEYS and key != "analysis":
            payload[key] = value
    payload["safety"] = {
        **dict(ui.get("safety") or {}),
        **dict(payload.get("safety") or {}),
    }
    payload["ui_state"] = _ui_state_for_report(payload)
    return payload


def _ui_state_for_report(payload: dict[str, Any]) -> dict[str, Any]:
    freshness = dict(payload.get("freshness") or {})
    coverage = dict(payload.get("coverage") or {})
    metadata = dict(payload.get("metadata") or {})
    freshness_status = str(freshness.get("status") or "unknown")
    status = "succeeded"
    if freshness_status == "stale":
        status = "stale"
    elif freshness_status in {"unavailable", "missing"}:
        status = "failed"
    health_score = _score_or_none(payload.get("health_score"))
    risk_score = _score_or_none(payload.get("risk_score"))
    confidence_score = _score_or_none(payload.get("confidence_score"))
    human_validation_required = bool(metadata.get("human_validation_required")) or any(
        bool(dict(row.get("metadata") or {}).get("human_validation_required"))
        for row in payload.get("findings") or ()
        if isinstance(row, dict)
    )
    return {
        "status": status,
        "phase": "complete" if status in {"succeeded", "stale"} else "unavailable",
        "started_at": payload.get("created_at"),
        "completed_at": payload.get("created_at"),
        "elapsed_ms": None,
        "freshness": freshness,
        "score_summary": {
            "status": _score_status(payload, metadata),
            "health_score": health_score,
            "risk_score": risk_score if status != "failed" else None,
            "coverage": coverage,
            "confidence_score": confidence_score,
            "evidence_mode": payload.get("evidence_mode"),
            "score_status": metadata.get("score_status") or "final",
            "human_validation_required": human_validation_required,
        },
        "interaction_requests": list(payload.get("interaction_requests") or ()),
    }


def _score_or_none(value: Any) -> int | None:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return None


def _score_status(payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    if metadata.get("score_status") in {"provisional", "partial"}:
        return "needs_review"
    if payload.get("health_score") is None:
        return "not_run"
    risk = _score_or_none(payload.get("risk_score"))
    if risk is None:
        return "unavailable"
    if risk >= 50:
        return "blocked"
    if risk >= 26:
        return "at_risk"
    if risk >= 11:
        return "needs_review"
    return "ok"
