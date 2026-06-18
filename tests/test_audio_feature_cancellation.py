from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from fls_pilot.analysis.audio_features import FeatureExtractor, FeatureExtractorConfig


def test_feature_extraction_checks_cooperative_cancellation_between_blocks(tmp_path) -> None:
    path = tmp_path / "long.wav"
    sf.write(path, np.zeros(48000 * 3, dtype=np.float32), 48000, subtype="FLOAT")
    calls = 0

    def cancel() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise RuntimeError("cancelled")

    extractor = FeatureExtractor(FeatureExtractorConfig(block_frames=4096))
    with pytest.raises(RuntimeError, match="cancelled"):
        extractor.extract(path, cancellation_check=cancel)

    assert calls == 3
