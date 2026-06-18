from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
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
    finally:
        runtime.close()
