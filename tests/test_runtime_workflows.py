from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow


def test_mix_review_runs_and_stores_scoped_report(tmp_path) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
    bridge = FakeBridge()

    result = run_workflow(runtime, "mix_review", bridge=bridge)
    report = runtime.latest_report("mix_review")

    assert result["workflow"] == "mix_review"
    assert result["contract_version"] == "fls-pilot.analysis-report.v1"
    assert "analysis_report" not in result["details"]
    assert report is not None
    assert report.project_scope_id == runtime.project_context.project_scope_id
    assert report.snapshot_id == runtime.project_context.snapshot_id


def test_legacy_workflow_runner_forwards_user_decisions(tmp_path, monkeypatch) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
    bridge = FakeBridge()
    calls = []

    def fake_runner(state, *, bridge_override=None, inputs=None):  # noqa: ANN001
        calls.append({"bridge": bridge_override, "inputs": inputs})
        return {"ok": True, "workflow": "mix_review"}

    monkeypatch.setattr("fls_pilot.control_center._run_mix_review", fake_runner)

    result = run_workflow(
        runtime,
        "mix_review",
        bridge=bridge,
        inputs={
            "user_decisions": [
                {
                    "interaction_id": "mix_review.confirm_heuristics",
                    "decision": "confirmed",
                }
            ]
        },
    )

    assert result == {"ok": True, "workflow": "mix_review"}
    assert calls == [
        {
            "bridge": bridge,
            "inputs": {
                "user_decisions": [
                    {
                        "interaction_id": "mix_review.confirm_heuristics",
                        "decision": "confirmed",
                    }
                ]
            },
        }
    ]


def test_legacy_workflow_runner_rejects_unknown_inputs(tmp_path) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")

    try:
        run_workflow(
            runtime,
            "mix_review",
            bridge=FakeBridge(),
            inputs={"unsafe": True},
        )
    except ValueError as exc:
        assert "mix_review does not accept workflow inputs" in str(exc)
    else:
        raise AssertionError("run_workflow accepted unsupported legacy inputs")


def test_routing_workflow_runner_accepts_audit_options(tmp_path, monkeypatch) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
    bridge = FakeBridge()
    calls = []

    def fake_runner(state, *, bridge_override=None, inputs=None):  # noqa: ANN001
        calls.append({"bridge": bridge_override, "inputs": inputs})
        return {"ok": True, "workflow": "routing_audit"}

    monkeypatch.setattr("fls_pilot.control_center._run_routing_audit", fake_runner)

    result = run_workflow(
        runtime,
        "routing_audit",
        bridge=bridge,
        inputs={
            "routing_check_mode": "level_2_signal_flow",
            "template_compliance": "manual_select",
            "selected_template_profile": "psytrance",
            "playback_decision": "manual_playback_running",
            "marker_name": "Drop",
            "loop_duration_seconds": 16,
        },
    )

    assert result == {"ok": True, "workflow": "routing_audit"}
    assert calls[0]["inputs"]["routing_check_mode"] == "level_2_signal_flow"
    assert calls[0]["inputs"]["selected_template_profile"] == "psytrance"


def test_all_l1_workflows_share_current_project_scope(tmp_path, monkeypatch) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
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
