from __future__ import annotations

import io
import json
import subprocess
from unittest import mock

import pytest

from fls_pilot import control_center, doctor, runtime_config
from fls_pilot.packs import load_pack_manifest
from fls_pilot.workflows.registry import (
    DEFAULT_WORKFLOW_REGISTRY,
    build_effective_workflow_registry,
)


def _finding(component: str, severity: str = "blocker", status: str = "ok") -> doctor.Finding:
    return doctor.Finding(component, severity, status, "evidence", "fix", "source")


def _state(*, port: int = 8766, sse_port: int = 8080) -> control_center.ControlCenterState:
    return control_center.ControlCenterState(
        host="127.0.0.1",
        port=port,
        sse_host="127.0.0.1",
        sse_port=sse_port,
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


def test_state_uses_configured_daemon_endpoint(monkeypatch):
    monkeypatch.setenv("FLS_PILOT_TCP_HOST", "127.0.0.2")
    monkeypatch.setenv("FLS_PILOT_TCP_PORT", "9791")

    state = _state()

    assert state.daemon_host == "127.0.0.2"
    assert state.daemon_port == 9791


def test_control_transport_allows_only_transient_marker_navigation(monkeypatch):
    class FakeTCPBridge:
        def __init__(self, host: str, port: int) -> None:
            self.host = host
            self.port = port
            self.calls: list[tuple[str, dict]] = []
            self.closed = False

        def wait_for_heartbeat(self, timeout: float = 1.0) -> bool:
            return True

        def is_alive(self) -> bool:
            return True

        def call(self, command: str, params: dict | None = None):
            from fls_pilot import protocol

            payload = dict(params or {})
            self.calls.append((command, payload))
            if command == protocol.CMD_JUMP_PLAYLIST_MARKER:
                return {"ok": True, "target": {"index": payload["index"], "name": "DROP #1"}}
            if command == protocol.CMD_GET_PLAY_STATE:
                return {"playing": True, "recording": False}
            if command == protocol.CMD_GET_SONG_POS:
                return {"position_beats": 32.0}
            if command == protocol.CMD_GET_TEMPO:
                return {"bpm": 128.0}
            if command == protocol.CMD_LIST_PLAYLIST_MARKERS:
                return {"state": "live", "total": 1, "markers": [{"index": 0, "name": "DROP #1"}]}
            raise AssertionError(f"unexpected command: {command}")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(control_center, "TCPBridge", FakeTCPBridge)

    payload = control_center._control_transport(
        _state(),
        {"action": "jump_to_marker", "params": {"index": 0}},
    )

    assert payload["ok"] is True
    assert payload["result"]["target"]["name"] == "DROP #1"
    assert payload["transport"]["markers"]["total"] == 1

    denied = control_center._control_transport(
        _state(),
        {"action": "set_tempo", "params": {"bpm": 130}},
    )
    assert denied["ok"] is False


def test_control_mix_watch_status_is_bridge_free(monkeypatch):
    def fail_bridge(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("status must not open a bridge")

    monkeypatch.setattr(control_center, "TCPBridge", fail_bridge)

    payload = control_center._control_mix_watch(_state(), {"action": "status"})

    assert payload["ok"] is True
    assert "watch" in payload


def test_control_mix_watch_rejects_unknown_action_before_bridge(monkeypatch):
    def fail_bridge(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("invalid actions must not open a bridge")

    monkeypatch.setattr(control_center, "TCPBridge", fail_bridge)

    payload = control_center._control_mix_watch(_state(), {"action": "render"})

    assert payload["ok"] is False
    assert "action must be" in payload["error"]


def test_workflow_inputs_from_body_normalizes_user_decisions() -> None:
    inputs = control_center._workflow_inputs_from_body(
        {
            "inputs": {"unrelated": "ignored by legacy runner"},
            "user_decisions": [
                {
                    "interaction_id": "low_end.confirm_detected_tracks",
                    "decision": "selected",
                    "selected": ["mixer:2"],
                },
                {"interaction_id": "", "decision": "confirmed"},
                "not-a-decision",
            ],
        }
    )

    assert inputs == {
        "unrelated": "ignored by legacy runner",
        "user_decisions": [
            {
                "interaction_id": "low_end.confirm_detected_tracks",
                "interaction_request_id": "low_end.confirm_detected_tracks",
                "decision": "selected",
                "selected": ["mixer:2"],
                "selected_values": ["mixer:2"],
                "selected_value": "mixer:2",
            }
        ],
    }


def test_status_groups_doctor_findings(monkeypatch):
    findings = [
        _finding("Python Environment"),
        _finding("MIDI/IAC/loopMIDI Ports"),
        _finding("FL Studio Controller Script"),
        _finding("Piano Roll MCP_Apply Script", "advisory", "manual_check"),
    ]
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    state = _state()

    status = control_center.collect_status(state)

    assert status["control_center"]["port"] == 8766
    assert status["groups"]["midi"][0]["component"] == "MIDI/IAC/loopMIDI Ports"
    assert status["groups"]["mcp_apply"][0]["status"] == "manual_check"
    assert status["readiness"]["read_only_review_ready"] is True


def test_status_groups_fl_studio_application_separately(monkeypatch):
    """FL Studio Application finding must land in the fl_app group, not controller."""
    findings = [
        _finding("FL Studio Application", "blocker", "failed"),
        _finding("FL Studio Controller Script", "blocker", "probe_needed"),
    ]
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    state = _state()

    status = control_center.collect_status(state)

    assert status["groups"]["fl_app"][0]["component"] == "FL Studio Application"
    assert not any(
        f["component"] == "FL Studio Application" for f in status["groups"]["controller"]
    )
    assert not any(f["component"] == "FL Studio Application" for f in status["groups"]["other"])


def test_setup_guidance_prompts_to_open_fl_studio():
    """Open FL Studio card must appear and precede the controller card."""
    groups = {
        "environment": [],
        "fl_app": [_finding("FL Studio Application", "blocker", "failed").to_dict()],
        "midi": [],
        "controller": [
            _finding("FL Studio Controller Script", "blocker", "probe_needed").to_dict()
        ],
        "daemon": [],
        "mcp_stdio": [],
        "mcp_sse": [],
        "mcp_apply": [],
        "optional_dependencies": [],
        "other": [],
    }

    guidance = control_center._setup_guidance(
        groups=groups,
        readiness={},
        processes={"daemon": {"state": "running", "running": True}},
        ports={"daemon": {"host": "127.0.0.1", "selected_port": 9787}},
        daemon_autostart={"state": "started", "message": "Started."},
        sse_probe={},
    )

    titles = [item["title"] for item in guidance]
    assert "Open FL Studio" in titles
    open_idx = titles.index("Open FL Studio")
    fl_app_items = [item for item in guidance if item["title"] == "Open FL Studio"]
    assert len(fl_app_items) == 1
    assert fl_app_items[0]["action_path"] == "/api/refresh"
    assert fl_app_items[0]["action_label"] == "Re-check"
    # Controller card (if present) must come after the Open FL Studio card.
    for i, item in enumerate(guidance):
        if item["title"] == "Connect FL Studio to the controller":
            assert i > open_idx


def test_ui_payload_surfaces_catalog_next_action_and_service_actions():
    payload = control_center._ui_payload(
        status_report={"bridge": {"state": "live"}},
        readiness={"read_only_review_ready": True},
        processes={
            "daemon": {"state": "running", "running": True},
            "sse": {"state": "external"},
        },
        ports={
            "daemon": {"host": "127.0.0.1", "selected_port": 9787},
            "sse": {"host": "127.0.0.1", "selected_port": 8080},
        },
    )

    catalog = {item["id"]: item for item in payload["workflow_catalog"]}
    assert catalog["mix_review"]["enabled"] is True
    assert catalog["preflight"]["enabled"] is True
    assert catalog["preflight"]["endpoint"] == "/api/workflows/preflight"
    assert catalog["audio_evidence"]["enabled"] is True
    assert catalog["audio_evidence"]["endpoint"] == "/api/audio-analysis"
    assert catalog["plugin_assistant"]["enabled"] is False
    assert catalog["plugin_assistant"]["endpoint"] is None
    assert catalog["jam_2_project"]["group"] == "Roadmap"
    assert payload["next_action"]["target_panel"] == "producer_health"
    assert payload["next_action"]["action_label"] == "Open Health"
    assert payload["service_actions"]["daemon"]["stop"]["enabled"] is True
    assert payload["service_actions"]["sse"]["external"] is True
    assert payload["service_actions"]["sse"]["stop"]["enabled"] is False


def test_ui_payload_uses_effective_workflow_registry_metadata() -> None:
    manifest = load_pack_manifest(
        {
            "pack_id": "genre.house",
            "version": "1.0.0",
            "title": "House Pack",
            "publisher": "FLS Pilot",
            "min_app_version": "3.0.0b3",
            "workflows": [
                {
                    "workflow_id": "low_end_analysis",
                    "profiles": ["house"],
                    "metadata": {"genre": "house"},
                }
            ],
            "rulesets": [],
            "profiles": [{"id": "house", "title": "House"}],
            "entitlement": {"kind": "pro"},
            "metadata": {},
        }
    )
    registry = build_effective_workflow_registry(
        DEFAULT_WORKFLOW_REGISTRY,
        (manifest,),
    )

    payload = control_center._ui_payload(
        status_report={"bridge": {"state": "live"}},
        readiness={"read_only_review_ready": True},
        processes={
            "daemon": {"state": "running", "running": True},
            "sse": {"state": "external"},
        },
        ports={
            "daemon": {"host": "127.0.0.1", "selected_port": 9787},
            "sse": {"host": "127.0.0.1", "selected_port": 8080},
        },
        workflow_registry=registry,
    )

    catalog = {item["id"]: item for item in payload["workflow_catalog"]}
    extension = catalog["low_end_analysis"]["metadata"]["pack_extensions"][0]
    assert extension["pack_id"] == "genre.house"
    assert extension["profiles"][0]["id"] == "house"
    assert extension["entitlement"]["kind"] == "pro"
    assert catalog["low_end_analysis"]["endpoint"] == "/api/workflows/low-end-analysis"


def test_status_uses_selected_tcp_endpoint_for_doctor_and_status(monkeypatch):
    findings = [
        _finding("TCP Daemon / Bridge"),
        _finding("FL Studio Controller Script"),
    ]
    doctor_calls = []
    status_calls = []

    class FakeTCPBridge:
        def __init__(self, host, port):  # noqa: ANN001
            self.host = host
            self.port = port

    def fake_run_all_checks(**kwargs):  # noqa: ANN003, ANN202
        doctor_calls.append(kwargs)
        return findings

    def fake_status_snapshot(**kwargs):  # noqa: ANN003, ANN202
        bridge = kwargs["bridge_factory"]()
        status_calls.append((bridge.host, bridge.port))
        return {"bridge": {"state": "live"}, "project": {}}

    monkeypatch.setattr(control_center.doctor, "run_all_checks", fake_run_all_checks)
    monkeypatch.setattr(control_center, "collect_status_report", fake_status_snapshot)
    monkeypatch.setattr(control_center, "TCPBridge", FakeTCPBridge)
    state = _state()
    state.daemon_fallback_port = 9788

    control_center.collect_status(state)

    assert doctor_calls[0]["bridge_transport"] == "tcp"
    assert doctor_calls[0]["tcp_host"] == "127.0.0.1"
    assert doctor_calls[0]["tcp_port"] == 9788
    assert status_calls == [("127.0.0.1", 9788)]


def test_status_autostarts_daemon_when_environment_is_ready(monkeypatch):
    findings = [
        _finding("Python Environment"),
        _finding("Core Dependencies"),
        _finding("TCP Daemon / Bridge", "blocker", "failed"),
    ]
    spawned: dict = {}
    health_calls = []

    def fake_health(host, port):  # noqa: ANN001, ANN202
        health_calls.append((host, port))
        return {"reachable": bool(spawned)}

    def fake_spawn(name, args, env):  # noqa: ANN001, ANN202
        spawned["name"] = name
        spawned["args"] = args
        spawned["env"] = env
        process = mock.Mock(spec=subprocess.Popen)
        process.pid = 123
        process.poll.return_value = None
        return control_center.ManagedProcess(
            name=name,
            args=args,
            env=env,
            process=process,
            started_at="now",
        )

    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    monkeypatch.setattr(control_center, "_daemon_health", fake_health)
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
    monkeypatch.setattr(control_center, "_spawn", fake_spawn)
    monkeypatch.setattr(
        control_center,
        "collect_status_report",
        lambda **_: {"bridge": {"state": "unavailable"}, "project": {}},
    )
    state = _state()

    status = control_center.collect_status(state)

    assert spawned["name"] == "daemon"
    assert spawned["env"]["FLS_PILOT_TCP_PORT"] == "9787"
    assert status["automation"]["daemon_autostart"]["state"] == "started"
    assert status["processes"]["daemon"]["state"] == "running"
    assert health_calls[0] == ("127.0.0.1", 9787)


def test_daemon_startup_guidance_is_not_ok_when_daemon_stopped():
    groups = {
        "daemon": [
            _finding("TCP Daemon / Bridge", "blocker", "failed").to_dict(),
        ],
    }

    guidance = control_center._setup_guidance(
        groups=groups,
        readiness={},
        processes={"daemon": {"state": "stopped"}},
        ports={"daemon": {"host": "127.0.0.1", "selected_port": 9787}},
        daemon_autostart={"state": "started", "message": "Started daemon on port 9787."},
        sse_probe={},
    )

    daemon_items = [item for item in guidance if item["title"] == "Daemon startup"]
    assert len(daemon_items) == 1
    assert daemon_items[0]["status"] == "action needed"
    assert daemon_items[0]["action_path"] == "/api/process/daemon/start"
    assert "not running" in daemon_items[0]["text"]


def test_setup_guidance_prioritizes_midi_manual_action(monkeypatch):
    findings = [
        _finding("Python Environment"),
        _finding("Core Dependencies"),
        _finding("TCP Daemon / Bridge"),
        _finding("MIDI/IAC/loopMIDI Ports", "blocker", "failed"),
    ]
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    monkeypatch.setattr(control_center, "_daemon_health", lambda host, port: {"reachable": True})
    monkeypatch.setattr(
        control_center,
        "collect_status_report",
        lambda **_: {"bridge": {"state": "unavailable"}, "project": {}},
    )
    state = _state()

    status = control_center.collect_status(state)

    midi_guidance = next(
        item for item in status["setup_guidance"] if item["checkpoint"] == "created_midi_ports"
    )
    assert midi_guidance["title"] == "Create MIDI loopback ports"
    assert midi_guidance["groups"] == ["midi"]


def test_status_visualizes_running_sse_probe_in_guided_setup(monkeypatch):
    findings = [
        _finding("Python Environment"),
        _finding("Core Dependencies"),
        _finding("TCP Daemon / Bridge"),
    ]

    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 234
    process.poll.return_value = None
    state = _state()
    state.processes["sse"] = control_center.ManagedProcess(
        name="sse",
        args=["fls-pilot", "--sse"],
        env={},
        process=process,
        started_at="now",
    )

    def fake_probe(probe_state):  # noqa: ANN001, ANN202
        probe_state.sse_probe = control_center._sse_probe_state(
            "ok",
            "SSE MCP connection test passed at http://127.0.0.1:8080/sse.",
            probe_state.sse_host,
            probe_state.sse_port,
            checked_at="now",
            result={"tool_count": 1, "resource_count": 1},
        )
        return dict(probe_state.sse_probe)

    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    monkeypatch.setattr(control_center, "_daemon_health", lambda host, port: {"reachable": True})
    monkeypatch.setattr(control_center, "_probe_sse_connection", fake_probe)
    monkeypatch.setattr(
        control_center,
        "collect_status_report",
        lambda **_: {"bridge": {"state": "unavailable"}, "project": {}},
    )

    status = control_center.collect_status(state)

    assert status["mcp"]["sse_probe"]["state"] == "ok"
    assert status["processes"]["sse"]["probe"]["state"] == "ok"
    assert any(
        item["title"] == "MCP SSE connection" and item["status"] == "OK"
        for item in status["setup_guidance"]
    )


def test_manual_checkpoint_is_user_confirmed(monkeypatch):
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: [])
    state = _state()

    result = control_center._confirm_step(state, "ran_mcp_apply")

    assert result["checkpoints"]["ran_mcp_apply"]["status"] == "user_confirmed"
    assert result["readiness"]["write_tools_ready"] is True


def test_client_snippets_use_selected_sse_port():
    state = _state(sse_port=8091)

    snippets = control_center.client_snippets(state)

    assert snippets["chatgpt"]["url"] == "http://localhost:8091/sse"
    assert snippets["claude"]["mcpServers"]["fls-pilot"]["env"]["FLS_PILOT_TRANSPORT"] == "tcp"


def test_client_snippets_use_daemon_fallback_port():
    state = _state()
    state.daemon_fallback_port = 9788

    snippets = control_center.client_snippets(state)

    assert snippets["claude"]["mcpServers"]["fls-pilot"]["env"]["FLS_PILOT_TCP_PORT"] == "9788"
    assert "9788" in snippets["terminal"]["daemon"]
    assert "FLS_PILOT_TCP_PORT=9788" in snippets["terminal"]["sse"]


def test_runtime_client_follows_selected_daemon_fallback_port(monkeypatch):
    state = _state()
    state.daemon_fallback_port = 9788
    created = []

    class FakeRuntimeClient:
        def __init__(self, host, port):  # noqa: ANN001
            self.host = host
            self.port = port
            created.append((host, port))

    monkeypatch.setattr(control_center, "RuntimeClient", FakeRuntimeClient)

    client = control_center._runtime_client(state)

    assert created == [("127.0.0.1", 9788)]
    assert client is state.runtime_client
    assert client.port == 9788


def test_start_daemon_reports_non_daemon_port_conflict(monkeypatch):
    state = _state()
    monkeypatch.setattr(control_center, "_daemon_health", lambda host, port: {"reachable": False})
    monkeypatch.setattr(
        control_center,
        "tcp_port_status",
        lambda host, port: {"available": False, "fallback_port": 9788},
    )
    monkeypatch.setattr(control_center, "find_available_tcp_port", lambda host, port: 9788)

    result = control_center._start_daemon(state)

    assert result["ok"] is False
    assert result["state"] == "port_conflict"
    assert result["fallback_port"] == 9788
    assert state.daemon_fallback_port == 9788


def test_start_sse_uses_fallback_port_and_safe_args(monkeypatch):
    state = _state()
    state.daemon_fallback_port = 9788
    monkeypatch.setattr(control_center, "find_available_tcp_port", lambda host, port: 8081)
    monkeypatch.setattr(
        control_center,
        "_probe_sse_connection",
        lambda probe_state: control_center._sse_probe_state(
            "ok",
            "SSE MCP connection test passed.",
            probe_state.sse_host,
            probe_state.sse_port,
        ),
    )
    spawned: dict = {}

    def fake_spawn(name, args, env):  # noqa: ANN001, ANN202
        spawned["name"] = name
        spawned["args"] = args
        spawned["env"] = env
        process = mock.Mock(spec=subprocess.Popen)
        process.pid = 123
        process.poll.return_value = None
        return control_center.ManagedProcess(
            name=name,
            args=args,
            env=env,
            process=process,
            started_at="now",
        )

    monkeypatch.setattr(control_center, "_spawn", fake_spawn)

    result = control_center._start_sse(state)

    assert result["url"] == "http://localhost:8081/sse"
    assert state.sse_port == 8081
    assert spawned["args"][-2:] == ["--port", "8081"]
    assert spawned["env"]["FLS_PILOT_TRANSPORT"] == "tcp"
    assert spawned["env"]["FLS_PILOT_TCP_HOST"] == "127.0.0.1"
    assert spawned["env"]["FLS_PILOT_TCP_PORT"] == "9788"


def test_start_sse_runs_forced_connection_probe(monkeypatch):
    state = _state()
    monkeypatch.setattr(control_center, "find_available_tcp_port", lambda host, port: 8081)
    probes = []

    def fake_probe(probe_state):  # noqa: ANN001, ANN202
        probes.append((probe_state.sse_host, probe_state.sse_port))
        probe_state.sse_probe = control_center._sse_probe_state(
            "ok",
            "SSE MCP connection test passed.",
            probe_state.sse_host,
            probe_state.sse_port,
        )
        return dict(probe_state.sse_probe)

    def fake_spawn(name, args, env):  # noqa: ANN001, ANN202
        process = mock.Mock(spec=subprocess.Popen)
        process.pid = 123
        process.poll.return_value = None
        return control_center.ManagedProcess(
            name=name,
            args=args,
            env=env,
            process=process,
            started_at="now",
        )

    monkeypatch.setattr(control_center, "_spawn", fake_spawn)
    monkeypatch.setattr(control_center, "_probe_sse_connection", fake_probe)

    result = control_center._start_sse(state)

    assert probes == [("127.0.0.1", 8081)]
    assert result["probe"]["state"] == "ok"
    assert state.sse_probe["state"] == "ok"


def test_start_daemon_uses_configured_endpoint_and_child_env(monkeypatch):
    state = _state()
    state.daemon_host = "127.0.0.2"
    state.daemon_port = 9791
    health_calls = []
    spawned: dict = {}

    monkeypatch.setattr(
        control_center,
        "_daemon_health",
        lambda host, port: health_calls.append((host, port)) or {"reachable": False},
    )
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

    def fake_spawn(name, args, env):  # noqa: ANN001, ANN202
        spawned["name"] = name
        spawned["args"] = args
        spawned["env"] = env
        process = mock.Mock(spec=subprocess.Popen)
        process.pid = 123
        process.poll.return_value = None
        return control_center.ManagedProcess(
            name=name,
            args=args,
            env=env,
            process=process,
            started_at="now",
        )

    monkeypatch.setattr(control_center, "_spawn", fake_spawn)

    result = control_center._start_daemon(state)

    assert result["ok"] is True
    assert health_calls == [("127.0.0.2", 9791)]
    assert spawned["env"]["FLS_PILOT_TCP_HOST"] == "127.0.0.2"
    assert spawned["env"]["FLS_PILOT_TCP_PORT"] == "9791"


def test_process_status_checks_selected_daemon_fallback(monkeypatch):
    state = _state()
    state.daemon_fallback_port = 9788
    calls = []

    monkeypatch.setattr(
        control_center,
        "_daemon_health",
        lambda host, port: calls.append((host, port)) or {"reachable": True},
    )

    status = control_center._process_status(state)

    assert calls == [("127.0.0.1", 9788)]
    assert status["daemon"]["state"] == "external"


def test_process_status_reclassifies_exited_daemon_when_external_daemon_is_reachable(
    monkeypatch,
):
    state = _state()
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 123
    process.poll.return_value = 1
    state.processes["daemon"] = control_center.ManagedProcess(
        name="daemon",
        args=["fls-pilot-daemon"],
        env={},
        process=process,
        started_at="now",
    )
    monkeypatch.setattr(
        control_center,
        "_daemon_health",
        lambda host, port: {"reachable": True},
    )

    status = control_center._process_status(state)

    assert status["daemon"]["state"] == "external"
    assert status["daemon"]["health"]["reachable"] is True


def test_setup_report_redacts_home(monkeypatch):
    home_text = str(control_center.Path.home())
    findings = [doctor.Finding("Python Environment", "blocker", "ok", home_text, "", "source")]
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: findings)
    state = _state()

    report = control_center.setup_report(state)

    assert home_text not in report
    assert "~" in report


def test_setup_report_handles_running_managed_process(monkeypatch):
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: [])
    monkeypatch.setattr(control_center, "_daemon_health", lambda host, port: {"reachable": False})
    monkeypatch.setattr(control_center, "can_bind_tcp", lambda host, port: True)
    state = _state()
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 123
    process.poll.return_value = None
    state.processes["sse"] = control_center.ManagedProcess(
        name="sse",
        args=["fls-pilot", "--sse"],
        env={},
        process=process,
        started_at="now",
    )

    report = control_center.setup_report(state)

    assert "- sse: running" in report


