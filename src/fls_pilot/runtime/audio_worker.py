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
from ..profile import profile

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
        with profile("audio.features.validate_source", source=str(source)):
            _validate_audio_source_identity(source, payload)
        context.set_progress(0.05)
        with profile(
            "audio.features.hash",
            source=str(source),
            extractor=FEATURE_EXTRACTOR_VERSION,
        ):
            actual_sha256 = sha256_file(source, cancellation_check=context.raise_if_cancelled)
        context.set_progress(0.15)
        with profile("audio.features.extract", extractor=FEATURE_EXTRACTOR_VERSION):
            features = self.extractor.extract(
                source,
                cancellation_check=context.raise_if_cancelled,
            )
        context.set_progress(0.85)
        configuration_fingerprint = str(
            payload.get("configuration_fingerprint")
            or feature_configuration_fingerprint(self.extractor.config)
        )
        with profile("audio.features.publish", source=str(source)):
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
    request = build_audio_job_request(path, extractor_config=extractor_config)
    job = runtime.jobs.submit(
        kind=AUDIO_FEATURE_JOB_KIND,
        input_payload=request["input"],
        input_summary=request["input_summary"],
        idempotency_key=request["idempotency_key"],
        idempotent=True,
        max_retries=2,
    )
    return job.to_dict()


def build_audio_job_request(
    path: str | Path,
    *,
    extractor_config: FeatureExtractorConfig | None = None,
) -> dict[str, Any]:
    source = validate_audio_source(path)
    stat = source.stat()
    config = extractor_config or FeatureExtractorConfig()
    configuration_fingerprint = feature_configuration_fingerprint(config)
    idempotency_key = ":".join(
        (
            AUDIO_FEATURE_JOB_KIND,
            str(source),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            FEATURE_EXTRACTOR_VERSION,
            configuration_fingerprint,
        )
    )
    return {
        "kind": AUDIO_FEATURE_JOB_KIND,
        "input": {
            "path": str(source),
            "source_size_bytes": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "configuration_fingerprint": configuration_fingerprint,
        },
        "input_summary": {
            "source_basename": source.name,
            "source_size_bytes": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
        },
        "idempotency_key": idempotency_key,
    }


def validate_audio_source(path: Any) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise ValueError("audio source path is required")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"audio source file not found: {source}")
    return source


def _validate_audio_source_identity(
    source: Path,
    payload: dict[str, Any],
) -> None:
    expected_size = _safe_int(payload.get("source_size_bytes"))
    expected_mtime_ns = _safe_int(payload.get("source_mtime_ns"))
    if expected_size is None and expected_mtime_ns is None:
        return
    stat = source.stat()
    if expected_size is not None and stat.st_size != expected_size:
        raise ValueError("audio source changed after job submission (size)")
    if expected_mtime_ns is not None and stat.st_mtime_ns != expected_mtime_ns:
        raise ValueError("audio source changed after job submission (mtime)")


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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
