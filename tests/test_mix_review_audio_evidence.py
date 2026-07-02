from __future__ import annotations

from test_runtime_core import FakeBridge

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow


def _publish_master(store: AudioArtifactStore, *, source_hash: str = "f" * 64, summary=None):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": summary or {
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
        source_sha256=source_hash,
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
        assert report["metadata"]["score_status"] == "provisional"
        assert "risk_score_v2" in report["metadata"]
        assert report["metadata"]["audio_evidence_status"] == "not_requested"
        assert report["metadata"]["automatic_fl_render"] is False
        assert report["metadata"]["rendered_audio_evidence"]["status"] == "not_requested"
        assert report["metadata"]["requires_manual_audio_export"] is False
        assert report["coverage"]["status"] == "fresh"
        assert "rendered_audio_features" not in report["coverage"]["missing"]
        assert not any(row["id"] == "rendered_audio_features" for row in report["prerequisites"])
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
        report = run_workflow(runtime, "mix_review", bridge=bridge, inputs={"level": 3})
        assert report["analysis_mode"] == "hybrid"
        assert report["metadata"]["mix_review_level"] == 3
        assert report["metadata"]["evidence_level"] == 3
        assert report["metadata"]["evidence_level_label"] == "rendered_master_evidence"
        assert report["metadata"]["audio_evidence_status"] == "available"
        assert report["metadata"]["rendered_audio_evidence"]["status"] == "available"
        assert report["metadata"]["rendered_audio_evidence"]["mix_review_audio_findings"] is True
        assert report["metadata"]["score_status"] == "partial"
        assert any(
            row["id"] == "rendered_audio_features" and row["status"] == "ok"
            for row in report["prerequisites"]
        )
        assert "rendered_audio_features" not in report["coverage"]["missing"]
        assert any(
            finding["rule_id"] == "mix_review.rendered_master_headroom"
            and finding["metadata"]["finding_state"] == "rendered_master_proxy"
            and finding["metadata"]["stem_specific_claim"] is False
            for finding in report["findings"]
        )
        assert not any("kick_bass" in finding["rule_id"] for finding in report["findings"])
    finally:
        runtime.close()


def test_mix_review_level_4_requires_confirmed_stem_roles_for_stem_findings(tmp_path) -> None:
    artifacts = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        artifact_store=artifacts,
        job_store_path=tmp_path / "jobs.sqlite3",
    )
    bridge = FakeBridge()
    runtime.get_static_project_snapshot(bridge)
    master = _publish_master(artifacts)
    kick = _publish_master(
        artifacts,
        source_hash="1" * 64,
        summary={
            "duration_seconds": 8.0,
            "peak_dbfs": -4.0,
            "time_alignment_checked": True,
            "kick_bass_overlap": 0.7,
        },
    )
    bass = _publish_master(
        artifacts,
        source_hash="2" * 64,
        summary={
            "duration_seconds": 8.0,
            "peak_dbfs": -11.0,
            "time_alignment_checked": True,
            "kick_bass_overlap": 0.7,
        },
    )
    runtime.attach_audio_artifact(
        master.artifact_id,
        evidence_kind="rendered_master",
        workflow_targets=("mix_review",),
    )
    runtime.attach_audio_artifact(
        kick.artifact_id,
        evidence_kind="stem",
        stem_role="kick",
        workflow_targets=("mix_review",),
    )
    runtime.attach_audio_artifact(
        bass.artifact_id,
        evidence_kind="stem",
        stem_role="bass",
        workflow_targets=("mix_review",),
    )
    try:
        unconfirmed = run_workflow(runtime, "mix_review", bridge=bridge, inputs={"level": 4})
        assert "rendered_stem_features" in unconfirmed["coverage"]["missing"]
        assert not any("kick_bass_overlap" in row["rule_id"] for row in unconfirmed["findings"])

        runtime.attach_audio_artifact(
            kick.artifact_id,
            evidence_kind="stem",
            stem_role="kick",
            workflow_targets=("mix_review",),
            confirmed_by_user=True,
        )
        runtime.attach_audio_artifact(
            bass.artifact_id,
            evidence_kind="stem",
            stem_role="bass",
            workflow_targets=("mix_review",),
            confirmed_by_user=True,
        )
        confirmed = run_workflow(runtime, "mix_review", bridge=bridge, inputs={"level": 4})
        assert "rendered_stem_features" not in confirmed["coverage"]["missing"]
        assert any(
            row["rule_id"] == "mix_review.kick_bass_overlap"
            and row["metadata"]["finding_state"] == "stem_audio_confirmed"
            for row in confirmed["findings"]
        )
    finally:
        runtime.close()
