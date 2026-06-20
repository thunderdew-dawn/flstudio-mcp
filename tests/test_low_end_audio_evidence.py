from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot import control_center
from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.interactions import manual_audio_render_task
from fls_pilot.runtime.workflow_runner import run_workflow


def test_low_end_report_keeps_proxy_labeling(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    bridge = FakeBridge()
    runtime.get_static_project_snapshot(bridge)
    manifest = artifacts.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {
                "duration_seconds": 60.0,
                "low_end_energy_ratio": 0.45,
                "low_band_stereo_proxy": -0.25,
            },
        },
        source_sha256="1" * 64,
        source_size_bytes=100,
        source_basename="master.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )
    runtime.attach_audio_artifact(
        manifest.artifact_id,
        evidence_kind="rendered_master",
        workflow_targets=("low_end_analysis",),
    )
    try:
        report = run_workflow(runtime, "low_end_analysis", bridge=bridge)
        finding = next(
            row
            for row in report["findings"]
            if row["rule_id"] == "low_end.rendered_audio_proxy"
        )
        assert finding["severity"] == "medium"
        assert finding["evidence"][0]["proxy_notice"] == "Not mono-cancellation proof."
        assert "proxy" in finding["limitations"][0].lower()
        assert report["ruleset_id"] == "core.low-end.metadata"
        assert report["ruleset_version"] == "1.0.0"
        assert report["profile_id"] == "default"
    finally:
        runtime.close()


def test_low_end_declarative_rule_failure_does_not_crash(monkeypatch) -> None:
    legacy = {
        "ok": True,
        "workflow": "low_end_analysis",
        "title": "Low-End Analysis",
        "evidence_mode": "static_snapshot_only",
        "summary": {"levels_valid": False},
        "details": {
            "tracks": [{"track": 2, "name": "Bass", "pan": 0.4}],
            "low_end": {
                "tracks": [{"track": 2, "name": "Bass", "pan": 0.4}],
                "findings": [],
            },
        },
    }
    monkeypatch.setattr(
        control_center,
        "evaluate_rules",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad rule")),
    )

    report = control_center._build_low_end_analysis_report(legacy)

    assert report.ruleset_id == "core.low-end.metadata"
    assert report.findings == ()
    assert report.metadata["rule_evaluation_errors"] == ["ValueError: bad rule"]
    assert "rules were skipped" in " ".join(report.limitations)


def test_low_end_report_can_represent_manual_audio_task() -> None:
    report = control_center._build_low_end_analysis_report(
        {
            "ok": True,
            "workflow": "low_end_analysis",
            "title": "Low-End Analysis",
            "evidence_mode": "static_snapshot_only",
            "summary": {"levels_valid": False},
            "details": {"low_end": {"tracks": [], "findings": []}},
        }
    )
    task = manual_audio_render_task()
    report_with_task = type(report)(
        **{
            **report.__dict__,
            "interaction_requests": (task.to_dict(),),
        }
    )

    payload = report_with_task.to_dict()

    assert payload["interaction_requests"][0]["id"] == "audio.render_master"
    assert payload["interaction_requests"][0]["resume_input"]["type"] == "file_path"
    assert payload["interaction_requests"][0]["metadata"]["automatic_render"] is False
