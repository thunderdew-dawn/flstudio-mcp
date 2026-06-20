from __future__ import annotations

import threading

import pytest

from fls_pilot import daemon
from fls_pilot.runtime.client import RuntimeClient, RuntimeClientError
from fls_pilot.runtime.core import RuntimeCore


@pytest.fixture
def runtime_server(tmp_path):
    original_runtime = daemon._runtime
    daemon._runtime = RuntimeCore(
        job_store_path=tmp_path / "jobs.sqlite3",
        workflow_store_path=tmp_path / "workflows.sqlite3",
        workflow_run_store_path=tmp_path / "runs.sqlite3",
    )
    # Register a dummy job handler for the tests
    daemon._runtime.jobs.register_handler("workflow.low_end_level4", lambda p, c: {})
    
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


def _client(server) -> RuntimeClient:
    return RuntimeClient(
        host="127.0.0.1",
        port=server.server_address[1],
        timeout=2.0,
    )


def test_admin_list_returns_builtins_and_custom(runtime_server) -> None:
    client = _client(runtime_server)
    
    # Create custom definition
    client.workflow_admin_create({
        "workflow_id": "user.low_end_level4",
        "title": "Low End",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    
    workflows = client.workflow_admin_list()
    ids = {w["workflow_id"] for w in workflows}
    
    # Built-ins should be there
    assert "mix_review" in ids
    # Custom should be there
    assert "user.low_end_level4" in ids


def test_admin_get_can_read_builtin(runtime_server) -> None:
    client = _client(runtime_server)
    w = client.workflow_admin_get("mix_review")
    assert w["workflow_id"] == "mix_review"
    assert w["origin"] == "builtin"
    assert w["protected"] is True


def test_admin_create_accepts_valid_custom_id(runtime_server) -> None:
    client = _client(runtime_server)
    w = client.workflow_admin_create({
        "workflow_id": "user.low_end_level4",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    assert w["workflow_id"] == "user.low_end_level4"
    assert w["origin"] == "custom"


def test_admin_create_rejects_custom_id_without_namespace(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="Invalid custom workflow ID"):
        client.workflow_admin_create({
            "workflow_id": "my_workflow",
            "runner_type": "job",
            "runner_ref": "workflow.low_end_level4"
        })


def test_admin_create_rejects_builtin_overwrite(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="Cannot overwrite built-in"):
        client.workflow_admin_create({
            "workflow_id": "mix_review",
            "runner_type": "job",
            "runner_ref": "workflow.low_end_level4"
        })


def test_admin_create_rejects_dangerous_fields(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="Dangerous field rejected: cmd"):
        client.workflow_admin_create({
            "workflow_id": "user.dangerous",
            "runner_type": "job",
            "runner_ref": "workflow.low_end_level4",
            "metadata": {"cmd": "rm -rf /"}
        })


def test_admin_create_rejects_job_without_ref(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="requires a runner_ref"):
        client.workflow_admin_create({
            "workflow_id": "user.noref",
            "runner_type": "job"
        })


def test_admin_update_custom_workflow(runtime_server) -> None:
    client = _client(runtime_server)
    client.workflow_admin_create({
        "workflow_id": "user.updateable",
        "title": "Old Title",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    
    updated = client.workflow_admin_update("user.updateable", {"title": "New Title"})
    assert updated["title"] == "New Title"
    assert updated["version"] == 2


def test_admin_update_rejects_builtin(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="Built-in workflows cannot be updated"):
        client.workflow_admin_update("mix_review", {"title": "Hacked"})


def test_admin_archive_custom_no_hard_delete(runtime_server) -> None:
    client = _client(runtime_server)
    client.workflow_admin_create({
        "workflow_id": "user.to_archive",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    
    archived = client.workflow_admin_archive("user.to_archive")
    assert archived["status"] == "archived"
    assert archived["archived_at"] is not None
    
    # Should be excluded from list by default
    assert "user.to_archive" not in {w["workflow_id"] for w in client.workflow_admin_list()}
    # Should be included if requested
    assert "user.to_archive" in {w["workflow_id"] for w in client.workflow_admin_list(include_archived=True)}


def test_admin_archive_rejects_builtin(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="Built-in workflows cannot be archived"):
        client.workflow_admin_archive("mix_review")


def test_job_kind_list(runtime_server) -> None:
    client = _client(runtime_server)
    kinds = client.job_kind_list()
    assert "workflow.low_end_level4" in kinds
    # Ensure handlers aren't leaked, just strings
    assert all(isinstance(k, str) for k in kinds)


def test_admin_validate(runtime_server) -> None:
    client = _client(runtime_server)
    res = client.workflow_admin_validate({
        "workflow_id": "user.valid",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    assert res["valid"] is True
    
    res2 = client.workflow_admin_validate({
        "workflow_id": "bad_id",
        "runner_type": "job",
        "metadata": {"script": "echo"}
    })
    assert res2["valid"] is False
    assert any("Dangerous" in e for e in res2["errors"])
    assert any("Invalid custom workflow ID" in e for e in res2["errors"])
    assert any("requires a runner_ref" in e for e in res2["errors"])


def test_admin_create_rejects_unregistered_job_kind(runtime_server) -> None:
    client = _client(runtime_server)
    with pytest.raises(RuntimeClientError, match="is not a registered job kind"):
        client.workflow_admin_create({
            "workflow_id": "user.badkind",
            "runner_type": "job",
            "runner_ref": "workflow.does_not_exist"
        })


def test_admin_update_rejects_unregistered_job_kind(runtime_server) -> None:
    client = _client(runtime_server)
    client.workflow_admin_create({
        "workflow_id": "user.update_bad_kind",
        "title": "Valid initially",
        "runner_type": "job",
        "runner_ref": "workflow.low_end_level4"
    })
    with pytest.raises(RuntimeClientError, match="is not a registered job kind"):
        client.workflow_admin_update("user.update_bad_kind", {
            "runner_ref": "workflow.does_not_exist"
        })
