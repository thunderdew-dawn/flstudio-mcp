from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore


def _publish(store: AudioArtifactStore, source_hash: str = "a" * 64):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {
                "duration_seconds": 10.0,
                "peak_dbfs": -1.0,
                "rms_dbfs": -12.0,
                "band_energy": {"sub": 0.1, "low": 0.2, "mid": 0.6, "high": 0.1},
                "low_end_energy_ratio": 0.3,
                "stereo_correlation_proxy": 0.8,
                "low_band_stereo_proxy": 0.95,
            },
        },
        source_sha256=source_hash,
        source_size_bytes=100,
        source_basename="mix.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )


def test_runtime_records_real_rendered_audio_observation(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    runtime.get_static_project_snapshot(FakeBridge())
    manifest = _publish(artifacts)
    try:
        observation, link = runtime.attach_audio_artifact(
            manifest.artifact_id,
            evidence_kind="rendered_master",
            workflow_targets=("mix_review", "project_health"),
        )

        assert observation.kind == "rendered_audio_features"
        assert observation.payload["artifact_id"] == manifest.artifact_id
        assert observation.project_fingerprint == runtime.project_context.project_fingerprint
        assert link.project_scope_id == runtime.project_context.project_scope_id
        assert runtime.rendered_audio_observations(workflow_target="mix_review") == (
            observation,
        )
    finally:
        runtime.close()


def test_deleted_source_does_not_invalidate_complete_artifact(tmp_path) -> None:
    source = tmp_path / "mix.wav"
    source.write_bytes(b"user source")
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    runtime.get_static_project_snapshot(FakeBridge())
    manifest = _publish(artifacts)
    source.unlink()
    try:
        observation, _link = runtime.attach_audio_artifact(
            manifest.artifact_id,
            evidence_kind="rendered_master",
            workflow_targets=("mix_review",),
        )
        assert runtime.rendered_audio_observations() == (observation,)
    finally:
        runtime.close()
