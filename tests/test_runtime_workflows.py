from __future__ import annotations

from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow

from test_runtime_core import FakeBridge


def test_mix_review_runs_and_stores_scoped_report() -> None:
    runtime = RuntimeCore()
    bridge = FakeBridge()

    result = run_workflow(runtime, "mix_review", bridge=bridge)
    report = runtime.latest_report("mix_review")

    assert result["workflow"] == "mix_review"
    assert result["details"]["analysis_report"]["workflow"] == "mix_review"
    assert report is not None
    assert report.project_scope_id == runtime.project_context.project_scope_id
    assert report.snapshot_id == runtime.project_context.snapshot_id


def test_all_l1_workflows_share_current_project_scope(monkeypatch) -> None:
    runtime = RuntimeCore()
    bridge = FakeBridge()
    monkeypatch.setattr(
        "fls_pilot.control_center._probe_unused_mixer_tracks",
        lambda *args, **kwargs: {
            "tracks": [],
            "truncated": False,
            "probe_failed": False,
        },
    )

    for workflow in (
        "mix_review",
        "routing_audit",
        "low_end_analysis",
        "project_organizer",
    ):
        result = run_workflow(runtime, workflow, bridge=bridge)
        assert result["workflow"] == workflow

    scopes = {
        runtime.latest_report(workflow).project_scope_id
        for workflow in (
            "mix_review",
            "routing_audit",
            "low_end_analysis",
            "project_organizer",
        )
    }
    assert scopes == {runtime.project_context.project_scope_id}
    assert runtime.project_health()["overall_status"] == "fresh"
