"""Project Health backend aggregation over stored workflow reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .schema import AnalysisReport
from .store import ReportStore
from ..runtime.contracts import ProjectContext

WORKFLOWS = (
    ("project_organizer", "Organizer"),
    ("mix_review", "Mix Review"),
    ("routing_audit", "Routing Audit"),
    ("low_end_analysis", "Low-End Analysis"),
)
USABLE_FRESHNESS = {"fresh", "partial"}


def aggregate_project_health(
    store: ReportStore,
    *,
    project_context: ProjectContext | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build Project Health without re-running source workflows."""
    current = now or datetime.now(timezone.utc)
    sections: list[dict[str, Any]] = []
    usable_reports: list[AnalysisReport] = []
    missing_workflows: list[str] = []
    coverage_available = 0
    coverage_required = 0
    fingerprints: set[str] = set()

    reports = {
        workflow: (
            store.get_latest_compatible(workflow, project_context)
            if project_context is not None
            else store.get_latest_report(workflow)
        )
        for workflow, _title in WORKFLOWS
    }
    for report in reports.values():
        if report and report.project_fingerprint not in {None, "unknown"}:
            fingerprints.add(str(report.project_fingerprint))
    mixed_projects = project_context is None and len(fingerprints) > 1

    for workflow, title in WORKFLOWS:
        report = reports[workflow]
        if report is None:
            missing_workflows.append(workflow)
            coverage_required += 1
            sections.append(_missing_section(workflow, title))
            continue

        freshness = effective_freshness(report, now=current)
        if mixed_projects and report.project_fingerprint not in {None, "unknown"}:
            freshness = "stale"

        coverage = report.coverage
        coverage_available += coverage.available
        coverage_required += coverage.required
        usable = freshness in USABLE_FRESHNESS and coverage.available > 0
        if usable:
            usable_reports.append(report)

        section = {
            "workflow": workflow,
            "title": title,
            "report_id": report.report_id,
            "project_fingerprint": report.project_fingerprint or "unknown",
            "freshness": freshness,
            "health_score": report.health_score,
            "risk_score": report.risk_score,
            "coverage": coverage.to_dict(),
            "confidence_score": report.confidence_score,
            "evidence_mode": report.evidence_mode,
            "findings": [finding.to_dict() for finding in report.findings],
            "next_actions": [dict(row) for row in report.next_actions],
        }
        if freshness != "fresh":
            section["reason"] = _section_reason(
                report,
                freshness=freshness,
                mixed_projects=mixed_projects,
            )
        section["recommended_next_action"] = _next_action(
            report,
            workflow=workflow,
            title=title,
            freshness=freshness,
        )
        sections.append(section)

    all_workflows_usable = len(usable_reports) == len(WORKFLOWS)
    overall_health = (
        round(sum(report.health_score for report in usable_reports) / len(usable_reports))
        if all_workflows_usable
        else None
    )
    overall_risk = (
        round(sum(report.risk_score for report in usable_reports) / len(usable_reports))
        if all_workflows_usable
        else None
    )
    overall_confidence = round(
        sum(
            report.confidence_score if report in usable_reports else 0
            for report in reports.values()
            if report is not None
        )
        / len(WORKFLOWS)
    )
    overall_coverage = (
        round((coverage_available / coverage_required) * 100) if coverage_required else 0
    )
    next_workflows = [
        section["recommended_next_action"]
        for section in sections
        if section.get("recommended_next_action")
    ]

    return {
        "overall_status": "fresh" if all_workflows_usable else "partial",
        "overall_health_score": overall_health,
        "overall_risk_score": overall_risk,
        "overall_coverage_pct": overall_coverage,
        "overall_confidence_score": overall_confidence,
        "sections": sections,
        "missing_workflows": missing_workflows,
        "mixed_project_fingerprints": mixed_projects,
        "next_suggested_workflows": next_workflows,
        "runtime_session_id": (
            project_context.runtime_session_id if project_context else "unknown"
        ),
        "project_scope_id": (
            project_context.project_scope_id if project_context else "unknown"
        ),
        "snapshot_id": project_context.snapshot_id if project_context else "unknown",
    }


def effective_freshness(
    report: AnalysisReport,
    *,
    now: datetime | None = None,
) -> str:
    """Resolve stored freshness against its validity timestamps."""
    status = report.freshness.status
    if status not in USABLE_FRESHNESS:
        return status
    current = now or datetime.now(timezone.utc)
    valid_until = _parse_iso(report.freshness.valid_until)
    if valid_until is not None and current > valid_until:
        return "stale"
    return status


def _missing_section(workflow: str, title: str) -> dict[str, Any]:
    return {
        "workflow": workflow,
        "title": title,
        "report_id": None,
        "project_fingerprint": "unknown",
        "freshness": "missing",
        "health_score": None,
        "risk_score": None,
        "coverage": {
            "required": 1,
            "available": 0,
            "missing": ["workflow_report"],
            "optional_available": 0,
            "status": "unavailable",
            "score": 0,
        },
        "confidence_score": 0,
        "evidence_mode": "unknown",
        "reason": "Report not run in this session",
        "recommended_next_action": {
            "type": "run_workflow",
            "workflow": workflow,
            "label": f"Run {title}",
        },
    }


def _section_reason(
    report: AnalysisReport,
    *,
    freshness: str,
    mixed_projects: bool,
) -> str:
    if mixed_projects and report.project_fingerprint not in {None, "unknown"}:
        return "Stored reports belong to different project snapshots"
    reason = f"Report is {freshness}"
    if report.freshness.details:
        reason += f": {report.freshness.details}"
    return reason


def _next_action(
    report: AnalysisReport,
    *,
    workflow: str,
    title: str,
    freshness: str,
) -> dict[str, Any] | None:
    if freshness == "fresh" and report.next_actions:
        return dict(report.next_actions[0])
    if freshness == "fresh":
        return None
    if report.evidence_mode in {"no_level_evidence", "static_snapshot_only"}:
        label = f"Play project and run {title}"
    elif report.evidence_mode == "short_live_snapshot":
        label = f"Capture a longer live window for {title}"
    else:
        label = f"Run {title}"
    return {"type": "run_workflow", "workflow": workflow, "label": label}


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
