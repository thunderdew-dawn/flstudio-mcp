from __future__ import annotations

from fls_pilot.music.mix_review_levels import (
    MixReviewLevel,
    allow_inline_live_meter,
    normalize_mix_review_options,
)


def test_default_options_are_level_1() -> None:
    options = normalize_mix_review_options(None)

    assert options.level == MixReviewLevel.STATIC
    assert options.capture.loop_seconds == 16


def test_string_level_is_normalized() -> None:
    options = normalize_mix_review_options({"level": "2"})

    assert options.level == MixReviewLevel.LIVE_WATCH


def test_invalid_level_does_not_crash() -> None:
    options = normalize_mix_review_options({"level": "not-a-level"})

    assert options.level == MixReviewLevel.STATIC


def test_inline_live_meter_policy_allows_only_static_and_watch_levels() -> None:
    assert allow_inline_live_meter(None) is True
    assert allow_inline_live_meter(normalize_mix_review_options({"level": 1})) is True
    assert allow_inline_live_meter(normalize_mix_review_options({"level": 2})) is True
    assert allow_inline_live_meter(normalize_mix_review_options({"level": 3})) is False
    assert allow_inline_live_meter(normalize_mix_review_options({"level": 4})) is False


def test_loop_seconds_bounds() -> None:
    low = normalize_mix_review_options({"level": 2, "loop_seconds": 1})
    high = normalize_mix_review_options({"level": 2, "loop_seconds": 999})

    assert low.capture.loop_seconds == 8
    assert high.capture.loop_seconds == 60


def test_level_3_missing_master_evidence() -> None:
    options = normalize_mix_review_options({"level": 3})

    assert options.requested_evidence_summary()["rendered_master"]["status"] == "missing"
    assert "Integrated LUFS" in options.expected_checks()


def test_level_4_missing_stem_evidence() -> None:
    options = normalize_mix_review_options({"level": 4})

    assert options.requested_evidence_summary()["rendered_stem_status"] == "missing"
    assert "Kick/Bass Masking" in options.expected_checks()
