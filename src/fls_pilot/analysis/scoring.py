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
