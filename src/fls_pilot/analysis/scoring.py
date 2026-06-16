"""Shared score helpers for analysis workflow reports."""

from __future__ import annotations


def clamp_score(value: float | int | None, *, default: int = 0) -> int:
    """Clamp a numeric score to the public 0..100 range."""
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, round(numeric)))


def health_from_risk(risk_score: float | int | None) -> int:
    """Convert risk into the canonical health direction: high is good."""
    return 100 - clamp_score(risk_score)


def coverage_score(required: int, available: int) -> int:
    """Percent of required evidence currently available."""
    required = max(0, int(required))
    available = max(0, int(available))
    if required == 0:
        return 100
    return clamp_score((available / required) * 100)


def risk_band(score: float | int | None) -> str:
    """Map 0..100 risk to a stable band."""
    value = clamp_score(score)
    if value == 0:
        return "none"
    if value <= 25:
        return "low"
    if value <= 60:
        return "medium"
    if value <= 85:
        return "high"
    return "critical"


def confidence_band(score: float | int | None) -> str:
    """Map 0..100 confidence to a stable band."""
    value = clamp_score(score)
    if value < 40:
        return "low"
    if value < 75:
        return "medium"
    return "high"


def risk_from_severities(severities: list[str] | tuple[str, ...]) -> int:
    """Estimate aggregate risk from finding severities."""
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
    return clamp_score(sum(weights.get(str(item).lower(), 0) for item in severities))


def confidence_from_coverage(
    *,
    required: int,
    available: int,
    evidence_mode: str,
) -> int:
    """Estimate confidence from required evidence coverage and evidence mode."""
    base = coverage_score(required, available)
    mode_bonus = {
        "rendered_audio": 15,
        "hybrid": 10,
        "watch_window": 8,
        "live_runtime": 4,
        "static_snapshot": 0,
        "manual_check": -10,
    }.get(str(evidence_mode), 0)
    return clamp_score(base + mode_bonus)


def mix_health_score(
    *,
    high: int,
    medium: int,
    low: int,
    levels_valid: bool,
    master_peak: float | None,
) -> int:
    """Calculate health score for Mix Review workflow."""
    penalty = high * 18 + medium * 9 + low * 3
    if not levels_valid:
        penalty += 12
    if master_peak is not None:
        if master_peak >= 0:
            penalty += 24
        elif master_peak > -1:
            penalty += 16
        elif master_peak > -3:
            penalty += 7
    return clamp_score(100 - penalty)


def organizer_score(
    *,
    unnamed_channels: int,
    routing_cleanup: int,
    unnamed_patterns: int,
    unnamed_playlist_tracks: int,
    duplicate_mixer: int,
    duplicate_patterns: int,
    grouping_candidates: int,
) -> int:
    """Calculate health score for Project Organizer workflow."""
    penalty = (
        routing_cleanup * 12
        + unnamed_channels * 5
        + unnamed_patterns * 4
        + unnamed_playlist_tracks * 2
        + duplicate_mixer * 5
        + duplicate_patterns * 4
        + grouping_candidates * 3
    )
    return clamp_score(100 - penalty)


def routing_health_score(
    *,
    direct_count: int,
    unrouted_count: int,
    dead_end_count: int,
    unused_count: int,
) -> int:
    """Calculate health score for Routing Audit workflow."""
    penalty = direct_count * 7 + unrouted_count * 12 + dead_end_count * 14 + unused_count * 3
    return clamp_score(100 - penalty)


def low_end_health_score(
    *,
    high: int,
    medium: int,
    low: int,
    stereo_risks: int,
    levels_valid: bool,
) -> int:
    """Calculate health score for Low-End Analysis workflow."""
    penalty = high * 24 + medium * 12 + low * 4 + stereo_risks * 5 + (0 if levels_valid else 8)
    return clamp_score(100 - penalty)
