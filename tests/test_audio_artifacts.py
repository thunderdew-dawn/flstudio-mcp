from __future__ import annotations

import hashlib

from fls_pilot.analysis.audio_schema import AUDIO_FEATURES_CONTRACT_VERSION
from fls_pilot.runtime.artifacts import AudioArtifactStore


def _features(value: float = -3.0) -> dict:
    return {
        "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
        "summary": {"peak_dbfs": value},
        "frames": [0.1, 0.2],
    }


def test_audio_artifact_publish_is_content_addressed_and_validated(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path)
    source = b"source audio remains outside the store"
    source_hash = hashlib.sha256(source).hexdigest()

    manifest = store.publish(
        features=_features(),
        source_sha256=source_hash,
        source_size_bytes=len(source),
        source_basename="/private/path/Mix.wav",
        extractor_version="core-1",
        configuration_fingerprint="config-1",
    )

    assert manifest.source_basename == "Mix.wav"
    assert store.read_manifest(manifest.artifact_id) == manifest
    assert store.read_features(manifest.artifact_id) == _features()
    assert store.validate_result_ref(store.result_ref(manifest.artifact_id))
    assert not list(tmp_path.rglob(".*.tmp-*"))


def test_same_content_and_configuration_reuses_artifact_identity(tmp_path) -> None:
    store = AudioArtifactStore(tmp_path)
    arguments = {
        "features": _features(),
        "source_sha256": "a" * 64,
        "source_size_bytes": 100,
        "source_basename": "mix.wav",
        "extractor_version": "core-1",
        "configuration_fingerprint": "config-1",
    }

    first = store.publish(**arguments)
    second = store.publish(**arguments)

    assert first.artifact_id == second.artifact_id
    assert len(store.list_manifests()) == 1
