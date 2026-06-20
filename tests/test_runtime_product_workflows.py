from __future__ import annotations

from fls_pilot.runtime.core import RuntimeCore
from fls_pilot.runtime.workflow_runner import run_workflow

from test_runtime_core import FakeBridge


def test_preflight_is_static_and_exposes_missing_level_evidence(tmp_path) -> None:
    runtime = RuntimeCore(job_store_path=tmp_path / "jobs.sqlite3")
    bridge = FakeBridge()

    result = run_workflow(runtime, "preflight", bridge=bridge)

    assert result["workflow"] == "preflight"
    assert result["analysis_mode"] == "static_snapshot"
    assert "live_meter_window" in result["coverage"]["missing"]
    assert any("render" in row.lower() for row in result["limitations"])
    assert runtime.latest_report("preflight") is not None
