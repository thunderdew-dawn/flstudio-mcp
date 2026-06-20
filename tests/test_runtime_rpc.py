from __future__ import annotations

import threading
import time

import pytest

from fls_pilot import daemon
from fls_pilot.runtime.client import RuntimeClient
from fls_pilot.runtime.core import RuntimeCore


@pytest.fixture
def runtime_server(tmp_path):
    original_runtime = daemon._runtime
    daemon._runtime = RuntimeCore(
        job_store_path=tmp_path / "jobs.sqlite3",
        workflow_store_path=tmp_path / "workflows.sqlite3",
        workflow_run_store_path=tmp_path / "runs.sqlite3",
    )
    server = daemon._Server(("127.0.0.1", 0), daemon._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        daemon._runtime.close()
        daemon._runtime = original_runtime


def _client(server) -> RuntimeClient:  # noqa: ANN001
    return RuntimeClient(
        host="127.0.0.1",
        port=server.server_address[1],
        timeout=2.0,
    )


def test_clients_share_one_runtime_session(runtime_server) -> None:
    first = _client(runtime_server)
    second = _client(runtime_server)

    assert first.session().id == second.session().id
    assert first.project_context().runtime_session_id == first.session().id


def test_runtime_catalog_is_canonical(runtime_server) -> None:
    catalog = {row["id"]: row for row in _client(runtime_server).workflow_catalog()}

    assert "sidechain_routing_check" in catalog
    assert "sidechaining" not in catalog
    assert catalog["project_health"]["status"] == "active"
    assert catalog["sidechain_routing_check"]["status"] == "planned"
    assert catalog["jam_2_project"]["enabled"] is False


def test_unknown_runtime_operation_fails_without_bridge_access(
    runtime_server,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        daemon,
        "_get_bridge",
        lambda: pytest.fail("bridge must not be accessed"),
    )
    client = _client(runtime_server)

    with pytest.raises(ValueError, match="unknown Runtime operation"):
        client.request("raw.execute", {"code": "anything"})


def test_planned_workflow_cannot_run_or_access_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        daemon,
        "_get_bridge",
        lambda: pytest.fail("planned workflow must not access the bridge"),
    )

    response = daemon._handle_request(
        {
            "op": "runtime",
            "operation": "analysis.workflow.run",
            "params": {"workflow_id": "jam_2_project", "inputs": {}},
        }
    )

    assert response["ok"] is False
    assert response["error"] == "workflow is not active: jam_2_project"


def test_daemon_rejects_unknown_params_without_bridge_access(monkeypatch) -> None:
    monkeypatch.setattr(
        daemon,
        "_get_bridge",
        lambda: pytest.fail("bridge must not be accessed"),
    )
    response = daemon._handle_request(
        {
            "op": "runtime",
            "operation": "runtime.session",
            "params": {"cmd": "raw"},
        }
    )

    assert response["ok"] is False
    assert response["code"] == "invalid_request"


@pytest.mark.parametrize(
    "report",
    [
        {"workflow": "mix_review"},
        {"contract_version": "fls-pilot.workflow-report.v1", "workflow": "mix_review"},
        {"contract_version": "fls-pilot.analysis-report.v2", "workflow": "mix_review"},
    ],
)
def test_runtime_rejects_incompatible_report_versions(report: dict) -> None:
    response = daemon._handle_request(
        {
            "op": "runtime",
            "operation": "analysis.report.add",
            "params": {"report": report},
        }
    )

    assert response["ok"] is False
    assert response["code"] == "incompatible_report_version"


def test_runtime_job_rpc_never_accesses_bridge(runtime_server, monkeypatch) -> None:
    runtime = daemon._runtime
    runtime.register_job_handler(
        "test.rpc",
        lambda payload, context: {"value": payload["value"]},
    )
    monkeypatch.setattr(
        daemon,
        "_get_bridge",
        lambda: pytest.fail("Runtime jobs must not access the FL bridge"),
    )
    client = _client(runtime_server)

    submitted = client.submit_job(
        "test.rpc",
        input={"value": 7},
        input_summary={"value": 7},
        idempotency_key="rpc:7",
    )
    for _ in range(100):
        status = client.job_status(submitted["job_id"])
        if status["status"] == "succeeded":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Runtime job did not complete")

    result = client.job_result(submitted["job_id"])
    assert result["result_ref"] == {"value": 7}
    assert client.list_jobs(kind="test.rpc")


def test_runtime_operations_include_admin_ops() -> None:
    from fls_pilot.runtime.protocol import RUNTIME_OPERATIONS
    expected = {
        "workflow.admin.list",
        "workflow.admin.get",
        "workflow.admin.create",
        "workflow.admin.update",
        "workflow.admin.archive",
        "workflow.admin.validate",
        "job.kind.list"
    }
    assert expected.issubset(RUNTIME_OPERATIONS)


def test_operation_allowed_params_strictly_defined_for_admin_ops() -> None:
    from fls_pilot.runtime.protocol import OPERATION_ALLOWED_PARAMS
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.list"] == {"include_archived"}
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.get"] == {"workflow_id", "version"}
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.create"] == {"definition"}
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.update"] == {"workflow_id", "patch"}
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.archive"] == {"workflow_id"}
    assert OPERATION_ALLOWED_PARAMS["workflow.admin.validate"] == {"definition"}
    assert OPERATION_ALLOWED_PARAMS["job.kind.list"] == set()


def test_workflow_run_operations_in_pr4() -> None:
    from fls_pilot.runtime.protocol import RUNTIME_OPERATIONS
    expected = {
        "workflow.run.submit",
        "workflow.run.status",
        "workflow.run.list",
        "workflow.run.cancel",
    }
    assert expected.issubset(RUNTIME_OPERATIONS)

