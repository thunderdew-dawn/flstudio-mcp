from __future__ import annotations

from fls_pilot.analysis.audio_features import pairwise_overlap_masks


def _features(mask, *, duration=0.4, sample_rate=48000):
    return {
        "source": {
            "duration_seconds": duration,
            "sample_rate": sample_rate,
        },
        "activity": {
            "frame_hop_seconds": 0.1,
            "mask": mask,
        },
    }


def test_pairwise_overlap_masks_require_aligned_stems() -> None:
    result = pairwise_overlap_masks(
        {
            "kick": _features([True, False, True, False]),
            "bass": _features([True, True, False, False]),
        }
    )

    assert result["availability"] == "complete"
    assert result["pairs"]["bass|kick"]["mask"] == [True, False, False, False]
    assert result["pairs"]["bass|kick"]["overlap_ratio"] == 0.25


def test_pairwise_overlap_rejects_incompatible_duration() -> None:
    result = pairwise_overlap_masks(
        {
            "kick": _features([True, False, True, False]),
            "bass": _features([True, True], duration=0.2),
        }
    )

    assert result["availability"] == "unavailable"
    assert result["reason"] == "stems_are_not_time_aligned"
