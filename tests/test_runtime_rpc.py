from __future__ import annotations

import threading

import pytest

from fls_pilot import daemon
from fls_pilot.runtime.client import RuntimeClient, RuntimeClientError
from fls_pilot.runtime.core import RuntimeCore


@pytest.fixture
def runtime_server():
    original_runtime = daemon._runtime
    daemon._runtime = RuntimeCore()
    server = daemon._Server(("127.0.0.1", 0), daemon._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
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
