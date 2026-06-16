from __future__ import annotations

from fls_pilot.analysis import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
    analysis_report_to_control_center_legacy,
    analysis_report_to_workflow_report,
)
from fls_pilot.workflow_report import CONTRACT_VERSION


def test_analysis_report_adapter_emits_current_workflow_report_envelope() -> None:
    report = AnalysisReport(
        report_id="rep_adapter_test",
        workflow="routing_review",
        title="Routing Review",
        analysis_mode="static_snapshot",
        freshness=Freshness(status="fresh", source_observation_ids=("obs_static",)),
        coverage=Coverage(required=2, available=2),
        prerequisites=(
            Prerequisite("fl_session_alive", "ok"),
            Prerequisite("static_project_snapshot", "ok"),
        ),
        risk_score=42,
        confidence_score=75,
        findings=(
            Finding(
                id="direct_to_master_1",
                rule_id="routing.direct_to_master",
                title="Instrument routes directly to Master",
                severity="medium",
                risk_score=42,
                confidence_score=75,
                evidence_mode="static_snapshot",
                entities=(EntityRef("mixer_track", "mixer:4", "Lead"),),
                evidence=({"metric": "route_dst", "value": "mixer:master"},),
                source_observation_ids=("obs_routing",),
            ),
        ),
        source_observations=("obs_static", "obs_routing"),
        safety={"read_only": True, "requires_explicit_approval": False},
    )

    payload = analysis_report_to_workflow_report(report)

    assert payload["contract_version"] == CONTRACT_VERSION
    assert payload["workflow"] == "routing_review"
    assert payload["mode"] == "static_snapshot"
    assert payload["status"] == "Analysis generated"
    assert payload["summary"]["risk_score"] == 42
    assert payload["summary"]["health_score"] == 58
    assert payload["summary"]["coverage_status"] == "fresh"
    assert payload["diagnostics"][0]["id"] == "direct_to_master_1"
    assert payload["diagnostics"][0]["target"]["canonical_id"] == "mixer:4"
    assert payload["metadata"]["analysis_report_contract_version"] == (
        ANALYSIS_REPORT_CONTRACT_VERSION
    )
    assert payload["metadata"]["analysis_report"]["report_id"] == "rep_adapter_test"
    assert payload["json_report"]["metadata"]["analysis_report_id"] == "rep_adapter_test"


def test_analysis_report_adapter_marks_partial_evidence_in_status() -> None:
    report = AnalysisReport(
        workflow="mix_review",
        title="Mix Review",
        analysis_mode="static_snapshot",
        freshness=Freshness(status="partial"),
        coverage=Coverage(required=3, available=2, missing=("live_meter_window",)),
        risk_score=10,
        confidence_score=40,
    )

    payload = analysis_report_to_workflow_report(report)

    assert payload["ok"] is True
    assert payload["status"] == "Analysis generated with partial evidence"
    assert payload["summary"]["coverage_status"] == "partial"


def test_analysis_report_adapter_attaches_control_center_metadata() -> None:
    report = AnalysisReport(
        report_id="rep_control_center_test",
        workflow="low_end_analysis",
        title="Low-End Analysis",
        analysis_mode="static_snapshot",
        freshness=Freshness(status="partial"),
        coverage=Coverage(required=2, available=1, missing=("live_meter_window",)),
        risk_score=16,
        confidence_score=50,
        safety={"read_only": True, "project_changes": False},
    )
    legacy = {
        "ok": True,
        "workflow": "low_end_analysis",
        "summary": {"health_score": 80},
        "details": {"low_end": {"findings": []}},
        "safety": {"read_only": True},
    }

    payload = analysis_report_to_control_center_legacy(report, legacy)

    assert payload["workflow"] == "low_end_analysis"
    assert payload["summary"] == {"health_score": 80}
    assert payload["analysis"]["contract_version"] == ANALYSIS_REPORT_CONTRACT_VERSION
    assert payload["analysis"]["report_id"] == "rep_control_center_test"
    assert payload["analysis"]["coverage"]["status"] == "partial"
    assert payload["details"]["low_end"] == {"findings": []}
    assert payload["details"]["analysis_report"]["workflow"] == "low_end_analysis"
    assert payload["safety"]["project_changes"] is False
