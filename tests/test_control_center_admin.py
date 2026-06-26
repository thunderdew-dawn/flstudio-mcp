"""Tests for PR 5: Local Admin Mode and Minimal Admin UI.

Acceptance criteria:
1. Without --admin / admin_enabled=False, /admin returns 403.
2. Without --admin, /api/admin/workflows returns 403.
3. With admin_enabled=True, /admin is reachable (serves admin.html bytes or 404 on missing file).
4. With admin_enabled=True, /api/admin/workflows proxies to RuntimeClient.workflow_admin_list.
5. GET /api/admin/job-kinds proxies to job_kind_list.
6. POST /api/admin/workflows/<id>/run proxies to workflow_run_submit.
7. POST /api/admin/workflow-runs/<run_id>/cancel proxies to workflow_run_cancel.
8. DELETE /api/admin/workflows/<id> calls workflow_admin_archive (not hard delete).
9. Normal Control Center routes remain unchanged (not broken by admin changes).
10. Admin UI is loaded from /admin, not injected into the existing index.html.
"""

from __future__ import annotations

import io
import json
from unittest import mock

import pytest

from fls_pilot import control_center


# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


def _state(*, admin_enabled: bool = False, port: int = 0) -> control_center.ControlCenterState:
    return control_center.ControlCenterState(
        host="127.0.0.1",
        port=port,
        sse_host="127.0.0.1",
        sse_port=8080,
        admin_enabled=admin_enabled,
    )


@pytest.fixture(autouse=True)
def _stable_port_probes(monkeypatch):
    monkeypatch.setattr(control_center, "can_bind_tcp", lambda host, port: True)
    monkeypatch.setattr(
        control_center,
        "tcp_port_status",
        lambda host, port: {
            "host": host,
            "preferred_port": port,
            "available": True,
            "selected_port": port,
            "fallback_port": None,
        },
    )


def _make_server_mock() -> mock.Mock:
    server = mock.Mock()
    server.server_version = "test"
    server.sys_version = ""
    server.timeout = 1
    server._BaseServer__is_shut_down = mock.Mock()
    server._BaseServer__shutdown_request = False
    return server


def _http(handler_cls, method: str, path: str, body: bytes = b"") -> dict:
    """Drive a single HTTP request through the handler and return the parsed JSON body."""
    content_length = len(body)
    headers = (
        f"{method} {path} HTTP/1.1\r\n"
        f"Host: localhost\r\n"
        f"Content-Type: application/json\r\n"
        f"Content-Length: {content_length}\r\n"
        f"\r\n"
    ).encode() + body

    class OneShotHandler(handler_cls):
        def setup(self):  # noqa: ANN001
            self.rfile = io.BytesIO(headers)
            self.wfile = io.BytesIO()

        def finish(self):  # noqa: ANN001
            pass

    handler = OneShotHandler(
        request=None,
        client_address=("127.0.0.1", 1234),
        server=_make_server_mock(),
    )
    raw = handler.wfile.getvalue().decode("utf-8")
    # Parse status line
    status_line, rest = raw.split("\r\n", 1)
    status_code = int(status_line.split(" ", 2)[1])
    body_str = rest.split("\r\n\r\n", 1)[1]
    data = json.loads(body_str)
    return {"status": status_code, "data": data}


# ---------------------------------------------------------------------------
# 1. Without admin_enabled=False, /admin returns 403
# ---------------------------------------------------------------------------


def test_admin_page_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/admin")
    assert result["status"] == 403
    assert result["data"]["ok"] is False
    assert "admin mode disabled" in result["data"]["error"]


# ---------------------------------------------------------------------------
# 2. Without admin_enabled=False, /api/admin/workflows returns 403
# ---------------------------------------------------------------------------


def test_admin_workflows_api_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/workflows")
    assert result["status"] == 403
    assert result["data"]["ok"] is False


def test_admin_api_post_workflows_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/admin/workflows", body=b'{"definition":{}}')
    assert result["status"] == 403


def test_admin_workflow_runs_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/workflow-runs")
    assert result["status"] == 403


def test_admin_job_kinds_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/job-kinds")
    assert result["status"] == 403


def test_admin_jobs_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/jobs")
    assert result["status"] == 403


def test_admin_delete_workflow_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "DELETE", "/api/admin/workflows/mix_review")
    assert result["status"] == 403


