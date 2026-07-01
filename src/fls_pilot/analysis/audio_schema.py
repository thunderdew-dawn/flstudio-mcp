"""Versioned contracts for offline audio feature artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

AUDIO_FEATURES_CONTRACT_VERSION = "fls-pilot.audio-features.v1"
AUDIO_ARTIFACT_CONTRACT_VERSION = "fls-pilot.audio-artifact.v1"
AUDIO_FEATURES_PLACEHOLDER_STATUS = "pending_external_analyzer"
AUDIO_FEATURE_PLACEHOLDER_KEYS = (
    "peak_dbfs",
    "true_peak_dbfs",
    "integrated_lufs",
    "short_term_lufs_max",
    "rms_dbfs",
    "crest_factor_db",
    "clipping_count",
    "stereo_correlation",
    "mono_loss_db",
    "band_energy",
    "low_band_side_ratio",
    "harshness_score",
    "drop_break_energy_ratio",
)


@dataclass(frozen=True)
class AudioArtifactManifest:
    artifact_id: str
    created_at: str
    source_sha256: str
    source_size_bytes: int
    source_basename: str
    extractor_version: str
    configuration_fingerprint: str
    feature_file: str
    feature_sha256: str
    availability: str = "complete"
    warnings: tuple[str, ...] = ()
    contract_version: str = AUDIO_ARTIFACT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != AUDIO_ARTIFACT_CONTRACT_VERSION:
            raise ValueError(f"unsupported audio artifact contract: {self.contract_version!r}")
        if self.availability not in {"complete", "partial", "unavailable"}:
            raise ValueError(f"invalid artifact availability: {self.availability!r}")
        object.__setattr__(self, "source_size_bytes", max(0, int(self.source_size_bytes)))
        object.__setattr__(self, "warnings", tuple(str(row) for row in self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "artifact_id": self.artifact_id,
            "created_at": self.created_at,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "source_basename": self.source_basename,
            "extractor_version": self.extractor_version,
            "configuration_fingerprint": self.configuration_fingerprint,
            "feature_file": self.feature_file,
            "feature_sha256": self.feature_sha256,
            "availability": self.availability,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> AudioArtifactManifest:
        return cls(
            contract_version=str(value.get("contract_version") or ""),
            artifact_id=str(value.get("artifact_id") or ""),
            created_at=str(value.get("created_at") or ""),
            source_sha256=str(value.get("source_sha256") or ""),
            source_size_bytes=int(value.get("source_size_bytes") or 0),
            source_basename=str(value.get("source_basename") or ""),
            extractor_version=str(value.get("extractor_version") or ""),
            configuration_fingerprint=str(
                value.get("configuration_fingerprint") or ""
            ),
            feature_file=str(value.get("feature_file") or ""),
            feature_sha256=str(value.get("feature_sha256") or ""),
            availability=str(value.get("availability") or "unavailable"),
            warnings=tuple(value.get("warnings") or ()),
        )


def validate_audio_features(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    version = payload.get("contract_version")
    if version != AUDIO_FEATURES_CONTRACT_VERSION:
        raise ValueError(
            f"unsupported audio features contract: {version!r}; "
            f"expected {AUDIO_FEATURES_CONTRACT_VERSION!r}"
        )
    return payload


def audio_features_placeholder(
    *,
    source_kind: str,
    stem_role: str | None = None,
    status: str = AUDIO_FEATURES_PLACEHOLDER_STATUS,
) -> dict[str, Any]:
    """Return an audio-features v1 placeholder with no computed DSP values."""
    return {
        "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
        "artifact_type": "audio_features.v1",
        "source_kind": str(source_kind or "rendered_master"),
        "stem_role": str(stem_role) if stem_role else None,
        "status": str(status or AUDIO_FEATURES_PLACEHOLDER_STATUS),
        "features": {key: None for key in AUDIO_FEATURE_PLACEHOLDER_KEYS},
    }
