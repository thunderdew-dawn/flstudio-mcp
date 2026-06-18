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
    assert summary["stereo_correlation_proxy"] is None
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
