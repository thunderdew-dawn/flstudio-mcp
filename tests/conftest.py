"""Shared test fixtures for fls-pilot tests.

Provides test-environment isolation for tests that depend on daemon._runtime or
any RuntimeCore constructed without an explicit job_store_path.  Without this
fixture, RuntimeCore defaults to ~/.fls-pilot/runtime/jobs.sqlite3, which may
not be writable in CI environments.
"""

from __future__ import annotations

import pytest

from fls_pilot import daemon
from fls_pilot.runtime import access as runtime_access
from fls_pilot.runtime.core import RuntimeCore


@pytest.fixture(autouse=True)
def _isolate_daemon_runtime(tmp_path, monkeypatch):
    """Replace daemon._runtime and runtime_access._LOCAL_RUNTIME with a
    tmp_path-backed RuntimeCore.

    This fixture is autouse so it runs for every test, ensuring that:
    - daemon._handle_request() / _get_runtime() uses an isolated SQLite store.
    - local_runtime() / get_report_store() uses the same isolated store instead
      of creating its own RuntimeCore() against the default ~/.fls-pilot path.
    - offline tests default to direct Runtime access even when the surrounding
      environment has FLS_PILOT_TRANSPORT=tcp for live/manual workflows.

    The runtime_server fixture in test_runtime_rpc.py saves and restores
    daemon._runtime directly; the conftest try/finally restores the module
    globals cleanly after each test.
    """
    monkeypatch.setenv("FLS_PILOT_TRANSPORT", "direct")
    prev_daemon = daemon._runtime
    prev_local = runtime_access._LOCAL_RUNTIME
    isolated = RuntimeCore(
        job_store_path=tmp_path / "daemon_jobs.sqlite3",
        workflow_store_path=tmp_path / "daemon_workflows.sqlite3",
        workflow_run_store_path=tmp_path / "daemon_workflow_runs.sqlite3",
    )
    daemon._runtime = isolated
    runtime_access._LOCAL_RUNTIME = isolated
    try:
        yield isolated
    finally:
        daemon._runtime = prev_daemon
        runtime_access._LOCAL_RUNTIME = prev_local
        isolated.close(wait=False)
