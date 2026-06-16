from __future__ import annotations

from fls_pilot.analysis import (
    clamp_score,
    confidence_band,
    confidence_from_coverage,
    coverage_score,
    health_from_risk,
    low_end_health_score,
    mix_health_score,
    organizer_score,
    risk_band,
    risk_from_severities,
    routing_health_score,
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


def test_risk_and_confidence_can_be_estimated_from_shared_inputs() -> None:
    assert risk_from_severities(("medium", "low", "info")) == 24
    assert risk_from_severities(("critical", "critical", "high")) == 100
    assert confidence_from_coverage(
        required=3,
        available=2,
        evidence_mode="static_snapshot",
    ) == 67
    assert confidence_from_coverage(
        required=3,
        available=3,
        evidence_mode="rendered_audio",
    ) == 100


def test_mix_health_score_matches_legacy_formula() -> None:
    assert mix_health_score(high=0, medium=0, low=0, levels_valid=True, master_peak=-4.0) == 100
    assert mix_health_score(high=0, medium=0, low=0, levels_valid=True, master_peak=-1.5) == 93
    assert mix_health_score(high=0, medium=0, low=0, levels_valid=True, master_peak=0.5) == 76
    assert mix_health_score(high=1, medium=0, low=0, levels_valid=False, master_peak=-4.0) == 70


def test_organizer_score_matches_legacy_formula() -> None:
    assert organizer_score(
        unnamed_channels=1,
        routing_cleanup=1,
        unnamed_patterns=1,
        unnamed_playlist_tracks=1,
        duplicate_mixer=1,
        duplicate_patterns=1,
        grouping_candidates=1,
    ) == 65
    assert organizer_score(
        unnamed_channels=0,
        routing_cleanup=0,
        unnamed_patterns=0,
        unnamed_playlist_tracks=0,
        duplicate_mixer=0,
        duplicate_patterns=0,
        grouping_candidates=0,
    ) == 100


def test_routing_health_score_matches_legacy_formula() -> None:
    assert routing_health_score(
        direct_count=1,
        unrouted_count=1,
        dead_end_count=1,
        unused_count=1,
    ) == 64
    assert routing_health_score(
        direct_count=0,
        unrouted_count=0,
        dead_end_count=0,
        unused_count=0,
    ) == 100


def test_low_end_health_score_matches_legacy_formula() -> None:
    assert low_end_health_score(high=1, medium=1, low=1, stereo_risks=1, levels_valid=False) == 47
    assert low_end_health_score(high=0, medium=0, low=0, stereo_risks=0, levels_valid=True) == 100
