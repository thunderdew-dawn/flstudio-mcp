from __future__ import annotations

import time

import numpy as np
import soundfile as sf

from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.audio_worker import AudioAnalysisWorker, submit_audio_feature_job
from fls_pilot.runtime.core import RuntimeCore


def test_audio_worker_publishes_compact_result_without_bridge_access(tmp_path) -> None:
    path = tmp_path / "mix.wav"
    sf.write(path, np.zeros(48000, dtype=np.float32), 48000, subtype="FLOAT")
    artifact_store = AudioArtifactStore(tmp_path / "artifacts")
    runtime = RuntimeCore(
        job_store_path=tmp_path / "jobs.sqlite3",
        job_result_validator=artifact_store.validate_result_ref,
    )
    AudioAnalysisWorker(artifact_store).register(runtime)
    try:
        submitted = submit_audio_feature_job(runtime, path)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = runtime.jobs.status(submitted["job_id"])
            if job.status in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("audio job did not complete")

        assert job.status == "succeeded", job.error
        assert job.result_ref["kind"] == "audio_features"
        assert "path" not in job.result_ref
        features = artifact_store.read_features(job.result_ref["artifact_id"])
        assert features["summary"]["duration_seconds"] == 1.0
    finally:
        runtime.close()