def test_port_state_uses_selected_sse_port(monkeypatch):
    monkeypatch.setattr(control_center, "can_bind_tcp", lambda host, port: False)
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
    state = _state(sse_port=8081)

    ports = control_center._port_state(state)

    assert ports["sse"]["selected_port"] == 8081
    assert ports["sse"]["fallback_port"] == 8081


def test_port_state_reports_configured_daemon_port(monkeypatch):
    monkeypatch.setattr(control_center, "can_bind_tcp", lambda host, port: port == 9791)
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
    state = _state()
    state.daemon_host = "127.0.0.2"
    state.daemon_port = 9791

    ports = control_center._port_state(state)

    assert ports["daemon"]["host"] == "127.0.0.2"
    assert ports["daemon"]["preferred_port"] == 9791
    assert ports["daemon"]["available"] is True
    assert ports["daemon"]["selected_port"] == 9791


def test_runtime_port_status_finds_fallback(monkeypatch):
    calls = []

    def fake_can_bind(host, port):  # noqa: ANN001, ANN202
        calls.append((host, port))
        return port == 9002

    monkeypatch.setattr(runtime_config, "can_bind_tcp", fake_can_bind)

    status = runtime_config.tcp_port_status("127.0.0.1", 9000)

    assert status["available"] is False
    assert status["selected_port"] == 9002
    assert status["fallback_port"] == 9002
    assert calls[:3] == [("127.0.0.1", 9000), ("127.0.0.1", 9001), ("127.0.0.1", 9002)]