def test_admin_run_workflow_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/admin/workflows/mix_review/run", body=b'{"inputs":{}}')
    assert result["status"] == 403


def test_admin_cancel_run_returns_403_without_admin_flag():
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/admin/workflow-runs/run-123/cancel", body=b'{}')
    assert result["status"] == 403


# ---------------------------------------------------------------------------
# 3. With admin_enabled=True, /admin is reachable
# ---------------------------------------------------------------------------


def test_admin_page_is_reachable_with_admin_enabled(monkeypatch):
    """The /admin route should succeed (200) or raise a 404 for a missing asset, not 403."""
    state = _state(admin_enabled=True)
    handler_cls = control_center._handler_factory(state)
    # Patch _serve_static to avoid FileNotFoundError in tests
    served = []

    def fake_serve_static(self, name, content_type):  # noqa: ANN001
        served.append(name)
        payload = b"<html>admin</html>"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    monkeypatch.setattr(handler_cls, "_serve_static", fake_serve_static)
    headers = b"GET /admin HTTP/1.1\r\nHost: localhost\r\n\r\n"

    class OneShotHandler(handler_cls):
        def setup(self):  # noqa: ANN001
            self.rfile = io.BytesIO(headers)
            self.wfile = io.BytesIO()

        def finish(self):  # noqa: ANN001
            pass

    OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=_make_server_mock())
    assert "admin.html" in served


def test_admin_js_is_reachable_with_admin_enabled(monkeypatch):
    state = _state(admin_enabled=True)
    handler_cls = control_center._handler_factory(state)
    served = []

    def fake_serve_static(self, name, content_type):  # noqa: ANN001
        served.append(name)
        payload = b"/* admin js */"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    monkeypatch.setattr(handler_cls, "_serve_static", fake_serve_static)
    headers = b"GET /admin.js HTTP/1.1\r\nHost: localhost\r\n\r\n"

    class OneShotHandler(handler_cls):
        def setup(self):  # noqa: ANN001
            self.rfile = io.BytesIO(headers)
            self.wfile = io.BytesIO()

        def finish(self):  # noqa: ANN001
            pass

    OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=_make_server_mock())
    assert "admin.js" in served


# ---------------------------------------------------------------------------
# 4. /api/admin/workflows proxies to RuntimeClient.workflow_admin_list
# ---------------------------------------------------------------------------


def test_admin_workflows_api_proxies_to_runtime_client(monkeypatch):
    state = _state(admin_enabled=True)
    fake_workflows = [
        {"workflow_id": "mix_review", "title": "Mix Review", "status": "active", "origin": "builtin"}
    ]
    monkeypatch.setattr(
        control_center,
        "_admin_list_workflows",
        lambda s: {"ok": True, "workflows": fake_workflows},
    )
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/workflows")
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert len(result["data"]["workflows"]) == 1
    assert result["data"]["workflows"][0]["workflow_id"] == "mix_review"


def test_admin_create_workflow_proxies_to_runtime_client(monkeypatch):
    state = _state(admin_enabled=True)
    created = []
    monkeypatch.setattr(
        control_center,
        "_admin_create_workflow",
        lambda s, body: created.append(body) or {"ok": True, "workflow": {"workflow_id": "user.test"}},
    )
    handler_cls = control_center._handler_factory(state)
    body = json.dumps({"definition": {"workflow_id": "user.test"}}).encode()
    result = _http(handler_cls, "POST", "/api/admin/workflows", body=body)
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert len(created) == 1


def test_admin_update_workflow_uses_put_method(monkeypatch):
    state = _state(admin_enabled=True)
    updated = []
    monkeypatch.setattr(
        control_center,
        "_admin_update_workflow",
        lambda s, wid, body: updated.append((wid, body)) or {
            "ok": True,
            "workflow": {"workflow_id": wid},
        },
    )
    handler_cls = control_center._handler_factory(state)
    body = json.dumps({"patch": {"title": "New Title"}}).encode()
    result = _http(handler_cls, "PUT", "/api/admin/workflows/user.test", body=body)
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert updated[0][0] == "user.test"


# ---------------------------------------------------------------------------
# 5. GET /api/admin/job-kinds proxies to job_kind_list
# ---------------------------------------------------------------------------


