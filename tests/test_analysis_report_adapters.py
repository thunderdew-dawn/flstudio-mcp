from __future__ import annotations

from fls_pilot.analysis import (
    ANALYSIS_REPORT_CONTRACT_VERSION,
    AnalysisReport,
    Coverage,
    Freshness,
    analysis_report_for_control_center,
    serialize_analysis_report,
)


def test_analysis_report_serialization_is_canonical() -> None:
    report = AnalysisReport(
        report_id="rep_direct",
        workflow="routing_review",
        title="Routing Review",
        analysis_mode="static_snapshot",
        freshness=Freshness(status="fresh"),
        coverage=Coverage(required=1, available=1),
        risk_score=20,
        confidence_score=80,
    )

    payload = serialize_analysis_report(report)

    assert payload["contract_version"] == ANALYSIS_REPORT_CONTRACT_VERSION
    assert payload["report_id"] == "rep_direct"
    assert "analysis" not in payload
    assert "analysis_report" not in payload.get("metadata", {})


def test_control_center_adds_ui_details_without_a_report_envelope() -> None:
    report = AnalysisReport(
        workflow="low_end_analysis",
        title="Low-End Analysis",
        analysis_mode="static_snapshot",
    )

    payload = analysis_report_for_control_center(
        report,
        {
            "summary": {"low_end_findings": 2},
            "details": {"low_end": {"findings": ["one", "two"]}},
            "analysis": {"legacy": True},
        },
    )

    assert payload["contract_version"] == ANALYSIS_REPORT_CONTRACT_VERSION
    assert payload["details"]["low_end"]["findings"] == ["one", "two"]
    assert "analysis" not in payload
