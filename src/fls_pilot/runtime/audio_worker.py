"""Runtime job handler for deterministic offline audio feature extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..analysis.audio_features import (
    FEATURE_EXTRACTOR_VERSION,
    FeatureExtractor,
    FeatureExtractorConfig,
)
from .artifacts import AudioArtifactStore
from .core import RuntimeCore
from .jobs import JobContext

AUDIO_FEATURE_JOB_KIND = "audio.features"


class AudioAnalysisWorker:
    def __init__(
        self,
        artifact_store: AudioArtifactStore,
        *,
        extractor: FeatureExtractor | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.extractor = extractor or FeatureExtractor()

    def register(self, runtime: RuntimeCore) -> None:
        runtime.register_job_handler(AUDIO_FEATURE_JOB_KIND, self.handle)

    def handle(self, payload: dict[str, Any], context: JobContext) -> dict[str, Any]:
        source = validate_audio_source(payload.get("path"))
        expected_sha256 = str(payload.get("source_sha256") or "")
        context.set_progress(0.05)
        actual_sha256 = sha256_file(source, cancellation_check=context.raise_if_cancelled)
        if expected_sha256 and actual_sha256 != expected_sha256:
            raise ValueError("source audio changed after job submission")
        context.set_progress(0.15)
        features = self.extractor.extract(
            source,
            cancellation_check=context.raise_if_cancelled,
        )
        context.set_progress(0.85)
        configuration_fingerprint = str(
            payload.get("configuration_fingerprint")
            or feature_configuration_fingerprint(self.extractor.config)
        )
        manifest = self.artifact_store.publish(
            features=features,
            source_sha256=actual_sha256,
            source_size_bytes=source.stat().st_size,
            source_basename=source.name,
            extractor_version=FEATURE_EXTRACTOR_VERSION,
            configuration_fingerprint=configuration_fingerprint,
            warnings=tuple(features.get("warnings") or ()),
        )
        context.set_progress(0.98)
        result = self.artifact_store.result_ref(manifest.artifact_id)
        result["summary"] = compact_feature_summary(features)
        return result


def submit_audio_feature_job(
    runtime: RuntimeCore,
    path: str | Path,
    *,
    extractor_config: FeatureExtractorConfig | None = None,
) -> dict[str, Any]:
    source = validate_audio_source(path)
    source_sha256 = sha256_file(source)
    config = extractor_config or FeatureExtractorConfig()
    configuration_fingerprint = feature_configuration_fingerprint(config)
    idempotency_key = ":".join(
        (
            AUDIO_FEATURE_JOB_KIND,
            source_sha256,
            FEATURE_EXTRACTOR_VERSION,
            configuration_fingerprint,
        )
    )
    job = runtime.jobs.submit(
        kind=AUDIO_FEATURE_JOB_KIND,
        input_payload={
            "path": str(source),
            "source_sha256": source_sha256,
            "configuration_fingerprint": configuration_fingerprint,
        },
        input_summary={
            "source_basename": source.name,
            "source_size_bytes": source.stat().st_size,
            "source_sha256_prefix": source_sha256[:12],
        },
        idempotency_key=idempotency_key,
        idempotent=True,
        max_retries=2,
    )
    return job.to_dict()


def validate_audio_source(path: Any) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("audio source path is required")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"audio source file not found: {source}")
    return source


def sha256_file(
    path: str | Path,
    *,
    cancellation_check=None,
) -> str:
    source = Path(path)
    check = cancellation_check or (lambda: None)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            check()
            digest.update(chunk)
    check()
    return digest.hexdigest()


def feature_configuration_fingerprint(config: FeatureExtractorConfig) -> str:
    payload = json.dumps(config.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_feature_summary(features: dict[str, Any]) -> dict[str, Any]:
    summary = dict(features.get("summary") or {})
    return {
        key: summary.get(key)
        for key in (
            "duration_seconds",
            "sample_rate",
            "channel_count",
            "peak_dbfs",
            "rms_dbfs",
            "integrated_lufs",
            "crest_factor_db",
            "low_end_energy_ratio",
            "stereo_correlation_proxy",
            "stereo_width_proxy",
            "low_band_stereo_proxy",
        )
    }
