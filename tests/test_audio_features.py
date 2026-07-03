from __future__ import annotations

import math

import numpy as np
import soundfile as sf

from fls_pilot.analysis.audio_features import FeatureExtractor


def _tone(sample_rate: int, seconds: float, frequency: float, amplitude: float):
    time = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
    return amplitude * np.sin(2 * np.pi * frequency * time)


def test_core_features_are_deterministic_for_mono_tone(tmp_path) -> None:
    sample_rate = 48000
    path = tmp_path / "tone.wav"
    sf.write(path, _tone(sample_rate, 1.0, 100.0, 0.5), sample_rate, subtype="FLOAT")

    first = FeatureExtractor().extract(path)
    second = FeatureExtractor().extract(path)
    summary = first["summary"]

    assert first == second
    assert summary["sample_rate"] == sample_rate
    assert summary["channel_count"] == 1
    assert math.isclose(summary["peak_dbfs"], -6.0206, abs_tol=0.02)
    assert math.isclose(summary["rms_dbfs"], -9.0309, abs_tol=0.05)
    assert math.isclose(summary["crest_factor_db"], 3.0103, abs_tol=0.05)
    assert summary["low_end_energy_ratio"] > 0.9
    assert summary["bass_80_120_ratio"] > 0.9
    assert summary["low_end_20_120_ratio"] > 0.9
    assert summary["mono_folddown_loss_db"] is None
    assert summary["stereo_correlation_proxy"] is None
    assert "insufficient_stereo_evidence" in first["warnings"]
    assert first["optional_mir"]["tempo"]["availability"] == "not_computed"


def test_stereo_metrics_are_labeled_proxies(tmp_path) -> None:
    sample_rate = 48000
    mono = _tone(sample_rate, 1.0, 80.0, 0.4)
    path = tmp_path / "anti-phase.wav"
    sf.write(path, np.column_stack((mono, -mono)), sample_rate, subtype="FLOAT")

    summary = FeatureExtractor().extract(path)["summary"]

    assert summary["stereo_correlation_proxy"] < -0.99
    assert summary["low_band_stereo_proxy"] < -0.99
    assert summary["stereo_width_proxy"] > 1000
    assert summary["mono_folddown_loss_db"] < -60
    assert summary["low_band_side_ratio"] > 0.99


def test_low_end_feature_bands_and_short_audio_warnings(tmp_path) -> None:
    sample_rate = 48000
    path = tmp_path / "short-rumble.wav"
    sf.write(path, _tone(sample_rate, 0.02, 15.0, 0.5), sample_rate, subtype="FLOAT")

    result = FeatureExtractor().extract(path)
    summary = result["summary"]

    assert summary["infrasonic_ratio_below_20"] > 0.5
    assert summary["sub_20_40_ratio"] < 0.55
    assert "audio_shorter_than_fft_window_zero_padded" in result["warnings"]
