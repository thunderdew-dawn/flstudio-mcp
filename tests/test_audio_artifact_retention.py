from __future__ import annotations

import time
from datetime import datetime, timezone

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import ArtifactRetentionPolicy, AudioArtifactStore


def _publish(store: AudioArtifactStore, source: str):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {"source": source},
        },
        source_sha256=source * 64,
        source_size_bytes=10,
        source_basename=f"{source}.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )


def test_retention_uses_lru_and_protects_running_job_artifacts(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path)
    first = _publish(store, "a")
    time.sleep(0.01)
    second = _publish(store, "b")
    time.sleep(0.01)
    third = _publish(store, "c")

    removed = store.enforce_retention(
        ArtifactRetentionPolicy(
            maximum_artifacts=1,
            maximum_bytes=10**9,
            target_max_age_days=0,
        ),
        protected_artifact_ids=(first.artifact_id,),
        now=datetime.now(timezone.utc),
    )

    assert first.artifact_id not in removed
    assert removed == [second.artifact_id, third.artifact_id]
    assert store.read_manifest(first.artifact_id).artifact_id == first.artifact_id


def test_retention_does_not_delete_artifacts_before_age_eligibility(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path)
    _publish(store, "d")
    _publish(store, "e")

    removed = store.enforce_retention(
        ArtifactRetentionPolicy(
            maximum_artifacts=1,
            maximum_bytes=10**9,
            target_max_age_days=30,
        )
    )

    assert removed == []
    assert len(store.list_manifests()) == 2
