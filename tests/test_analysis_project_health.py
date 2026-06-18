from datetime import datetime, timedelta, timezone

from fls_pilot.analysis.health_aggregator import aggregate_project_health
from fls_pilot.analysis.schema import AnalysisReport, Coverage, Freshness, Prerequisite
from fls_pilot.analysis.store import ReportStore


def _fake_report(
    workflow: str,
    health: int,
    risk: int,
    confidence: int,
    *,
    now: datetime,
    fingerprint: str = "proj_test",
    freshness: str = "fresh",
) -> AnalysisReport:
    return AnalysisReport(
        workflow=workflow,
        title=workflow.replace("_", " ").title(),
        analysis_mode="static_snapshot",
        evidence_mode="static_snapshot_only",
        created_at=now.isoformat(),
        project_fingerprint=fingerprint,
        freshness=Freshness(
            status=freshness,
            created_at=now.isoformat(),
            valid_until=(now + timedelta(seconds=60)).isoformat(),
        ),
        coverage=Coverage(required=1, available=1),
        prerequisites=(Prerequisite("fl_session_alive", "ok"),),
        risk_score=risk,
        health_score=health,
        confidence_score=confidence,
    )


def test_report_store_keeps_latest_per_workflow() -> None:
    now = datetime.now(timezone.utc)
    store = ReportStore(limit_per_workflow=2)
    first = _fake_report("mix_review", 50, 50, 50, now=now)
    second = _fake_report("mix_review", 80, 20, 90, now=now)
    routing = _fake_report("routing_audit", 100, 0, 100, now=now)

    store.add_report(first)
    assert store.get_latest_report("mix_review") is first
    store.add_report(second)
    assert store.get_latest_report("mix_review") is second
    store.add_report(routing)
    assert store.get_latest_report("routing_audit") is routing


def test_project_health_aggregator_missing_reports() -> None:
    aggregate = aggregate_project_health(ReportStore())

    assert aggregate["overall_status"] == "partial"
    assert aggregate["overall_health_score"] is None
    assert aggregate["overall_risk_score"] is None
    assert aggregate["overall_confidence_score"] == 0
    assert aggregate["overall_coverage_pct"] == 0
    assert len(aggregate["missing_workflows"]) == 4
    assert all(
        section["recommended_next_action"]["type"] == "run_workflow"
        for section in aggregate["sections"]
    )


def test_partial_health_does_not_hide_missing_workflows_behind_good_score() -> None:
    now = datetime.now(timezone.utc)
    store = ReportStore()
    store.add_report(_fake_report("mix_review", 100, 0, 100, now=now))

    aggregate = aggregate_project_health(store, now=now)

    assert aggregate["overall_status"] == "partial"
    assert aggregate["overall_health_score"] is None
    assert aggregate["overall_risk_score"] is None
    assert aggregate["overall_coverage_pct"] == 25


def test_project_health_aggregates_all_fresh_reports() -> None:
    now = datetime.now(timezone.utc)
    store = ReportStore()
    values = {
        "project_organizer": (90, 10, 80),
        "mix_review": (80, 20, 100),
        "routing_audit": (70, 30, 60),
        "low_end_analysis": (60, 40, 40),
    }
    for workflow, (health, risk, confidence) in values.items():
        store.add_report(
            _fake_report(
                workflow,
                health,
                risk,
                confidence,
                now=now,
            )
        )

    aggregate = aggregate_project_health(store, now=now)

    assert aggregate["overall_status"] == "fresh"
    assert aggregate["overall_health_score"] == 75
    assert aggregate["overall_risk_score"] == 25
    assert aggregate["overall_confidence_score"] == 70
    assert aggregate["overall_coverage_pct"] == 100


def test_expired_report_is_marked_stale() -> None:
    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=1)
    store = ReportStore()
    store.add_report(_fake_report("mix_review", 100, 0, 100, now=old))

    aggregate = aggregate_project_health(store, now=now)
    mix_section = next(
        section for section in aggregate["sections"] if section["workflow"] == "mix_review"
    )

    assert mix_section["freshness"] == "stale"
    assert aggregate["overall_health_score"] is None


def test_mixed_project_fingerprints_are_not_aggregated() -> None:
    now = datetime.now(timezone.utc)
    store = ReportStore()
    store.add_report(
        _fake_report(
            "mix_review",
            80,
            20,
            90,
            now=now,
            fingerprint="proj_one",
        )
    )
    store.add_report(
        _fake_report(
            "routing_audit",
            80,
            20,
            90,
            now=now,
            fingerprint="proj_two",
        )
    )

    aggregate = aggregate_project_health(store, now=now)

    assert aggregate["mixed_project_fingerprints"] is True
    assert aggregate["overall_health_score"] is None
    assert {
        section["freshness"]
        for section in aggregate["sections"]
        if section["report_id"] is not None
    } == {"stale"}