def test_http_status_endpoint(monkeypatch):
    monkeypatch.setattr(control_center.doctor, "run_all_checks", lambda **_: [])
    state = _state(port=0)
    handler_cls = control_center._handler_factory(state)
    request = b"GET /api/status HTTP/1.1\r\nHost: localhost\r\n\r\n"

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

    handler = OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=server)
    response = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(response.split("\r\n\r\n", 1)[1])
    assert payload["version"]


def test_http_routing_audit_endpoint(monkeypatch):
    monkeypatch.setattr(
        control_center,
        "_run_routing_audit",
        lambda state, **kwargs: {"ok": True, "workflow": "routing_audit", "state": "live"},
    )
    state = _state(port=0)
    handler_cls = control_center._handler_factory(state)
    request = (
        b"POST /api/workflows/routing-audit HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 2\r\n"
        b"\r\n"
        b"{}"
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

    handler = OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=server)
    response = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(response.split("\r\n\r\n", 1)[1])
    assert payload == {"ok": True, "workflow": "routing_audit", "state": "live"}


def test_http_project_organizer_endpoint(monkeypatch):
    monkeypatch.setattr(
        control_center,
        "_run_project_organizer",
        lambda state, **kwargs: {
            "ok": True,
            "workflow": "project_organizer",
            "state": "live",
        },
    )
    state = _state(port=0)
    handler_cls = control_center._handler_factory(state)
    request = (
        b"POST /api/workflows/project-organizer HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 2\r\n"
        b"\r\n"
        b"{}"
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

    handler = OneShotHandler(request=None, client_address=("127.0.0.1", 1234), server=server)
    response = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(response.split("\r\n\r\n", 1)[1])
    assert payload == {"ok": True, "workflow": "project_organizer", "state": "live"}


def test_http_mix_review_and_low_end_endpoints(monkeypatch):
    monkeypatch.setattr(
        control_center,
        "_run_mix_review",
        lambda state, **kwargs: {"ok": True, "workflow": "mix_review", "state": "live"},
    )
    monkeypatch.setattr(
        control_center,
        "_run_low_end_analysis",
        lambda state, **kwargs: {
            "ok": True,
            "workflow": "low_end_analysis",
            "title": "Low-End Analysis",
            "state": "live",
            "analysis": {"workflow": "low_end_analysis"},
            "details": {
                "analysis_report": {"workflow": "low_end_analysis"},
            },
        },
    )
    state = _state(port=0)
    handler_cls = control_center._handler_factory(state)

    def call_endpoint(path: str) -> dict:
        request = (
            f"POST {path} HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: 2\r\n"
            "\r\n"
            "{}"
        ).encode()

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
        return json.loads(response.split("\r\n\r\n", 1)[1])

    expected_by_path = {
        "/api/workflows/mix-review": {"workflow": "mix_review", "title": None},
        "/api/workflows/low-end-analysis": {
            "workflow": "low_end_analysis",
            "title": "Low-End Analysis",
        },
    }
    for path, expected in expected_by_path.items():
        payload = call_endpoint(path)
        assert payload["ok"] is True
        assert payload["state"] == "live"
        assert payload["workflow"] == expected["workflow"]
        if expected["title"]:
            assert payload["title"] == expected["title"]
            assert payload["analysis"]["workflow"] == expected["workflow"]
            assert payload["details"]["analysis_report"]["workflow"] == expected["workflow"]


def test_build_project_organizer_report_surfaces_cleanup_plan():
    report = control_center._build_project_organizer_report(
        channels=[
            {
                "channel": 1,
                "name": "Channel 1",
                "type": {"label": "genplug"},
                "target_mixer_track": 0,
                "target_name": "Master",
            },
            {
                "channel": 2,
                "name": "Lead",
                "type": {"label": "genplug"},
                "target_mixer_track": 5,
                "target_name": "Lead",
            },
        ],
        mixer_tracks=[
            {"i": 0, "name": "Master", "color": 1},
            {"i": 5, "name": "Lead", "color": 2},
            {"i": 6, "name": "Lead", "color": 3},
        ],
        patterns=[
            {"index": 1, "name": "Pattern 1", "color": None},
            {"index": 2, "name": "Drop", "color": 4},
            {"index": 3, "name": "Drop", "color": 5},
        ],
        playlist_tracks=[
            {"index": 1, "name": "Track 1", "color": None, "mute": False},
        ],
        routing=[
            {"i": 0, "name": "Master", "routes_to": []},
            {"i": 5, "name": "Lead", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
        ],
        template_context={},
    )

    assert report["ok"] is True
    assert report["workflow"] == "project_organizer"
    assert report["summary"]["unnamed_channels"] == 1
    assert report["summary"]["routing_cleanup"] == 1
    assert report["summary"]["proposed_changes"] >= 3
    assert any(
        step["tool"] == "fl_apply_project_cleanup_step" for step in report["cleanup_plan"]["steps"]
    )
    assert report["guided"]["next_tool"] == "fl_apply_project_cleanup_step"
    assert report["safety"]["read_only"] is True


def test_build_mix_review_report_summarizes_levels_findings_and_visuals():
    snapshot = {
        "playing": True,
        "levels_valid": True,
        "peak_window": {"source": "sustained_1200ms"},
        "tracks": [
            {
                "index": 0,
                "name": "Master",
                "vol_db": 0.0,
                "peak_db": 0.2,
                "peak_max": 1.02,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [],
            },
            {
                "index": 1,
                "name": "Lead Vox",
                "vol_db": -2.0,
                "peak_db": -0.4,
                "peak_max": 0.95,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [{"slot": 0, "name": "Fruity Parametric EQ 2"}],
                "routes_to": [{"dst": 0, "dst_name": "Master"}],
            },
            {
                "index": 2,
                "name": "Sub Bass",
                "vol_db": -3.0,
                "peak_db": -4.0,
                "peak_max": 0.63,
                "pan": 0.42,
                "stereo_sep": 0.5,
                "plugins": [],
                "routes_to": [{"dst": 0, "dst_name": "Master"}],
            },
            {
                "index": 3,
                "name": "Pad",
                "vol_db": -7.0,
                "peak_db": -18.0,
                "peak_max": 0.12,
                "pan": -0.2,
                "stereo_sep": 0.2,
                "plugins": [],
                "routes_to": [{"dst": 0, "dst_name": "Master"}],
            },
        ],
        "template_context": {},
        "gather_errors": [],
    }

    report = control_center._build_mix_review_report(snapshot)

    assert report["ok"] is True
    assert report["workflow"] == "mix_review"
    assert report["summary"]["master_peak_db"] == 0.2
    assert report["summary"]["hot_tracks"] == 1
    assert report["summary"]["low_end_findings"] >= 2
    assert report["summary"]["health_score"] < 100
    assert {finding["rule"] for finding in report["findings"]} >= {
        "clipping",
        "headroom",
    }
    assert report["proposals"]
    assert report["visuals"]["level_tracks"][0]["name"] == "Master"
    assert report["visuals"]["band_balance"]["bands_pct"]["low"] > 0
    assert any(row["low_end"] for row in report["visuals"]["stereo_tracks"])
    assert any(row["name"] == "Sub Bass" for row in report["details"]["low_end"]["tracks"])
    assert any(track["plugins"] for track in report["details"]["tracks"])


def test_mix_review_user_decision_validates_heuristic_findings():
    snapshot = {
        "playing": True,
        "levels_valid": True,
        "peak_window": {"source": "sustained_1200ms"},
        "tracks": [
            {
                "index": 0,
                "name": "Master",
                "vol_db": 0.0,
                "peak_db": -3.0,
                "peak_max": 0.7,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [],
            },
            {
                "index": 5,
                "name": "Pad",
                "vol_db": -7.0,
                "peak_db": -14.0,
                "peak_max": 0.2,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [{"dst": 0, "dst_name": "Master"}],
            },
        ],
        "template_context": {},
        "gather_errors": [],
    }

    provisional = control_center._build_mix_review_report(snapshot)
    heuristic = next(row for row in provisional["findings"] if row["rule"] == "missing_hpf")
    validated = control_center._build_mix_review_report(
        snapshot,
        user_decisions=(
            {
                "interaction_id": "mix_review.confirm_heuristics",
                "decision": "selected",
                "selected": [heuristic["id"]],
            },
        ),
    )
    finding = next(row for row in validated["findings"] if row["id"] == heuristic["id"])

    assert provisional["interaction_requests"][0]["id"] == "mix_review.confirm_heuristics"
    assert provisional["metadata"]["score_status"] == "provisional"
    assert validated["metadata"]["score_status"] == "final"
    assert validated["metadata"]["blocked_fix_plan_until_confirmed"] is False
    assert finding["severity"] == "info"
    assert finding["metadata"]["human_validation_required"] is False
    assert finding["metadata"]["validated_by_user"] is True
    assert finding["metadata"]["user_intent"] == "intentional"


def test_build_mix_review_report_skips_playback_requirement_for_default_level_1():
    snapshot = {
        "playing": False,
        "levels_valid": False,
        "peak_window": None,
        "tracks": [
            {
                "index": 0,
                "name": "Master",
                "vol_db": 0.0,
                "peak_db": -2.0,
                "peak_max": 0.8,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [],
            },
        ],
        "template_context": {},
        "gather_errors": [],
    }

    legacy_report = control_center._build_mix_review_report(snapshot)
    analysis_report = control_center._generic_analysis_report_from_legacy(
        legacy_report, "mix_review", "Mix Review"
    )
    report = control_center.analysis_report_for_control_center(analysis_report, legacy_report)

    assert report["ok"] is True
    prerequisites = report.get("prerequisites", [])
    assert any(
        req["id"] == "requires_playback" and req["status"] == "skipped"
        for req in prerequisites
    )
    assert "live_meter_window" not in report["coverage"]["missing"]

    level_2_report = control_center._build_mix_review_report(snapshot, options={"level": 2})
    level_2_analysis = control_center._generic_analysis_report_from_legacy(
        level_2_report, "mix_review", "Mix Review"
    )
    level_2_payload = control_center.analysis_report_for_control_center(
        level_2_analysis, level_2_report
    )
    assert any(
        req["id"] == "requires_playback" and req["status"] == "missing"
        for req in level_2_payload.get("prerequisites", [])
    )
    assert "live_meter_window" in level_2_payload["coverage"]["missing"]


def test_direct_live_snapshot_remains_valid_without_watch_evidence():
    snapshot = {
        "playing": True,
        "levels_valid": True,
        "peak_window": {"source": "sustained_1200ms"},
        "live_window": {
            "freshness": "unavailable",
            "limitations": [],
        },
        "tracks": [
            {
                "index": 0,
                "name": "Master",
                "vol_db": 0.0,
                "peak_db": 0.2,
                "peak_max": 1.02,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [],
            },
        ],
        "template_context": {},
        "gather_errors": [],
    }

    legacy_report = control_center._build_mix_review_report(snapshot)
    analysis_report = control_center._generic_analysis_report_from_legacy(
        legacy_report,
        "mix_review",
        "Mix Review",
    )

    assert legacy_report["evidence_mode"] == "short_live_snapshot"
    assert any(row["rule"] == "clipping" for row in legacy_report["findings"])
    assert analysis_report.evidence_mode == "short_live_snapshot"
    assert analysis_report.freshness.status == "fresh"


def test_low_end_analysis_legacy_report_keeps_ui_shape_and_adds_contract():
    snapshot = {
        "playing": True,
        "levels_valid": True,
        "peak_window": {"source": "sustained_1200ms"},
        "tracks": [
            {
                "index": 0,
                "name": "Master",
                "vol_db": 0.0,
                "peak_db": -2.0,
                "peak_max": 0.8,
                "pan": 0.0,
                "stereo_sep": 0.0,
                "plugins": [],
                "routes_to": [],
            },
            {
                "index": 2,
                "name": "Sub Bass",
                "vol_db": -3.0,
                "peak_db": -4.0,
                "peak_max": 0.63,
                "pan": 0.42,
                "stereo_sep": 0.5,
                "plugins": [],
                "routes_to": [{"dst": 0, "dst_name": "Master"}],
            },
        ],
        "template_context": {},
        "gather_errors": [],
    }

    state = control_center.ControlCenterState(
        host="127.0.0.1",
        port=1234,
        sse_host="127.0.0.1",
        sse_port=1235,
    )
    legacy_report = control_center._build_low_end_legacy_report(snapshot)
    report = control_center._store_low_end_report(state, legacy_report)

    assert report["workflow"] == "low_end_analysis"
    assert report["title"] == "Low-End Analysis"
    assert report["details"]["low_end"]["findings"]
    assert report["details"]["low_end"]["tracks"][0]["name"] == "Sub Bass"
    assert report["summary"]["low_end_findings"] >= 2
    assert report["contract_version"] == "fls-pilot.analysis-report.v1"
    assert report["workflow"] == "low_end_analysis"
    assert report["analysis_mode"] == "live_runtime"
    assert report["coverage"]["status"] == "fresh"
    assert report["confidence_score"] > 0
    assert report["findings"][0]["rule_id"].startswith("low_end.")
    assert "analysis_report" not in report["details"]


def test_build_routing_audit_report_summarizes_graph_and_findings():
    channels = [
        {
            "channel": 1,
            "name": "Kick",
            "type": {"label": "genplug"},
            "target_mixer_track": 1,
            "target_name": "Kick",
        },
        {
            "channel": 2,
            "name": "Vocal",
            "type": {"label": "audio"},
            "target_mixer_track": 3,
            "target_name": "Vocal",
        },
        {
            "channel": 3,
            "name": "FX Riser",
            "type": {"label": "audio"},
            "target_mixer_track": 0,
            "target_name": "Master",
        },
        {
            "channel": 4,
            "name": "Pad",
            "type": {"label": "genplug"},
            "target_mixer_track": 2,
            "target_name": "Pad",
        },
    ]
    routing = [
        {"i": 0, "name": "Master", "routes_to": []},
        {"i": 1, "name": "Kick", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
        {"i": 2, "name": "Pad", "routes_to": []},
        {"i": 3, "name": "Vocal", "routes_to": [{"dst": 10, "dst_name": "Vocal Bus"}]},
        {"i": 9, "name": "Insert 9", "routes_to": []},
        {"i": 10, "name": "Vocal Bus", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
    ]

    analysis_report, report = control_center._build_routing_audit_report(
        channels=channels,
        routing=routing,
        unused_mixer_tracks=[{"track": 9, "name": "Insert 9"}],
    )

    assert analysis_report.workflow == "routing_audit"
    assert report["ok"] is True
    assert report["summary"]["direct_to_master"] == 1
    assert report["summary"]["unrouted_channels"] == 1
    assert report["summary"]["dead_end_tracks"] == 1
    assert report["summary"]["unused_mixer_tracks"] == 1
    assert report["summary"]["routes"] == 3
    assert {finding["id"] for finding in report["findings"]} >= {
        "generators_direct_to_master",
        "unrouted_channels",
        "dead_end_tracks",
        "unused_mixer_tracks",
    }

    links = {(link["from"], link["to"], link["kind"]) for link in report["graph"]["links"]}
    assert ("channel:1", "master", "direct") in links
    assert ("channel:2", "track:10", "audio") in links
    assert ("track:10", "master", "audio") in links
    assert ("channel:3", "unrouted", "unrouted") in links
    assert ("channel:4", "dead_end", "dead_end") in links
    assert report["contract_version"] == "fls-pilot.analysis-report.v1"
    assert report["workflow"] == "routing_audit"
    assert report["coverage"]["status"] == "fresh"
    assert report["findings"][0]["rule_id"].startswith("routing.")
    assert "analysis_report" not in report["details"]
    canonical_ids = {
        entity["canonical_id"] for finding in report["findings"] for entity in finding["entities"]
    }
    assert {"channel:1", "mixer:1", "channel:3", "mixer:2", "mixer:9"} <= canonical_ids


def test_build_routing_audit_report_adds_discrepancy_template_and_level2_findings():
    channels = [
        {
            "channel": 1,
            "name": "Kick",
            "type": {"label": "genplug"},
            "target_mixer_track": 2,
            "target_name": "Kick",
            "vol_norm": 0.02,
            "pan": -1.0,
            "mute": True,
            "solo": False,
        },
        {
            "channel": 2,
            "name": "Bass",
            "type": {"label": "genplug"},
            "target_mixer_track": 11,
            "target_name": "Bass",
            "vol_norm": 0.9,
            "pan": 0.0,
            "mute": False,
            "solo": False,
        },
    ]
    mixer_tracks = [
        {
            "i": 0,
            "name": "Master",
            "vol_norm": 0.8,
            "pan": 0.0,
            "mute": False,
            "solo": False,
        },
        {
            "i": 1,
            "name": "Premaster",
            "vol_norm": 0.8,
            "pan": 0.0,
            "mute": False,
            "solo": False,
        },
        {
            "i": 2,
            "name": "Kick",
            "vol_norm": 0.9,
            "pan": 1.0,
            "mute": False,
            "solo": True,
        },
        {
            "i": 10,
            "name": "Kick Bus",
            "vol_norm": 0.9,
            "pan": 0.0,
            "mute": False,
            "solo": False,
        },
        {
            "i": 11,
            "name": "Bass",
            "vol_norm": 0.8,
            "pan": 0.0,
            "mute": False,
            "solo": False,
        },
    ]
    routing = [
        {"i": 0, "name": "Master", "routes_to": []},
        {"i": 1, "name": "Premaster", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
        {"i": 2, "name": "Kick", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
        {"i": 10, "name": "Kick Bus", "routes_to": [{"dst": 1, "dst_name": "Premaster"}]},
        {"i": 11, "name": "Bass", "routes_to": [{"dst": 0, "dst_name": "Master"}]},
    ]

    _analysis_report, report = control_center._build_routing_audit_report(
        channels=channels,
        routing=routing,
        mixer_tracks=mixer_tracks,
        options=control_center.routing_checks.RoutingAuditOptions(
            routing_check_mode=control_center.routing_checks.ROUTING_MODE_LEVEL_2,
            template_compliance=control_center.routing_checks.TEMPLATE_COMPLIANCE_MANUAL,
            selected_template_profile="psytrance",
            playback_decision="manual_playback_running",
            loop_duration_seconds=16,
        ),
        signal_flow={
            "available": True,
            "playback_used": True,
            "active_threshold": 0.00001,
            "track_peaks": {"0": 0.2, "1": 0.0, "2": 0.15, "10": 0.0, "11": 0.0},
            "limitations": [],
        },
    )

    ids = {finding["id"] for finding in report["findings"]}
    assert "channel_mixer_volume_conflict" in ids
    assert "channel_mixer_pan_conflict" in ids
    assert "channel_mixer_mute_conflict" in ids
    assert "channel_mixer_solo_conflict" in ids
    assert "template.source_direct_to_master" in ids
    assert "template.source_bypass_signal_confirmed" in ids
    assert "template.expected_bus_silent_signal_confirmed" in ids
    assert "channel_active_mixer_silent" in ids
    assert "direct_to_master_signal_confirmed" in ids
    assert report["routing_check_level"] == 2
    assert report["evidence_mode"] == "static_snapshot_plus_meter_snapshot"
    assert report["playback_used"] is True
    assert report["template_compliance_summary"]["profile_id"] == "psytrance"
    assert report["details"]["template_status"]["profile_source"] == "manual_select"


def test_main_rejects_non_loopback_host():
    with mock.patch("fls_pilot.control_center.serve_control_center") as serve:
        try:
            control_center.main(["--host", "0.0.0.0"])
        except SystemExit as exc:
            assert exc.code == 2
        else:  # pragma: no cover - defensive
            raise AssertionError("main accepted a non-loopback host")
    serve.assert_not_called()
