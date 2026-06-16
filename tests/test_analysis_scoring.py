from __future__ import annotations

from fls_pilot.analysis import (
    clamp_score,
    confidence_band,
    coverage_score,
    health_from_risk,
    risk_band,
)


def test_scores_are_clamped_to_public_range() -> None:
    assert clamp_score(-10) == 0
    assert clamp_score(42.4) == 42
    assert clamp_score(120) == 100
    assert clamp_score("bad", default=7) == 7


def test_risk_health_and_coverage_have_separate_meanings() -> None:
    assert risk_band(0) == "none"
    assert risk_band(12) == "low"
    assert risk_band(45) == "medium"
    assert risk_band(75) == "high"
    assert risk_band(95) == "critical"
    assert health_from_risk(75) == 25
    assert coverage_score(required=4, available=3) == 75
    assert coverage_score(required=0, available=0) == 100


def test_confidence_band_is_not_risk_band() -> None:
    assert confidence_band(10) == "low"
    assert confidence_band(55) == "medium"
    assert confidence_band(90) == "high"
