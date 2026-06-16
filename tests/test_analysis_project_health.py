import pytest
from typing import Any

from fls_pilot.analysis.schema import AnalysisReport, Coverage, Freshness, Prerequisite
from fls_pilot.analysis.store import ReportStore
from fls_pilot.analysis.health_aggregator import aggregate_project_health

def _fake_report(workflow: str, health: int, risk: int, conf: int) -> AnalysisReport:
    return AnalysisReport(
        workflow=workflow,
        title=workflow.replace("_", " ").title(),
        analysis_mode="static_snapshot",
        freshness=Freshness(status="fresh"),
        coverage=Coverage(required=1, available=1),
        prerequisites=(Prerequisite("fl_session_alive", "ok"),),
        risk_score=risk,
        health_score=health,
        confidence_score=conf,
    )

def test_report_store_keeps_latest_per_workflow():
    store = ReportStore(limit_per_workflow=2)
    
    r1 = _fake_report("mix_review", 50, 50, 50)
    r2 = _fake_report("mix_review", 80, 20, 90)
    r3 = _fake_report("routing_audit", 100, 0, 100)
    
    store.add_report(r1)
    assert store.get_latest_report("mix_review") is r1
    
    store.add_report(r2)
    assert store.get_latest_report("mix_review") is r2
    
    store.add_report(r3)
    assert store.get_latest_report("routing_audit") is r3
    
def test_project_health_aggregator_missing_reports():
    store = ReportStore()
    agg = aggregate_project_health(store)
    
    assert agg["overall_health_score"] is None
    assert agg["overall_risk_score"] is None
    assert agg["overall_confidence_score"] == 0
    assert agg["overall_coverage_pct"] == 0
    assert len(agg["missing_workflows"]) == 4
    
    for sec in agg["sections"]:
        assert sec["freshness"] == "missing"
        assert sec["recommended_next_action"]["type"] == "run_workflow"

def test_project_health_aggregator_with_reports():
    store = ReportStore()
    store.add_report(_fake_report("mix_review", health=80, risk=20, conf=100))
    store.add_report(_fake_report("project_organizer", health=90, risk=10, conf=80))
    
    agg = aggregate_project_health(store)
    
    # 2 available out of 4, 2 missing
    assert agg["overall_health_score"] == 85
    assert agg["overall_risk_score"] == 15
    assert agg["overall_confidence_score"] == 45 # (100 + 80 + 0 + 0) / 4
    assert len(agg["missing_workflows"]) == 2
    
    mix_sec = next(s for s in agg["sections"] if s["workflow"] == "mix_review")
    assert mix_sec["freshness"] == "fresh"
    assert mix_sec["health_score"] == 80
    assert mix_sec["risk_score"] == 20
    
    missing_sec = next(s for s in agg["sections"] if s["workflow"] == "routing_audit")
    assert missing_sec["freshness"] == "missing"
