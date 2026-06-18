from __future__ import annotations

import os
import time

import pytest

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime import artifacts
from fls_pilot.runtime.artifacts import AudioArtifactStore


def _publish(store: AudioArtifactStore):
    return store.publish(
        features={
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "summary": {"peak_dbfs": -1.0},
        },
        source_sha256="b" * 64,
        source_size_bytes=10,
        source_basename="mix.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )


def test_incomplete_temporary_files_are_ignored_and_cleaned_by_age(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path)
    manifest = _publish(store)
    temporary = tmp_path / manifest.artifact_id / ".features.json.tmp-abandoned"
    temporary.write_text('{"incomplete":', encoding="utf-8")
    old = time.time() - 7200
    os.utime(temporary, (old, old))

    assert store.read_features(manifest.artifact_id)["summary"]["peak_dbfs"] == -1.0
    assert store.cleanup_abandoned_temporary_files(minimum_age_seconds=3600) == 1
    assert not temporary.exists()


def test_failed_atomic_promotion_preserves_the_last_complete_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    store = AudioArtifactStore(tmp_path)
    manifest = _publish(store)
    original = store.read_features(manifest.artifact_id)
    real_replace = artifacts.os.replace

    def fail_feature_replace(source, destination):
        if str(destination).endswith("features.json"):
            raise OSError("simulated power loss")
        return real_replace(source, destination)

    monkeypatch.setattr(artifacts.os, "replace", fail_feature_replace)
    with pytest.raises(OSError, match="power loss"):
        store.publish(
            features={
                "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
                "summary": {"peak_dbfs": -9.0},
            },
            source_sha256="b" * 64,
            source_size_bytes=10,
            source_basename="mix.wav",
            extractor_version="core-1",
            configuration_fingerprint="config-1",
        )

    assert store.read_features(manifest.artifact_id) == original
    assert not list(tmp_path.rglob(".*.tmp-*"))
