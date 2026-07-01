"""Mix Review level, capture, and audio-evidence contracts.

This module is intentionally pure data normalization. It does not touch FL
Studio and it does not perform audio analysis.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class MixReviewLevel(IntEnum):
    STATIC = 1
    LIVE_WATCH = 2
    RENDERED_MASTER = 3
    RENDERED_STEMS = 4


CAPTURE_MIN_SECONDS = 8
CAPTURE_MAX_SECONDS = 60
CAPTURE_DEFAULT_SECONDS = 16
PLAYBACK_MODES = {"user_starts", "gui_starts", "unknown"}

LEVEL_LABELS = {
    MixReviewLevel.STATIC: "Level 1 - Static Mix Review",
    MixReviewLevel.LIVE_WATCH: "Level 2 - Live Peak Watch",
    MixReviewLevel.RENDERED_MASTER: "Level 3 - Rendered Master Evidence",
    MixReviewLevel.RENDERED_STEMS: "Level 4 - Stem/Bus Evidence",
}

LEVEL_ANALYSIS_MODES = {
    MixReviewLevel.STATIC: "static_snapshot",
    MixReviewLevel.LIVE_WATCH: "watch_window",
    MixReviewLevel.RENDERED_MASTER: "hybrid",
    MixReviewLevel.RENDERED_STEMS: "hybrid",
}

RENDERED_MASTER_EXPECTED_CHECKS = (
    "Integrated LUFS",
    "Short-Term Loudness Max",
    "True Peak",
    "Clipping Count",
    "Clipping Plateau Detection",
    "RMS",
    "Crest Factor",
    "Stereo Correlation",
    "Mono Loss",
    "Band Energy",
    "Sub/Low-Band Side Energy",
    "Harshness Band",
    "Drop-vs-Break Energy",
)

RENDERED_STEM_EXPECTED_CHECKS = (
    "Kick/Bass Masking",
    "Kick Transient vs Bass Sustain",
    "Low-End Phase",
    "Stem Headroom",
    "Bus Balance",
    "Sub-Side Energy per Stem",
    "FX/Reverb Low-End Leakage",
    "Drop/Break Bus Energy Balance",
    "Mono Compatibility per Low-End Stem",
)

STEM_ROLES = (
    "kick",
    "bass",
    "sub",
    "drums_bus",
    "percussion_bus",
    "synth_bus",
    "lead_bus",
    "fx_bus",
    "vocal_bus",
    "premaster",
    "master",
    "other",
)

EVIDENCE_STATUSES = {
    "missing",
    "pending",
    "unavailable",
    "external_analyzer_not_installed",
    "available",
    "pending_external_analyzer",
}


@dataclass(frozen=True)
class MixReviewCaptureOptions:
    loop_seconds: int = CAPTURE_DEFAULT_SECONDS
    playback_mode: str = "user_starts"
    marker_id: str | None = None
    marker_name: str | None = None
    requested_loudest_section: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "loop_seconds",
            max(CAPTURE_MIN_SECONDS, min(CAPTURE_MAX_SECONDS, _as_int(self.loop_seconds))),
        )
        playback = str(self.playback_mode or "unknown").strip().lower()
        if playback not in PLAYBACK_MODES:
            playback = "unknown"
        object.__setattr__(self, "playback_mode", playback)
        object.__setattr__(self, "marker_id", _optional_text(self.marker_id))
        object.__setattr__(self, "marker_name", _optional_text(self.marker_name))
        object.__setattr__(self, "requested_loudest_section", bool(self.requested_loudest_section))

    def to_dict(self) -> dict[str, Any]:
        return {
            "loop_seconds": self.loop_seconds,
            "playback_mode": self.playback_mode,
            "marker_id": self.marker_id,
            "marker_name": self.marker_name,
            "requested_loudest_section": self.requested_loudest_section,
        }


@dataclass(frozen=True)
class MixReviewAudioEvidenceRequest:
    source_kind: str
    status: str = "missing"
    path: str | None = None
    job_id: str | None = None
    artifact_id: str | None = None
    stem_role: str | None = None
    features: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        source_kind = str(self.source_kind or "").strip().lower()
        if source_kind in {"master", "rendered_audio", "rendered_master_audio"}:
            source_kind = "rendered_master"
        if source_kind in {"stem", "rendered_stem", "rendered_stems"}:
            source_kind = "rendered_stem"
        if source_kind not in {"rendered_master", "rendered_stem"}:
            source_kind = "rendered_master"
        object.__setattr__(self, "source_kind", source_kind)

        status = str(self.status or "missing").strip().lower()
        if status not in EVIDENCE_STATUSES:
            status = "missing"
        object.__setattr__(self, "status", status)

        role = _optional_text(self.stem_role)
        if role and role not in STEM_ROLES:
            role = "other"
        object.__setattr__(self, "stem_role", role)
        object.__setattr__(self, "path", _optional_text(self.path))
        object.__setattr__(self, "job_id", _optional_text(self.job_id))
        object.__setattr__(self, "artifact_id", _optional_text(self.artifact_id))
        object.__setattr__(self, "features", dict(self.features or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "status": self.status,
            "path": self.path,
            "job_id": self.job_id,
            "artifact_id": self.artifact_id,
            "stem_role": self.stem_role,
            "features": dict(self.features or {}),
        }


@dataclass(frozen=True)
class MixReviewOptions:
    level: MixReviewLevel = MixReviewLevel.STATIC
    genre_profile: str | None = None
    capture: MixReviewCaptureOptions = field(default_factory=MixReviewCaptureOptions)
    audio_evidence: tuple[MixReviewAudioEvidenceRequest, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", normalize_mix_review_level(self.level))
        object.__setattr__(self, "genre_profile", _optional_text(self.genre_profile))
        if not isinstance(self.capture, MixReviewCaptureOptions):
            object.__setattr__(self, "capture", _normalize_capture(self.capture))
        object.__setattr__(
            self,
            "audio_evidence",
            tuple(
                row
                if isinstance(row, MixReviewAudioEvidenceRequest)
                else _normalize_audio_evidence_row(row)
                for row in self.audio_evidence
            ),
        )

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS[self.level]

    @property
    def analysis_mode(self) -> str:
        return LEVEL_ANALYSIS_MODES[self.level]

    def expected_checks(self) -> list[str]:
        checks: list[str] = []
        if self.level >= MixReviewLevel.RENDERED_MASTER:
            checks.extend(RENDERED_MASTER_EXPECTED_CHECKS)
        if self.level >= MixReviewLevel.RENDERED_STEMS:
            checks.extend(RENDERED_STEM_EXPECTED_CHECKS)
        return checks

    def requested_evidence_summary(self) -> dict[str, Any]:
        master = next(
            (row for row in self.audio_evidence if row.source_kind == "rendered_master"),
            None,
        )
        stems = [row for row in self.audio_evidence if row.source_kind == "rendered_stem"]
        return {
            "rendered_master": master.to_dict()
            if master
            else {
                "source_kind": "rendered_master",
                "status": "missing",
                "features": {},
            },
            "rendered_stems": [row.to_dict() for row in stems],
            "rendered_stem_status": "available"
            if any(row.status == "available" for row in stems)
            else "missing",
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": int(self.level),
            "level_label": self.level_label,
            "genre_profile": self.genre_profile,
            "capture": self.capture.to_dict(),
            "audio_evidence": [row.to_dict() for row in self.audio_evidence],
        }


def normalize_mix_review_options(raw: Any = None, **overrides: Any) -> MixReviewOptions:
    if isinstance(raw, MixReviewOptions):
        base = raw.to_dict()
    elif raw is None:
        base = {}
    elif isinstance(raw, Mapping):
        base = dict(raw)
    elif isinstance(raw, (str, int)):
        base = {"level": raw}
    else:
        base = {}
    if overrides:
        base.update({key: value for key, value in overrides.items() if value is not None})

    capture_raw = (
        dict(base.get("capture") or {}) if isinstance(base.get("capture"), Mapping) else {}
    )
    for key in (
        "loop_seconds",
        "playback_mode",
        "marker_id",
        "marker_name",
        "requested_loudest_section",
    ):
        if key in base and key not in capture_raw:
            capture_raw[key] = base[key]

    evidence = base.get("audio_evidence") or ()
    if isinstance(evidence, Mapping):
        evidence = (evidence,)
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        evidence = ()

    return MixReviewOptions(
        level=normalize_mix_review_level(base.get("level", MixReviewLevel.STATIC)),
        genre_profile=base.get("genre_profile"),
        capture=_normalize_capture(capture_raw),
        audio_evidence=tuple(_normalize_audio_evidence_row(row) for row in evidence),
    )


def normalize_mix_review_level(value: Any) -> MixReviewLevel:
    if isinstance(value, MixReviewLevel):
        return value
    text = str(value or "").strip().lower()
    aliases = {
        "static": 1,
        "level_1": 1,
        "level1": 1,
        "live": 2,
        "watch": 2,
        "live_watch": 2,
        "level_2": 2,
        "level2": 2,
        "rendered_master": 3,
        "master": 3,
        "level_3": 3,
        "level3": 3,
        "stems": 4,
        "rendered_stems": 4,
        "stem_bus": 4,
        "level_4": 4,
        "level4": 4,
    }
    try:
        numeric = aliases.get(text, int(text))
    except (TypeError, ValueError):
        numeric = 1
    try:
        return MixReviewLevel(numeric)
    except ValueError:
        return MixReviewLevel.STATIC


def _normalize_capture(raw: Any) -> MixReviewCaptureOptions:
    if isinstance(raw, MixReviewCaptureOptions):
        return raw
    data = dict(raw or {}) if isinstance(raw, Mapping) else {}
    return MixReviewCaptureOptions(
        loop_seconds=data.get("loop_seconds", CAPTURE_DEFAULT_SECONDS),
        playback_mode=data.get("playback_mode", "user_starts"),
        marker_id=data.get("marker_id"),
        marker_name=data.get("marker_name"),
        requested_loudest_section=data.get("requested_loudest_section", True),
    )


def _normalize_audio_evidence_row(raw: Any) -> MixReviewAudioEvidenceRequest:
    if isinstance(raw, MixReviewAudioEvidenceRequest):
        return raw
    data = dict(raw or {}) if isinstance(raw, Mapping) else {}
    return MixReviewAudioEvidenceRequest(
        source_kind=data.get("source_kind")
        or data.get("kind")
        or data.get("evidence_kind")
        or "rendered_master",
        status=data.get("status", "missing"),
        path=data.get("path"),
        job_id=data.get("job_id"),
        artifact_id=data.get("artifact_id"),
        stem_role=data.get("stem_role") or data.get("role"),
        features=data.get("features"),
    )


def _as_int(value: Any, default: int = CAPTURE_DEFAULT_SECONDS) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
