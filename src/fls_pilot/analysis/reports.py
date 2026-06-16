"""Adapters between analysis reports and existing public report envelopes."""

from __future__ import annotations

from typing import Any

from ..workflow_report import diagnostic, workflow_report
from .schema import ANALYSIS_REPORT_CONTRACT_VERSION, AnalysisReport, Finding


def analysis_report_to_workflow_report(
    report: AnalysisReport,
    *,
    status: str | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    """Render an internal analysis report through the current v1 envelope."""
    data = report.to_dict()
    effective_ok = data["coverage"]["status"] != "unavailable" if ok is None else bool(ok)
    return workflow_report(
        workflow=report.workflow,
        title=report.title,
        mode=report.analysis_mode,
        status=status or _default_status(data),
        summary=_summary(data),
        diagnostics=[_diagnostic_from_finding(row) for row in report.findings],
        proposed_changes=[dict(row) for row in report.proposed_changes],
        applied_changes=[dict(row) for row in report.applied_changes],
        manual_checks=[dict(row) for row in report.manual_checks],
        notes=list(report.assumptions),
        limits=list(report.limitations),
        ok=effective_ok,
        safety=report.safety,
        metadata={
            "analysis_report_contract_version": ANALYSIS_REPORT_CONTRACT_VERSION,
            "analysis_report_id": report.report_id,
            "analysis_report": data,
            "source_observations": list(report.source_observations),
        },
    )


def analysis_report_to_control_center_legacy(
    report: AnalysisReport,
    legacy_payload: dict[str, Any],
) -> dict[str, Any]:
    """Attach a shared analysis report to an existing Control Center payload."""
    data = report.to_dict()
    payload = dict(legacy_payload)
    details = dict(payload.get("details") or {})
    details["analysis_report"] = data
    payload["details"] = details
    payload["analysis"] = {
        "contract_version": data["contract_version"],
        "report_id": data["report_id"],
        "workflow": data["workflow"],
        "analysis_mode": data["analysis_mode"],
        "evidence_mode": data.get("evidence_mode", "static_snapshot_only"),
        "freshness": data["freshness"],
        "coverage": data["coverage"],
        "prerequisites": data["prerequisites"],
        "risk_score": data["risk_score"],
        "risk_band": data["risk_band"],
        "health_score": data["health_score"],
        "confidence_score": data["confidence_score"],
        "source_observations": data["source_observations"],
    }
    payload["safety"] = {
        **dict(payload.get("safety") or {}),
        **dict(data.get("safety") or {}),
    }
    return payload


def _default_status(data: dict[str, Any]) -> str:
    coverage = data.get("coverage") or {}
    freshness = data.get("freshness") or {}
    if coverage.get("status") == "unavailable":
        return "Analysis unavailable"
    if coverage.get("status") == "partial" or freshness.get("status") == "partial":
        return "Analysis generated with partial evidence"
    return "Analysis generated"


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    coverage = data.get("coverage") or {}
    freshness = data.get("freshness") or {}
    prerequisites = data.get("prerequisites") or []
    return {
        "risk_score": data.get("risk_score"),
        "risk_band": data.get("risk_band"),
        "health_score": data.get("health_score"),
        "confidence_score": data.get("confidence_score"),
        "coverage_status": coverage.get("status"),
        "coverage_score": coverage.get("score"),
        "freshness_status": freshness.get("status"),
        "prerequisites_ok": sum(1 for row in prerequisites if row.get("status") == "ok"),
        "prerequisites_total": len(prerequisites),
        "findings": len(data.get("findings") or []),
    }


def _diagnostic_from_finding(finding: Finding) -> dict[str, Any]:
    data = finding.to_dict()
    target = {}
    entities = data.get("entities") or []
    if entities:
        target = dict(entities[0])
    return diagnostic(
        id=data["id"],
        severity=data["severity"],
        message=data["title"],
        evidence={
            "rule_id": data["rule_id"],
            "risk_score": data["risk_score"],
            "risk_band": data["risk_band"],
            "confidence_score": data["confidence_score"],
            "evidence_mode": data["evidence_mode"],
            "evidence": data["evidence"],
            "assumptions": data["assumptions"],
            "limitations": data["limitations"],
        },
        target=target,
        source=data["rule_id"],
        metadata={
            "analysis_finding": data,
            "source_observation_ids": data["source_observation_ids"],
            "recommended_next_action": data.get("recommended_next_action"),
        },
    )
