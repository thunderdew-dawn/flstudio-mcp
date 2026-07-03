"""Deterministic, memory-bounded core mix feature extraction."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .audio_schema import AUDIO_FEATURES_CONTRACT_VERSION

FEATURE_EXTRACTOR_VERSION = "core-mix-features-2"


@dataclass(frozen=True)
class FeatureExtractorConfig:
    block_frames: int = 65536
    fft_size: int = 4096
    activity_hop_seconds: float = 0.1
    activity_threshold_dbfs: float = -60.0
    low_band_hz: float = 120.0
    loudness_max_seconds: float = 600.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeatureExtractor:
    def __init__(self, config: FeatureExtractorConfig | None = None) -> None:
        self.config = config or FeatureExtractorConfig()

    def extract(
        self,
        path: str | Path,
        *,
        cancellation_check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        import numpy as np
        import soundfile as sf

        check = cancellation_check or (lambda: None)
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        check()
        with sf.SoundFile(source) as audio:
            sample_rate = int(audio.samplerate)
            channel_count = int(audio.channels)
            total_frames = int(len(audio))
            if sample_rate <= 0 or channel_count <= 0 or total_frames <= 0:
                raise ValueError("audio file is empty or has invalid stream metadata")
            duration_seconds = total_frames / sample_rate
            activity_size = max(1, int(round(sample_rate * self.config.activity_hop_seconds)))
            fft_size = max(256, int(self.config.fft_size))
            fft_hop = max(1, fft_size // 2)
            window = np.hanning(fft_size).astype(np.float64)
            frequencies = np.fft.rfftfreq(fft_size, 1.0 / sample_rate)
            band_masks = {
                "sub": (frequencies >= 20) & (frequencies < 80),
                "low": (frequencies >= 80) & (frequencies < 250),
                "mid": (frequencies >= 250) & (frequencies < 4000),
                "high": frequencies >= 4000,
            }
            low_end_masks = {
                "infrasonic_below_20": frequencies < 20,
                "sub_20_40": (frequencies >= 20) & (frequencies < 40),
                "sub_40_80": (frequencies >= 40) & (frequencies < 80),
                "bass_80_120": (frequencies >= 80) & (frequencies < 120),
                "low_mid_120_250": (frequencies >= 120) & (frequencies < 250),
                "low_end_20_120": (frequencies >= 20) & (frequencies < 120),
                "mud_120_250": (frequencies >= 120) & (frequencies < 250),
            }
            band_energy = {name: 0.0 for name in band_masks}
            low_end_energy = {name: 0.0 for name in low_end_masks}
            peak = 0.0
            sum_squares = 0.0
            mono_sum_squares = 0.0
            sample_count = 0
            activity_mask: list[bool] = []
            activity_rms_dbfs: list[float | None] = []
            activity_carry = np.empty(0, dtype=np.float64)
            fft_carry = np.empty(0, dtype=np.float64)
            left_fft_carry = np.empty(0, dtype=np.float64)
            right_fft_carry = np.empty(0, dtype=np.float64)
            stereo = channel_count >= 2
            left_squares = right_squares = cross = 0.0
            mid_squares = side_squares = 0.0
            low_left_squares = low_right_squares = low_cross = 0.0
            band_mid_energy = {
                "sub_20_40": 0.0,
                "bass_80_120": 0.0,
                "low_end_20_120": 0.0,
            }
            band_side_energy = dict(band_mid_energy)
            loudness_parts: list[Any] = []
            loudness_limit = int(sample_rate * self.config.loudness_max_seconds)
            loudness_frames = 0

            def process_fft_frames(
                mono_values,
                left_values=None,
                right_values=None,
                *,
                padded_tail: bool = False,
            ) -> int:
                processed = 0
                for start in range(0, len(mono_values) - fft_size + 1, fft_hop):
                    mono_frame = mono_values[start : start + fft_size]
                    spectrum = np.fft.rfft(mono_frame * window)
                    power = np.abs(spectrum) ** 2
                    for name, mask in band_masks.items():
                        band_energy[name] += float(power[mask].sum())
                    for name, mask in low_end_masks.items():
                        low_end_energy[name] += float(power[mask].sum())
                    if left_values is not None and right_values is not None:
                        left_frame = left_values[start : start + fft_size]
                        right_frame = right_values[start : start + fft_size]
                        mid_frame = (left_frame + right_frame) * 0.5
                        side_frame = (left_frame - right_frame) * 0.5
                        mid_power = np.abs(np.fft.rfft(mid_frame * window)) ** 2
                        side_power = np.abs(np.fft.rfft(side_frame * window)) ** 2
                        for name in band_mid_energy:
                            mask = low_end_masks[name]
                            band_mid_energy[name] += float(mid_power[mask].sum())
                            band_side_energy[name] += float(side_power[mask].sum())
                    processed = start + (fft_size if padded_tail else fft_hop)
                return processed

            for block in audio.blocks(
                blocksize=max(1024, int(self.config.block_frames)),
                dtype="float64",
                always_2d=True,
            ):
                check()
                values = np.asarray(block, dtype=np.float64)
                mono = values.mean(axis=1)
                peak = max(peak, float(np.max(np.abs(values), initial=0.0)))
                sum_squares += float(np.sum(values * values))
                sample_count += int(values.size)
                mono_sum_squares += float(np.sum(mono * mono))

                if loudness_frames < loudness_limit:
                    remaining = loudness_limit - loudness_frames
                    loudness_parts.append(values[:remaining].copy())
                    loudness_frames += min(len(values), remaining)

                fft_values = np.concatenate((fft_carry, mono))
                if stereo:
                    left_fft_values = np.concatenate((left_fft_carry, values[:, 0]))
                    right_fft_values = np.concatenate((right_fft_carry, values[:, 1]))
                    processed = process_fft_frames(
                        fft_values,
                        left_fft_values,
                        right_fft_values,
                    )
                    fft_carry = fft_values[processed:]
                    left_fft_carry = left_fft_values[processed:]
                    right_fft_carry = right_fft_values[processed:]
                else:
                    processed = process_fft_frames(fft_values)
                    fft_carry = fft_values[processed:]

                activity_values = np.concatenate((activity_carry, mono))
                complete = len(activity_values) // activity_size
                for index in range(complete):
                    frame = activity_values[
                        index * activity_size : (index + 1) * activity_size
                    ]
                    rms = float(np.sqrt(np.mean(frame * frame)))
                    dbfs = _dbfs(rms)
                    activity_rms_dbfs.append(None if not math.isfinite(dbfs) else round(dbfs, 3))
                    activity_mask.append(dbfs >= self.config.activity_threshold_dbfs)
                activity_carry = activity_values[complete * activity_size :]

                if stereo:
                    left = values[:, 0]
                    right = values[:, 1]
                    left_squares += float(np.sum(left * left))
                    right_squares += float(np.sum(right * right))
                    cross += float(np.sum(left * right))
                    mid = (left + right) * 0.5
                    side = (left - right) * 0.5
                    mid_squares += float(np.sum(mid * mid))
                    side_squares += float(np.sum(side * side))
                    low_frequencies = np.fft.rfftfreq(len(left), 1.0 / sample_rate)
                    low_mask = low_frequencies <= self.config.low_band_hz
                    low_left_spectrum = np.fft.rfft(left)
                    low_right_spectrum = np.fft.rfft(right)
                    low_left_spectrum[~low_mask] = 0
                    low_right_spectrum[~low_mask] = 0
                    low_left = np.fft.irfft(low_left_spectrum, n=len(left))
                    low_right = np.fft.irfft(low_right_spectrum, n=len(right))
                    low_left_squares += float(np.sum(low_left * low_left))
                    low_right_squares += float(np.sum(low_right * low_right))
                    low_cross += float(np.sum(low_left * low_right))

            check()
            if fft_carry.size:
                pad = fft_size - min(fft_size, len(fft_carry))
                tail = np.pad(fft_carry[:fft_size], (0, pad))
                if stereo:
                    left_tail = np.pad(left_fft_carry[:fft_size], (0, pad))
                    right_tail = np.pad(right_fft_carry[:fft_size], (0, pad))
                    process_fft_frames(
                        tail,
                        left_tail,
                        right_tail,
                        padded_tail=True,
                    )
                else:
                    process_fft_frames(tail, padded_tail=True)
            if activity_carry.size:
                rms = float(np.sqrt(np.mean(activity_carry * activity_carry)))
                dbfs = _dbfs(rms)
                activity_rms_dbfs.append(None if not math.isfinite(dbfs) else round(dbfs, 3))
                activity_mask.append(dbfs >= self.config.activity_threshold_dbfs)

        rms = math.sqrt(sum_squares / max(1, sample_count))
        peak_dbfs = _dbfs(peak)
        rms_dbfs = _dbfs(rms)
        total_band_energy = sum(band_energy.values()) or 1.0
        normalized_bands = {
            name: round(value / total_band_energy, 8)
            for name, value in band_energy.items()
        }
        normalized_low_end = {
            name: round(value / total_band_energy, 8)
            for name, value in low_end_energy.items()
        }
        low_end_ratio = normalized_bands["sub"] + normalized_bands["low"]
        correlation = (
            _correlation(cross, left_squares, right_squares) if stereo else None
        )
        low_correlation = (
            _correlation(low_cross, low_left_squares, low_right_squares)
            if stereo
            else None
        )
        width = (
            math.sqrt(side_squares / max(mid_squares, 1e-20)) if stereo else 0.0
        )
        low_band_side_ratio = _side_ratio(
            band_side_energy["low_end_20_120"],
            band_mid_energy["low_end_20_120"],
        )
        mono_folddown_loss_db = (
            _power_ratio_db(mono_sum_squares, sum_squares / channel_count)
            if stereo
            else None
        )
        integrated_lufs, loudness_warning = _integrated_loudness(
            loudness_parts,
            sample_rate,
            duration_seconds=duration_seconds,
            maximum_seconds=self.config.loudness_max_seconds,
        )
        warnings = [loudness_warning] if loudness_warning else []
        if total_frames < fft_size:
            warnings.append("audio_shorter_than_fft_window_zero_padded")
        if not stereo:
            warnings.append("insufficient_stereo_evidence")
        elif low_band_side_ratio is None:
            warnings.append("insufficient_low_band_stereo_evidence")
        if normalized_low_end["low_end_20_120"] <= 1e-8:
            warnings.append("insufficient_low_band_evidence")
        return {
            "contract_version": AUDIO_FEATURES_CONTRACT_VERSION,
            "extractor_version": FEATURE_EXTRACTOR_VERSION,
            "configuration": self.config.to_dict(),
            "source": {
                "basename": source.name,
                "duration_seconds": round(duration_seconds, 6),
                "sample_rate": sample_rate,
                "channel_count": channel_count,
                "frame_count": total_frames,
            },
            "summary": {
                "duration_seconds": round(duration_seconds, 6),
                "sample_rate": sample_rate,
                "channel_count": channel_count,
                "peak_dbfs": _finite_round(peak_dbfs),
                "rms_dbfs": _finite_round(rms_dbfs),
                "integrated_lufs": integrated_lufs,
                "crest_factor_db": _finite_round(peak_dbfs - rms_dbfs),
                "band_energy": normalized_bands,
                "low_end_energy_ratio": round(low_end_ratio, 8),
                "infrasonic_ratio_below_20": normalized_low_end["infrasonic_below_20"],
                "sub_20_40_ratio": normalized_low_end["sub_20_40"],
                "sub_40_80_ratio": normalized_low_end["sub_40_80"],
                "bass_80_120_ratio": normalized_low_end["bass_80_120"],
                "low_mid_120_250_ratio": normalized_low_end["low_mid_120_250"],
                "low_end_20_120_ratio": normalized_low_end["low_end_20_120"],
                "mud_120_250_ratio": normalized_low_end["mud_120_250"],
                "stereo_correlation_proxy": _optional_round(correlation),
                "stereo_width_proxy": round(width, 6),
                "low_band_stereo_proxy": _optional_round(low_correlation),
                "sub_side_ratio_db": _optional_round(
                    _power_ratio_db(
                        band_side_energy["sub_20_40"],
                        band_mid_energy["sub_20_40"],
                    )
                ),
                "bass_side_ratio_db": _optional_round(
                    _power_ratio_db(
                        band_side_energy["bass_80_120"],
                        band_mid_energy["bass_80_120"],
                    )
                ),
                "low_band_side_ratio": _optional_round(low_band_side_ratio),
                "mono_folddown_loss_db": _optional_round(mono_folddown_loss_db),
            },
            "activity": {
                "frame_hop_seconds": self.config.activity_hop_seconds,
                "threshold_dbfs": self.config.activity_threshold_dbfs,
                "mask": activity_mask,
                "rms_dbfs": activity_rms_dbfs,
            },
            "optional_mir": {
                "tempo": {"availability": "not_computed"},
                "key": {"availability": "not_computed"},
                "onsets": {"availability": "not_computed"},
                "melody": {"availability": "not_computed"},
            },
            "warnings": warnings,
        }


def pairwise_overlap_masks(
    stems: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = {str(name): dict(features) for name, features in stems.items()}
    names = sorted(rows)
    if len(names) < 2:
        return {"availability": "unavailable", "reason": "at_least_two_stems_required"}
    reference = rows[names[0]]
    reference_source = dict(reference.get("source") or {})
    reference_activity = dict(reference.get("activity") or {})
    sample_rate = int(reference_source.get("sample_rate") or 0)
    duration = float(reference_source.get("duration_seconds") or 0)
    hop = float(reference_activity.get("frame_hop_seconds") or 0)
    if sample_rate <= 0 or duration <= 0 or hop <= 0:
        return {"availability": "unavailable", "reason": "missing_alignment_metadata"}

    masks: dict[str, list[bool]] = {}
    for name in names:
        source = dict(rows[name].get("source") or {})
        activity = dict(rows[name].get("activity") or {})
        mask = [bool(value) for value in activity.get("mask") or ()]
        if (
            int(source.get("sample_rate") or 0) != sample_rate
            or abs(float(source.get("duration_seconds") or 0) - duration) > hop
            or abs(float(activity.get("frame_hop_seconds") or 0) - hop) > 1e-9
            or not mask
        ):
            return {
                "availability": "unavailable",
                "reason": "stems_are_not_time_aligned",
                "stem": name,
            }
        masks[name] = mask

    pairs: dict[str, Any] = {}
    for left_index, left_name in enumerate(names):
        for right_name in names[left_index + 1 :]:
            length = min(len(masks[left_name]), len(masks[right_name]))
            if abs(len(masks[left_name]) - len(masks[right_name])) > 1:
                return {
                    "availability": "unavailable",
                    "reason": "stems_are_not_time_aligned",
                }
            overlap = [
                masks[left_name][index] and masks[right_name][index]
                for index in range(length)
            ]
            pairs[f"{left_name}|{right_name}"] = {
                "mask": overlap,
                "overlap_ratio": round(sum(overlap) / max(1, length), 8),
            }
    return {
        "availability": "complete",
        "frame_hop_seconds": hop,
        "pairs": pairs,
    }


def _integrated_loudness(parts, sample_rate, *, duration_seconds, maximum_seconds):
    if duration_seconds > maximum_seconds:
        return None, "integrated_lufs_unavailable_for_long_file"
    try:
        import numpy as np
        import pyloudnorm as pyln

        values = np.concatenate(parts, axis=0)
        meter = pyln.Meter(sample_rate)
        loudness = float(meter.integrated_loudness(values))
        return _finite_round(loudness), None
    except Exception:
        return None, "integrated_lufs_unavailable"


def _correlation(cross: float, left_squares: float, right_squares: float) -> float | None:
    denominator = math.sqrt(left_squares * right_squares)
    if denominator <= 1e-20:
        return None
    return max(-1.0, min(1.0, cross / denominator))


def _side_ratio(side_power: float, mid_power: float) -> float | None:
    total = side_power + mid_power
    if total <= 1e-20:
        return None
    return max(0.0, min(1.0, side_power / total))


def _power_ratio_db(numerator: float, denominator: float) -> float | None:
    if denominator <= 1e-20:
        return None
    if numerator <= 1e-20:
        return -120.0
    return 10.0 * math.log10(numerator / denominator)


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(value) if value > 0 else float("-inf")


def _finite_round(value: float, digits: int = 6) -> float | None:
    return round(value, digits) if math.isfinite(value) else None


def _optional_round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)
