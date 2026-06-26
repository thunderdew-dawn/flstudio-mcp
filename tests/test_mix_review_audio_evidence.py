from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow


def _publish_master(store: AudioArtifactStore):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {
                "duration_seconds": 60.0,
                "peak_dbfs": -1.0,
                "rms_dbfs": -13.0,
                "integrated_lufs": -12.5,
                "crest_factor_db": 12.0,
                "band_energy": {"sub": 0.1, "low": 0.2, "mid": 0.6, "high": 0.1},
                "low_end_energy_ratio": 0.3,
                "stereo_correlation_proxy": 0.7,
                "stereo_width_proxy": 0.4,
                "low_band_stereo_proxy": 0.9,
            },
        },
        source_sha256="f" * 64,
        source_size_bytes=100,
        source_basename="master.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )


def test_mix_review_degrades_explicitly_without_audio(tmp_path) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
    try:
        report = run_workflow(runtime, "mix_review", bridge=FakeBridge())
        assert report["metadata"]["evidence_level"] == 1
        assert report["metadata"]["evidence_level_label"] == "static_project_snapshot"
        assert report["metadata"]["audio_evidence_status"] == "missing"
        assert report["metadata"]["automatic_fl_render"] is False
        assert report["metadata"]["evidence_level_4"]["status"] == "planned"
        assert report["coverage"]["status"] == "partial"
        assert report["prerequisites"][-1]["id"] == "rendered_audio_features"
        assert report["prerequisites"][-1]["status"] == "missing"
        assert report["next_actions"][0]["action"] == "submit"
    finally:
        runtime.close()


def test_mix_review_uses_linked_rendered_master(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    bridge = FakeBridge()
    runtime.get_static_project_snapshot(bridge)
    manifest = _publish_master(artifacts)
    runtime.attach_audio_artifact(
        manifest.artifact_id,
        evidence_kind="rendered_master",
        workflow_targets=("mix_review",),
    )
    try:
        report = run_workflow(runtime, "mix_review", bridge=bridge)
        assert report["analysis_mode"] == "hybrid"
        assert report["metadata"]["evidence_level"] == 2
        assert report["metadata"]["evidence_level_label"] == "rendered_master_audio"
        assert report["metadata"]["audio_evidence_status"] == "available"
        assert report["prerequisites"][-1]["status"] == "ok"
        assert "rendered_audio_features" not in report["coverage"]["missing"]
        assert any(
            finding["rule_id"] == "mix.rendered_master_features"
            for finding in report["findings"]
        )
    finally:
        runtime.close()
