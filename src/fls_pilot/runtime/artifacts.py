"""Atomic content-addressed storage for offline audio feature artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..analysis.audio_schema import AudioArtifactManifest, validate_audio_features
from .contracts import utc_now_iso

DEFAULT_AUDIO_ARTIFACT_ROOT = Path.home() / ".fls-pilot" / "audio-analysis" / "artifacts"


@dataclass(frozen=True)
class ArtifactRetentionPolicy:
    maximum_artifacts: int = 500
    maximum_bytes: int = 1024 * 1024 * 1024
    target_max_age_days: int = 30


class AudioArtifactStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or DEFAULT_AUDIO_ARTIFACT_ROOT).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def artifact_id(
        *,
        source_sha256: str,
        extractor_version: str,
        configuration_fingerprint: str,
    ) -> str:
        digest = hashlib.sha256(
            "\0".join(
                (source_sha256, extractor_version, configuration_fingerprint)
            ).encode("utf-8")
        ).hexdigest()
        return f"audio_{digest}"

    def publish(
        self,
        *,
        features: Mapping[str, Any],
        source_sha256: str,
        source_size_bytes: int,
        source_basename: str,
        extractor_version: str,
        configuration_fingerprint: str,
        availability: str = "complete",
        warnings: Iterable[str] = (),
    ) -> AudioArtifactManifest:
        feature_payload = validate_audio_features(features)
        artifact_id = self.artifact_id(
            source_sha256=source_sha256,
            extractor_version=extractor_version,
            configuration_fingerprint=configuration_fingerprint,
        )
        artifact_dir = self.root / artifact_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        feature_path = artifact_dir / "features.json"
        manifest_path = artifact_dir / "manifest.json"
        feature_bytes = _json_bytes(feature_payload)
        feature_sha256 = hashlib.sha256(feature_bytes).hexdigest()
        manifest = AudioArtifactManifest(
            artifact_id=artifact_id,
            created_at=utc_now_iso(),
            source_sha256=source_sha256,
            source_size_bytes=source_size_bytes,
            source_basename=Path(source_basename).name,
            extractor_version=extractor_version,
            configuration_fingerprint=configuration_fingerprint,
            feature_file=feature_path.name,
            feature_sha256=feature_sha256,
            availability=availability,
            warnings=tuple(warnings),
        )

        _atomic_write(feature_path, feature_bytes)
        if self._read_json(feature_path) != feature_payload:
            raise ValueError("audio feature artifact verification failed")
        if _sha256_file(feature_path) != feature_sha256:
            raise ValueError("audio feature artifact checksum verification failed")
        _atomic_write(manifest_path, _json_bytes(manifest.to_dict()))
        restored = self.read_manifest(artifact_id)
        if restored != manifest:
            raise ValueError("audio artifact manifest verification failed")
        _fsync_directory(artifact_dir)
        _fsync_directory(self.root)
        return manifest

    def read_manifest(self, artifact_id: str) -> AudioArtifactManifest:
        path = self._artifact_dir(artifact_id) / "manifest.json"
        return AudioArtifactManifest.from_dict(self._read_json(path))

    def read_features(self, artifact_id: str) -> dict[str, Any]:
        manifest = self.read_manifest(artifact_id)
        path = self._artifact_dir(artifact_id) / manifest.feature_file
        if _sha256_file(path) != manifest.feature_sha256:
            raise ValueError(f"audio artifact checksum mismatch: {artifact_id}")
        return validate_audio_features(self._read_json(path))

    def result_ref(self, artifact_id: str) -> dict[str, Any]:
        manifest = self.read_manifest(artifact_id)
        return {
            "kind": "audio_features",
            "artifact_id": manifest.artifact_id,
            "contract_version": manifest.contract_version,
            "availability": manifest.availability,
            "source_basename": manifest.source_basename,
            "source_sha256_prefix": manifest.source_sha256[:12],
            "warnings": list(manifest.warnings),
        }

    def validate_result_ref(self, result_ref: Mapping[str, Any]) -> bool:
        if result_ref.get("kind") != "audio_features":
            return False
        try:
            artifact_id = str(result_ref["artifact_id"])
            self.read_features(artifact_id)
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return False
        return True

    def list_manifests(self) -> list[AudioArtifactManifest]:
        manifests: list[AudioArtifactManifest] = []
        for path in sorted(self.root.glob("audio_*/manifest.json")):
            try:
                manifests.append(AudioArtifactManifest.from_dict(self._read_json(path)))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return manifests

    def cleanup_abandoned_temporary_files(self, *, minimum_age_seconds: int = 3600) -> int:
        cutoff = time.time() - max(0, int(minimum_age_seconds))
        removed = 0
        for path in self.root.rglob(".*.tmp-*"):
            try:
                if path.stat().st_mtime <= cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                continue
        return removed

    def enforce_retention(
        self,
        policy: ArtifactRetentionPolicy | None = None,
        *,
        protected_artifact_ids: Iterable[str] = (),
        now: datetime | None = None,
    ) -> list[str]:
        policy = policy or ArtifactRetentionPolicy()
        protected = {str(row) for row in protected_artifact_ids}
        now = now or datetime.now(timezone.utc)
        eligible_before = now - timedelta(days=max(0, policy.target_max_age_days))
        entries: list[tuple[AudioArtifactManifest, Path, int, float]] = []
        for manifest in self.list_manifests():
            directory = self._artifact_dir(manifest.artifact_id)
            size = sum(
                path.stat().st_size for path in directory.rglob("*") if path.is_file()
            )
            access_time = max(
                (
                    path.stat().st_atime
                    for path in directory.rglob("*")
                    if path.is_file()
                ),
                default=directory.stat().st_atime,
            )
            entries.append((manifest, directory, size, access_time))

        total_count = len(entries)
        total_bytes = sum(row[2] for row in entries)
        if (
            total_count <= max(0, policy.maximum_artifacts)
            and total_bytes <= max(0, policy.maximum_bytes)
        ):
            return []

        eligible = [
            row
            for row in entries
            if row[0].artifact_id not in protected
            and _parse_time(row[0].created_at) <= eligible_before
        ]
        eligible.sort(key=lambda row: row[3])
        removed: list[str] = []
        for manifest, directory, size, _access_time in eligible:
            if (
                total_count <= max(0, policy.maximum_artifacts)
                and total_bytes <= max(0, policy.maximum_bytes)
            ):
                break
            shutil.rmtree(directory)
            removed.append(manifest.artifact_id)
            total_count -= 1
            total_bytes -= size
        return removed

    def _artifact_dir(self, artifact_id: str) -> Path:
        normalized = str(artifact_id)
        if not normalized.startswith("audio_") or "/" in normalized or "\\" in normalized:
            raise ValueError(f"invalid audio artifact id: {artifact_id!r}")
        return self.root / normalized

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"artifact JSON must be an object: {path}")
        return value


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
