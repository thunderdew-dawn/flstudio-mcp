"""Project Health backend aggregator."""

from __future__ import annotations

from typing import Any

from .schema import AnalysisReport
from .store import ReportStore


def aggregate_project_health(store: ReportStore) -> dict[str, Any]:
    """Consume the latest available reports to build a backend Project Health aggregate."""
    workflows = [
        {"id": "project_organizer", "title": "Organizer"},
        {"id": "mix_review", "title": "Mix Review"},
        {"id": "routing_audit", "title": "Routing Audit"},
        {"id": "low_end_analysis", "title": "Low-End Analysis"},
    ]

    sections = []
    total_risk = 0
    total_health = 0
    total_confidence = 0
    total_coverage_available = 0
    total_coverage_required = 0
    missing_workflows = []
    available_workflows = 0

    for wf in workflows:
        report = store.get_latest_report(wf["id"])
        if report is not None:
            available_workflows += 1
            risk = report.risk_score
            health = report.health_score if report.health_score is not None else (100 - risk)
            confidence = report.confidence_score
            coverage = report.coverage

            total_risk += risk
            total_health += health
            total_confidence += confidence
            total_coverage_available += coverage.available
            total_coverage_required += coverage.required

            section = {
                "workflow": wf["id"],
                "title": wf["title"],
                "report_id": report.report_id,
                "freshness": report.freshness.status,
                "health_score": health,
                "risk_score": risk,
                "coverage": coverage.to_dict(),
                "confidence_score": confidence,
            }

            if report.freshness.status in {"stale", "missing", "unavailable", "partial"}:
                section["reason"] = f"Report is {report.freshness.status}"
                if report.freshness.details:
                    section["reason"] += f": {report.freshness.details}"
                    
                evidence = getattr(report, "evidence_mode", "static_snapshot_only")
                if evidence in ("no_level_evidence", "static_snapshot_only"):
                    section["recommended_next_action"] = {
                        "type": "run_workflow",
                        "workflow": wf["id"],
                        "label": f"Play project and run {wf['title']}",
                    }
                elif evidence == "short_live_snapshot":
                    section["recommended_next_action"] = {
                        "type": "run_workflow",
                        "workflow": wf["id"],
                        "label": f"Capture longer live window for {wf['title']}",
                    }
                else:
                    section["recommended_next_action"] = {
                        "type": "run_workflow",
                        "workflow": wf["id"],
                        "label": f"Run {wf['title']}",
                    }
            elif report.next_actions:
                section["recommended_next_action"] = report.next_actions[0]
            else:
                section["recommended_next_action"] = None

            sections.append(section)
        else:
            missing_workflows.append(wf["id"])
            total_coverage_required += 1  # Add basic required evidence

            sections.append({
                "workflow": wf["id"],
                "title": wf["title"],
                "report_id": None,
                "freshness": "missing",
                "health_score": None,
                "risk_score": None,
                "coverage": {
                    "required": 1,
                    "available": 0,
                    "missing": ["workflow_report"],
                    "status": "unavailable",
                    "score": 0,
                },
                "confidence_score": 0,
                "reason": "Report not run in this session",
                "recommended_next_action": {
                    "type": "run_workflow",
                    "workflow": wf["id"],
                    "label": f"Run {wf['title']}",
                },
            })

    # Overall calculation
    count = len(workflows)
    if available_workflows > 0:
        overall_health = round(total_health / available_workflows)
        overall_risk = round(total_risk / available_workflows)
        overall_confidence = round(total_confidence / count)  # Missing reduces confidence
    else:
        overall_health = None
        overall_risk = None
        overall_confidence = 0

    if total_coverage_required > 0:
        overall_coverage_pct = round((total_coverage_available / total_coverage_required) * 100)
    else:
        overall_coverage_pct = 100

    next_workflows = []
    for section in sections:
        if section.get("recommended_next_action") and section["recommended_next_action"].get("type") == "run_workflow":
            next_workflows.append(section["recommended_next_action"])

    return {
        "overall_health_score": overall_health,
        "overall_risk_score": overall_risk,
        "overall_coverage_pct": overall_coverage_pct,
        "overall_confidence_score": overall_confidence,
        "sections": sections,
        "missing_workflows": missing_workflows,
        "next_suggested_workflows": next_workflows,
    }
