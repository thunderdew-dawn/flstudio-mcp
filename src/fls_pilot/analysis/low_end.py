"""Low-end evidence levels, role handling, and scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scoring import clamp_score


@dataclass(frozen=True)
class LowEndEvidenceLevel:
    level: int
    key: str
    label: str
    can_create_audio_claims: bool
    can_create_stem_specific_claims: bool
    status: str = "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "key": self.key,
            "label": self.label,
            "can_create_audio_claims": self.can_create_audio_claims,
            "can_create_stem_specific_claims": self.can_create_stem_specific_claims,
            "status": self.status,
        }


LOW_END_EVIDENCE_LEVELS = {
    1: LowEndEvidenceLevel(
        1,
        "static_metadata",
        "Static metadata / project structure",
        False,
        False,
    ),
    2: LowEndEvidenceLevel(
        2,
        "live_playback_data",
        "Live playback data",
        True,
        False,
    ),
    3: LowEndEvidenceLevel(
        3,
        "rendered_master_audio",
        "Rendered master audio",
        True,
        False,
    ),
    4: LowEndEvidenceLevel(
        4,
        "role_confirmed_bus_or_stem_evidence",
        "Role-confirmed bus/stem evidence",
        True,
        True,
    ),
    5: LowEndEvidenceLevel(
        5,
        "deeper_batch_or_multi_source_evidence",
        "Deeper batch / multi-source evidence",
        True,
        True,
        status="planned",
    ),
}

LOW_END_GENRE_PROFILES = {
    "default": {
        "id": "default",
        "label": "Default",
        "low_end_ratio_medium": 0.40,
        "low_end_ratio_high": 0.55,
        "mono_loss_medium_db": -3.0,
        "mono_loss_high_db": -6.0,
    },
    "psytrance": {
        "id": "psytrance",
        "label": "Psytrance",
        "low_end_ratio_medium": 0.34,
        "low_end_ratio_high": 0.48,
        "mono_loss_medium_db": -2.0,
        "mono_loss_high_db": -5.0,
    },
}

LOW_END_FUTURE_GENRE_PROFILES = ("techno", "drum_and_bass", "hip_hop", "cinematic")

LOW_END_ROLE_ALIASES = {
    "kick": "kick",
    "sub": "sub",
    "808": "sub",
    "bass": "bass",
    "boom": "bass",
    "drums": "drums",
    "drum": "drums",
    "low_end_bus": "low_end_bus",
    "low-end bus": "low_end_bus",
    "music": "music_bus",
    "music_bus": "music_bus",
}
LOW_END_STEM_ROLES = frozenset(
    {"kick", "sub", "bass", "drums", "low_end_bus", "music_bus", "other"}
)

FINDING_STATE_VALUES = frozenset({"unconfirmed", "accepted", "rejected", "ignored"})


def low_end_evidence_level(level: int) -> LowEndEvidenceLevel:
    return LOW_END_EVIDENCE_LEVELS.get(int(level), LOW_END_EVIDENCE_LEVELS[1])


def low_end_evidence_metadata(level: int) -> dict[str, Any]:
    current = low_end_evidence_level(level)
    return {
        "evidence_level": current.level,
        "evidence_level_key": current.key,
        "evidence_level_label": current.key,
        "evidence_level_display_label": current.label,
        "evidence_levels": {
            str(key): value.to_dict() for key, value in LOW_END_EVIDENCE_LEVELS.items()
        },
        "automatic_fl_render": False,
    }


def normalize_low_end_genre_profile(value: Any) -> str:
    profile = str(value or "default").strip().lower().replace("-", "_")
    return profile if profile in LOW_END_GENRE_PROFILES else "default"


def normalize_stem_role(value: Any) -> str | None:
    role = str(value or "").strip().lower().replace("-", "_")
    if not role:
        return None
    role = LOW_END_ROLE_ALIASES.get(role, role)
    return role if role in LOW_END_STEM_ROLES else None


def role_confirmation_state(*, has_tracks: bool, has_confirmed_stems: bool) -> str:
    if has_confirmed_stems:
        return "role_confirmed"
    if has_tracks:
        return "name_based_unconfirmed"
    return "none"


def finding_state(value: Any, *, default: str = "accepted") -> str:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in FINDING_STATE_VALUES else default


def weighted_low_end_risk(findings: list[Any] | tuple[Any, ...]) -> int:
    weights = {
        "critical": 45,
        "high": 32,
        "error": 32,
        "medium": 16,
        "warning": 12,
        "low": 6,
        "info": 2,
        "ok": 0,
    }
    total = 0
    for row in findings:
        if hasattr(row, "severity"):
            severity = row.severity
            metadata = row.metadata or {}
            explicit_score = row.risk_score
        elif isinstance(row, dict):
            severity = row.get("severity")
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            explicit_score = row.get("risk_score")
        else:
            continue
        state = finding_state(metadata.get("finding_state"))
        if state in {"rejected", "ignored"}:
            continue
        try:
            contribution = float(explicit_score)
        except (TypeError, ValueError):
            contribution = float(weights.get(str(severity or "info").lower(), 0))
        if metadata.get("proxy_evidence") is True:
            contribution *= 0.75
        if state == "unconfirmed":
            contribution *= 0.5
        total += contribution
    return clamp_score(total)
