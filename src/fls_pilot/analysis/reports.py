"""Adapters between analysis reports and existing public report envelopes."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

from ..workflow_report import diagnostic, render_markdown, workflow_report
from .canonical import channel_entity_id, mixer_entity_id
from .runtime import get_report_store
from .schema import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
)
from .scoring import confidence_from_coverage, risk_from_severities


def analysis_report_to_workflow_report(
    report: AnalysisReport,
    *,
    status: str | None = None,
    ok: bool | None = None,
) -> dict[str, Any]:
    """Render an internal analysis report through the current v1 envelope."""
    get_report_store().add_report(report)
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


def enrich_workflow_report_with_analysis(
    payload: dict[str, Any],
    *,
    analysis_mode: str = "static_snapshot",
    evidence_mode: str | None = None,
    project_fingerprint: str | None = None,
    source_observations: tuple[str, ...] = (),
    ttl_seconds: float = 120.0,
) -> dict[str, Any]:
    """Attach an internal AnalysisReport while preserving workflow-report.v1."""
    report = analysis_report_from_workflow_report(
        payload,
        analysis_mode=analysis_mode,
        evidence_mode=evidence_mode,
        project_fingerprint=project_fingerprint,
        source_observations=source_observations,
        ttl_seconds=ttl_seconds,
    )
    get_report_store().add_report(report)
    data = report.to_dict()
    enriched = dict(payload)
    metadata = dict(enriched.get("metadata") or {})
    metadata.update(
        {
            "analysis_report_contract_version": ANALYSIS_REPORT_CONTRACT_VERSION,
            "analysis_report_id": report.report_id,
            "analysis_report": data,
            "source_observations": list(report.source_observations),
        }
    )
    enriched["metadata"] = metadata
    enriched["analysis"] = {
        key: data[key]
        for key in (
            "contract_version",
            "report_id",
            "workflow",
            "created_at",
            "analysis_mode",
            "evidence_mode",
            "project_fingerprint",
            "freshness",
            "coverage",
            "prerequisites",
            "risk_score",
            "risk_band",
            "health_score",
            "confidence_score",
            "source_observations",
        )
    }
    json_report = deepcopy(
        {
            key: value
            for key, value in enriched.items()
            if key not in {"json_report", "markdown_report"}
        }
    )
    enriched["json_report"] = json_report
    enriched["markdown_report"] = render_markdown(json_report)
    return enriched


def analysis_report_from_workflow_report(
    payload: dict[str, Any],
    *,
    analysis_mode: str,
    evidence_mode: str | None = None,
    project_fingerprint: str | None = None,
    source_observations: tuple[str, ...] = (),
    ttl_seconds: float = 120.0,
) -> AnalysisReport:
    """Adapt an existing workflow-report.v1 payload into AnalysisReport."""
    ok = bool(payload.get("ok", True))
    diagnostics = [
        dict(row) for row in payload.get("diagnostics") or [] if isinstance(row, dict)
    ]
    available = int(ok)
    coverage = Coverage(
        required=1,
        available=available,
        missing=() if available else ("workflow_report",),
    )
    confidence = confidence_from_coverage(
        required=coverage.required,
        available=coverage.available,
        evidence_mode=analysis_mode,
    )
    severities = tuple(row.get("severity", "info") for row in diagnostics)
    risk = risk_from_severities(severities)
    summary = dict(payload.get("summary") or {})
    created_at = datetime.now(timezone.utc)
    findings = tuple(
        _finding_from_diagnostic(
            row,
            workflow=str(payload.get("workflow") or "workflow"),
            index=index,
            analysis_mode=analysis_mode,
            confidence=confidence,
        )
        for index, row in enumerate(diagnostics, start=1)
    )
    return AnalysisReport(
        workflow=str(payload.get("workflow") or "workflow"),
        title=str(payload.get("title") or payload.get("workflow") or "Workflow"),
        analysis_mode=analysis_mode,
        evidence_mode=evidence_mode or _default_evidence_mode(analysis_mode),
        created_at=created_at.isoformat(),
        project_fingerprint=project_fingerprint,
        freshness=Freshness(
            status="fresh" if ok else "unavailable",
            created_at=created_at.isoformat(),
            valid_until=(created_at + timedelta(seconds=ttl_seconds)).isoformat(),
            source_observation_ids=source_observations,
        ),
        coverage=coverage,
        prerequisites=(
            Prerequisite("fl_session_alive", "ok" if ok else "unavailable"),
        ),
        risk_score=risk,
        health_score=summary.get("health_score"),
        confidence_score=confidence,
        findings=findings,
        assumptions=tuple(str(row) for row in payload.get("notes") or []),
        limitations=tuple(str(row) for row in payload.get("limits") or []),
        manual_checks=tuple(
            dict(row)
            for row in payload.get("manual_checks") or []
            if isinstance(row, dict)
        ),
        source_observations=source_observations,
        proposed_changes=tuple(
            dict(row)
            for row in payload.get("proposed_changes") or []
            if isinstance(row, dict)
        ),
        applied_changes=tuple(
            dict(row)
            for row in payload.get("applied_changes") or []
            if isinstance(row, dict)
        ),
        safety=dict(payload.get("safety") or {"read_only": True}),
        metadata={"legacy_summary": summary},
    )


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


def _finding_from_diagnostic(
    row: dict[str, Any],
    *,
    workflow: str,
    index: int,
    analysis_mode: str,
    confidence: int,
) -> Finding:
    severity = str(row.get("severity") or "info")
    target = dict(row.get("target") or {})
    entities = _entities_from_target(target)
    return Finding(
        id=str(row.get("id") or f"{workflow}.finding.{index}"),
        rule_id=str(row.get("source") or row.get("id") or f"{workflow}.finding"),
        title=str(row.get("message") or row.get("id") or "Finding"),
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=confidence,
        evidence_mode=analysis_mode,
        entities=entities,
        evidence=({"evidence": row.get("evidence"), "target": target},),
        metadata={"workflow_diagnostic": row},
    )


def _entities_from_target(target: dict[str, Any]) -> tuple[EntityRef, ...]:
    target_type = str(target.get("type") or "")
    index = target.get("index", target.get("track"))
    try:
        numeric_index = int(index)
    except (TypeError, ValueError):
        return ()
    if target_type == "channel":
        canonical_id = channel_entity_id(numeric_index)
    elif target_type in {"mixer", "mixer_track", "track"}:
        canonical_id = mixer_entity_id(numeric_index)
    else:
        return ()
    return (
        EntityRef(
            type=target_type,
            canonical_id=canonical_id,
            display_name=target.get("name"),
        ),
    )


def _default_evidence_mode(analysis_mode: str) -> str:
    return {
        "static_snapshot": "static_snapshot_only",
        "live_runtime": "short_live_snapshot",
        "watch_window": "sufficient_watch_window",
    }.get(analysis_mode, analysis_mode)