def test_admin_job_kinds_proxies_to_job_kind_list(monkeypatch):
    state = _state(admin_enabled=True)
    monkeypatch.setattr(
        control_center,
        "_admin_list_job_kinds",
        lambda s: {"ok": True, "kinds": ["audio.features", "workflow.low_end_level4"]},
    )
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "GET", "/api/admin/job-kinds")
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert "audio.features" in result["data"]["kinds"]


# ---------------------------------------------------------------------------
# 6. POST /api/admin/workflows/<id>/run proxies to workflow_run_submit
# ---------------------------------------------------------------------------


def test_admin_run_workflow_proxies_to_workflow_run_submit(monkeypatch):
    state = _state(admin_enabled=True)
    submitted = []
    monkeypatch.setattr(
        control_center,
        "_admin_run_workflow",
        lambda s, wid, body: submitted.append((wid, body)) or {
            "ok": True,
            "run_id": "run-abc",
            "workflow_id": wid,
        },
    )
    handler_cls = control_center._handler_factory(state)
    body = json.dumps({"inputs": {"use_current_project": True}}).encode()
    result = _http(handler_cls, "POST", "/api/admin/workflows/user.low_end_level4/run", body=body)
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert result["data"]["run_id"] == "run-abc"
    assert submitted[0][0] == "user.low_end_level4"


# ---------------------------------------------------------------------------
# 7. POST /api/admin/workflow-runs/<run_id>/cancel proxies to workflow_run_cancel
# ---------------------------------------------------------------------------


def test_admin_cancel_workflow_run_proxies_to_run_cancel(monkeypatch):
    state = _state(admin_enabled=True)
    cancelled = []
    monkeypatch.setattr(
        control_center,
        "_admin_cancel_workflow_run",
        lambda s, run_id: cancelled.append(run_id) or {"ok": True, "run_id": run_id, "status": "cancelled"},
    )
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/admin/workflow-runs/run-abc/cancel", body=b"{}")
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert cancelled == ["run-abc"]


# ---------------------------------------------------------------------------
# 8. DELETE /api/admin/workflows/<id> archives, never hard deletes
# ---------------------------------------------------------------------------


def test_admin_delete_workflow_calls_archive_not_hard_delete(monkeypatch):
    """DELETE /api/admin/workflows/<id> must proxy to _admin_archive_workflow only."""
    state = _state(admin_enabled=True)
    archived = []
    hard_deleted = []

    monkeypatch.setattr(
        control_center,
        "_admin_archive_workflow",
        lambda s, wid: archived.append(wid) or {"ok": True, "workflow": {"workflow_id": wid, "status": "archived"}},
    )
    # Make sure there's no hard_delete function called
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "DELETE", "/api/admin/workflows/user.test")
    assert result["status"] == 200
    assert result["data"]["ok"] is True
    assert archived == ["user.test"]
    assert hard_deleted == []


def test_admin_archive_proxy_function_calls_workflow_admin_archive():
    """Unit test _admin_archive_workflow calls workflow_admin_archive."""
    state = _state(admin_enabled=True)
    calls = []

    class FakeClient:
        def workflow_admin_archive(self, wid):  # noqa: ANN001
            calls.append(wid)
            return {"workflow_id": wid, "status": "archived"}

    state.runtime_client = FakeClient()
    result = control_center._admin_archive_workflow(state, "user.custom_wf")
    assert result["ok"] is True
    assert calls == ["user.custom_wf"]
    assert result["workflow"]["status"] == "archived"


# ---------------------------------------------------------------------------
# 9. Normal Control Center routes remain unchanged
# ---------------------------------------------------------------------------


def test_normal_status_route_unchanged_by_admin_mode(monkeypatch):
    """The /api/status route must still work regardless of admin_enabled."""
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: [])
    for admin_enabled in (False, True):
        state = _state(admin_enabled=admin_enabled)
        handler_cls = control_center._handler_factory(state)
        result = _http(handler_cls, "GET", "/api/status")
        assert result["status"] == 200, f"Unexpected status with admin_enabled={admin_enabled}"
        assert "version" in result["data"]


def test_normal_refresh_route_unchanged_by_admin_mode(monkeypatch):
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: [])
    state = _state(admin_enabled=True)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/refresh", body=b"{}")
    assert result["status"] == 200
    assert "version" in result["data"]


