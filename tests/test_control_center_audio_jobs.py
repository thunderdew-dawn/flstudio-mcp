from __future__ import annotations

import io
import json
from unittest import mock

from fls_pilot import control_center


def _state() -> control_center.ControlCenterState:
    return control_center.ControlCenterState(
        host="127.0.0.1",
        port=0,
        sse_host="127.0.0.1",
        sse_port=8080,
    )


class FakeRuntimeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.job = {
            "contract_version": "fls-pilot.runtime-job.v1",
            "job_id": "job_audio",
            "kind": "audio.features",
            "status": "succeeded",
            "progress": 1.0,
            "input_summary": {"source_basename": "mix.wav"},
            "result_ref": {
                "kind": "audio_features",
                "artifact_id": "artifact_audio",
                "summary": {"integrated_lufs": -12.4},
            },
        }

    def submit_job(self, kind, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append(("submit", (kind, kwargs)))
        return dict(self.job, status="queued", progress=0.0)

    def list_jobs(self, **kwargs):  # noqa: ANN003
        self.calls.append(("list", kwargs))
        return [dict(self.job)]

    def job_status(self, job_id):  # noqa: ANN001
        self.calls.append(("status", job_id))
        return dict(self.job)

    def cancel_job(self, job_id):  # noqa: ANN001
        self.calls.append(("cancel", job_id))
        return dict(self.job, status="cancelled")

    def job_result(self, job_id):  # noqa: ANN001
        self.calls.append(("result", job_id))
        return dict(self.job)

    def run_workflow(self, workflow_id, *, inputs=None):  # noqa: ANN001
        self.calls.append(("workflow", (workflow_id, inputs)))
        return {
            "contract_version": "fls-pilot.analysis-report.v1",
            "workflow": workflow_id,
            "report_id": "report_audio",
        }


def test_audio_analysis_actions_use_canonical_runtime_jobs(monkeypatch) -> None:
    state = _state()
    client = FakeRuntimeClient()
    monkeypatch.setattr(control_center, "_runtime_client", lambda current: client)
    monkeypatch.setattr(
        control_center,
        "build_audio_job_request",
        lambda path: {
            "kind": "audio.features",
            "input": {"path": path, "source_sha256": "abc"},
            "input_summary": {"source_basename": "mix.wav"},
            "idempotency_key": "audio.features:abc:v1:config",
        },
    )

    submitted = control_center._run_audio_analysis_action(
        state,
        {"action": "submit", "path": "/tmp/mix.wav"},
    )
    listed = control_center._run_audio_analysis_action(state, {"action": "list"})
    status = control_center._run_audio_analysis_action(
        state,
        {"action": "status", "job_id": "job_audio"},
    )
    cancelled = control_center._run_audio_analysis_action(
        state,
        {"action": "cancel", "job_id": "job_audio"},
    )

    assert submitted["job"]["status"] == "queued"
    assert listed["jobs"][0]["kind"] == "audio.features"
    assert status["job"]["status"] == "succeeded"
    assert cancelled["job"]["status"] == "cancelled"
    assert client.calls[0][0] == "submit"


def test_audio_result_links_project_evidence_only_when_requested(monkeypatch) -> None:
    state = _state()
    client = FakeRuntimeClient()
    monkeypatch.setattr(control_center, "_runtime_client", lambda current: client)

    unlinked = control_center._run_audio_analysis_action(
        state,
        {"action": "result", "job_id": "job_audio"},
    )
    linked = control_center._run_audio_analysis_action(
        state,
        {
            "action": "result",
            "job_id": "job_audio",
            "link_evidence": True,
            "evidence_kind": "rendered_master",
            "workflow_targets": ["mix_review", "low_end_analysis"],
            "confirmed_by_user": True,
        },
    )

    assert "report" not in unlinked
    assert linked["report"]["contract_version"] == "fls-pilot.analysis-report.v1"
    workflow_call = next(call for call in client.calls if call[0] == "workflow")
    workflow_id, inputs = workflow_call[1]
    assert workflow_id == "audio_evidence"
    assert inputs["artifact_id"] == "artifact_audio"
    assert inputs["workflow_links"] == ["mix_review", "low_end_analysis"]
    assert inputs["confirmed_by_user"] is True


def test_http_audio_analysis_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        control_center,
        "_run_audio_analysis_action",
        lambda state, body: {"ok": True, "action": body["action"]},
    )
    state = _state()
    handler_cls = control_center._handler_factory(state)
    body = json.dumps({"action": "list"}).encode()
    request = (
        b"POST /api/audio-analysis HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"\r\n"
        + body
    )

    class OneShotHandler(handler_cls):
        def setup(self):  # noqa: ANN001
            self.rfile = io.BytesIO(request)
            self.wfile = io.BytesIO()

        def finish(self):  # noqa: ANN001
            pass

    server = mock.Mock()
    server.server_version = "test"
    server.sys_version = ""
    server.timeout = 1
    server._BaseServer__is_shut_down = mock.Mock()
    server._BaseServer__shutdown_request = False

    handler = OneShotHandler(
        request=None,
        client_address=("127.0.0.1", 1234),
        server=server,
    )
    response = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(response.split("\r\n\r\n", 1)[1])

    assert payload == {"ok": True, "action": "list"}
