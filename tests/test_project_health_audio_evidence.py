from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow


def test_project_health_aggregates_audio_observations_without_recomputing(tmp_path) -> None:
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
                "peak_dbfs": -2.0,
                "low_end_energy_ratio": 0.25,
                "low_band_stereo_proxy": 0.9,
            },
        },
        source_sha256="2" * 64,
        source_size_bytes=100,
        source_basename="master.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )
    runtime.attach_audio_artifact(
        manifest.artifact_id,
        evidence_kind="rendered_master",
        workflow_targets=("mix_review", "low_end_analysis"),
    )
    try:
        for workflow in (
            "mix_review",
            "routing_audit",
            "low_end_analysis",
            "project_organizer",
        ):
            run_workflow(runtime, workflow, bridge=bridge)
        health = runtime.project_health()

        assert health["observation_summary"]["rendered_audio_features"] == 1
        assert health["observation_summary"]["audio_evidence_levels"] == [2]
        mix = next(
            row for row in health["sections"] if row["workflow"] == "mix_review"
        )
        assert not any(
            finding["rule_id"] == "mix.rendered_master_features"
            for finding in mix["findings"]
        )
    finally:
        runtime.close()
