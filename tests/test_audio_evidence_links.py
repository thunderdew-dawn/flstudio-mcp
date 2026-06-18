from __future__ import annotations

import pytest
from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.product_workflows import build_audio_evidence_report


def _publish(store: AudioArtifactStore, source_hash: str):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {
                "duration_seconds": 30.0,
                "peak_dbfs": -2.0,
                "rms_dbfs": -14.0,
                "integrated_lufs": -13.5,
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


def test_audio_report_uses_project_identity_not_file_identity(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    runtime.get_static_project_snapshot(FakeBridge())
    manifest = _publish(artifacts, "a" * 64)
    try:
        report = build_audio_evidence_report(
            runtime,
            manifest.artifact_id,
            workflow_links=("mix_review",),
        )
        assert report.project_fingerprint == runtime.project_context.project_fingerprint
        assert not report.project_fingerprint.startswith("file:")
        assert report.metadata["artifact"]["source_sha256_prefix"] == "a" * 12
        assert report.metadata["evidence_link"]["contract_version"] == (
            "fls-pilot.evidence-link.v1"
        )
    finally:
        runtime.close()


def test_unknown_project_association_requires_confirmation(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    manifest = _publish(artifacts, "b" * 64)
    try:
        with pytest.raises(ValueError, match="user_confirmation_required"):
            runtime.attach_audio_artifact(
                manifest.artifact_id,
                evidence_kind="rendered_master",
            )
        observation, link = runtime.attach_audio_artifact(
            manifest.artifact_id,
            evidence_kind="rendered_master",
            confirmed_by_user=True,
        )
        assert observation.kind == "rendered_audio_features"
        assert link.confirmed_by_user is True
    finally:
        runtime.close()


def test_changed_source_content_invalidates_previous_link(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    runtime.get_static_project_snapshot(FakeBridge())
    first = _publish(artifacts, "c" * 64)
    second = _publish(artifacts, "d" * 64)
    try:
        _first_observation, first_link = runtime.attach_audio_artifact(
            first.artifact_id,
            evidence_kind="rendered_master",
            workflow_targets=("mix_review",),
        )
        _second_observation, second_link = runtime.attach_audio_artifact(
            second.artifact_id,
            evidence_kind="rendered_master",
            workflow_targets=("mix_review",),
        )
        assert runtime.evidence_links.get(first_link.link_id).active is False
        assert runtime.evidence_links.get(first_link.link_id).invalidation_reason == (
            "audio_source_hash_changed"
        )
        assert second_link.active is True
    finally:
        runtime.close()
