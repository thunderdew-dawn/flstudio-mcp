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
