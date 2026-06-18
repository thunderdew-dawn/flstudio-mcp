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
    """Return one canonical report with optional non-contract UI detail fields.

    The canonical report remains the top-level object. Existing presentation
    details may be retained temporarily as additional fields, but no nested
    report envelope or reconstructed score is created.
    """
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
    return payload