def test_normal_workflows_route_not_blocked_by_admin_mode(monkeypatch):
    """The normal /api/workflows/* POST routes must not be blocked."""
    monkeypatch.setattr(
        control_center,
        "_run_mix_review",
        lambda s, **kwargs: {"ok": True, "workflow": "mix_review"},
    )
    state = _state(admin_enabled=False)
    handler_cls = control_center._handler_factory(state)
    result = _http(handler_cls, "POST", "/api/workflows/mix-review", body=b"{}")
    assert result["status"] == 200
    assert result["data"]["ok"] is True


# ---------------------------------------------------------------------------
# 10. Admin UI is separate — not injected into index.html
# ---------------------------------------------------------------------------


def test_index_html_is_not_admin_page(monkeypatch):
    """index.html must not serve admin.html content."""
    state = _state(admin_enabled=True)
    handler_cls = control_center._handler_factory(state)
    served = {}

    def fake_serve_static(self, name, content_type):  # noqa: ANN001
        served["name"] = name
        payload = f"<html>{name}</html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    monkeypatch.setattr(handler_cls, "_serve_static", fake_serve_static)
    headers = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"

    class OneShotHandler(handler_cls):
        def setup(self):  # noqa: ANN001
            self.rfile = io.BytesIO(headers)
            self.wfile = io.BytesIO()

        def finish(self):  # noqa: ANN001
            pass

    OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=_make_server_mock())
    # The root route must serve index.html, not admin.html
    assert served.get("name") == "index.html"


# ---------------------------------------------------------------------------
# ControlCenterState.admin_enabled tests
# ---------------------------------------------------------------------------


def test_state_admin_enabled_defaults_to_false():
    state = _state()
    assert state.admin_enabled is False


def test_state_admin_enabled_is_set_when_requested():
    state = _state(admin_enabled=True)
    assert state.admin_enabled is True


# ---------------------------------------------------------------------------
# serve_control_center and main accept --admin
# ---------------------------------------------------------------------------


def test_main_accepts_admin_flag(monkeypatch):
    served = []
    monkeypatch.setattr(
        control_center,
        "serve_control_center",
        lambda **kw: served.append(kw),
    )
    control_center.main(["--admin"])
    assert served[0]["admin"] is True


def test_main_admin_defaults_to_false_when_not_passed(monkeypatch):
    served = []
    monkeypatch.setattr(
        control_center,
        "serve_control_center",
        lambda **kw: served.append(kw),
    )
    control_center.main([])
    assert served[0]["admin"] is False


# ---------------------------------------------------------------------------
# Unit tests: admin proxy functions handle exceptions gracefully
# ---------------------------------------------------------------------------


def _state_with_failing_client(exc_type=RuntimeError, msg="simulated error"):
    """Return a state whose runtime_client raises for every admin call."""
    state = _state(admin_enabled=True)

    class FailingClient:
        def workflow_admin_list(self, **_):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_admin_get(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_admin_create(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_admin_update(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_admin_archive(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_run_submit(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_run_list(self, **_):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_run_status(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def workflow_run_cancel(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def job_kind_list(self):
            raise exc_type(msg)

        def list_jobs(self, **_):  # noqa: ANN001, ANN003
            raise exc_type(msg)

        def cancel_job(self, *_, **__):  # noqa: ANN001, ANN003
            raise exc_type(msg)

    state.runtime_client = FailingClient()
    return state


def test_admin_list_workflows_returns_error_on_runtime_failure():
    state = _state_with_failing_client()
    result = control_center._admin_list_workflows(state)
    assert result["ok"] is False
    assert "simulated error" in result["error"]


def test_admin_run_workflow_returns_error_on_runtime_failure():
    state = _state_with_failing_client()
    result = control_center._admin_run_workflow(state, "user.test", {"inputs": {}})
    assert result["ok"] is False


def test_admin_cancel_workflow_run_returns_error_on_runtime_failure():
    state = _state_with_failing_client()
    result = control_center._admin_cancel_workflow_run(state, "run-xyz")
    assert result["ok"] is False


def test_admin_list_job_kinds_returns_error_on_runtime_failure():
    state = _state_with_failing_client()
    result = control_center._admin_list_job_kinds(state)
    assert result["ok"] is False
