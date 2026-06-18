from __future__ import annotations

import time

import numpy as np
import soundfile as sf
from test_runtime_core import FakeBridge

from fls_pilot.runtime.artifacts import AudioArtifactStore
from fls_pilot.runtime.audio_worker import AudioAnalysisWorker
from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.tools import audio


class MockMCP:
    def __init__(self) -> None:
        self.tools = {}

    def tool(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        def decorator(function):
            self.tools[function.__name__] = function
            return function

        return decorator


def _wait_for(tool, job_id: str, timeout: float = 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = tool(action="status", job_id=job_id)
        if response["job"]["status"] in {"succeeded", "failed", "cancelled"}:
            return response["job"]
        time.sleep(0.01)
    raise AssertionError("audio job did not finish")


def test_audio_analysis_tool_uses_runtime_jobs_and_compact_results(
    tmp_path,
    monkeypatch,
) -> None:
    source = tmp_path / "mix.wav"
    sf.write(source, np.zeros(48000, dtype=np.float32), 48000, subtype="FLOAT")
    runtime = RuntimeCore(
        job_store_path=tmp_path / "jobs.sqlite3",
        artifact_store=AudioArtifactStore(tmp_path / "artifacts"),
    )
    AudioAnalysisWorker(runtime.audio_artifacts).register(runtime)
    runtime.get_static_project_snapshot(FakeBridge())
    monkeypatch.setenv("FLS_PILOT_TRANSPORT", "direct")
    monkeypatch.setattr("fls_pilot.runtime.access.local_runtime", lambda: runtime)
    mcp = MockMCP()
    audio.register(mcp)
    tool = mcp.tools["fl_audio_analysis"]
    try:
        submitted = tool(action="submit", path=str(source))
        assert submitted["ok"] is True
        job = _wait_for(tool, submitted["job"]["job_id"])
        assert job["status"] == "succeeded", job["error"]

        result = tool(
            action="result",
            job_id=job["job_id"],
            workflow_targets=["mix_review"],
        )
        assert result["ok"] is True
        assert result["job"]["result_ref"]["kind"] == "audio_features"
        assert "path" not in result["job"]["result_ref"]
        assert result["report"]["contract_version"] == "fls-pilot.analysis-report.v1"
        assert tool(action="list")["jobs"]
    finally:
        runtime.close()


def test_audio_analysis_rejects_missing_source_before_job_creation(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = RuntimeCore(
        job_store_path=tmp_path / "jobs.sqlite3",
        artifact_store=AudioArtifactStore(tmp_path / "artifacts"),
    )
    AudioAnalysisWorker(runtime.audio_artifacts).register(runtime)
    monkeypatch.setenv("FLS_PILOT_TRANSPORT", "direct")
    monkeypatch.setattr("fls_pilot.runtime.access.local_runtime", lambda: runtime)
    mcp = MockMCP()
    audio.register(mcp)
    try:
        response = mcp.tools["fl_audio_analysis"](
            action="submit",
            path=str(tmp_path / "missing.wav"),
        )
        assert response["ok"] is False
        assert runtime.jobs.list(kind="audio.features") == []
    finally:
        runtime.close()
