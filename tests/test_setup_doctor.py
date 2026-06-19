"""Tests for the Setup Doctor diagnostics."""

import json
import os
from unittest import mock

from fls_pilot import connection, doctor, protocol


def test_python_env():
    findings = doctor.check_python_environment()
    assert len(findings) == 1
    assert findings[0].component == "Python Environment"
    assert findings[0].status == "ok"


@mock.patch("fls_pilot.doctor._check_importable", return_value=True)
def test_core_deps_ok(mock_import):
    findings = doctor.check_core_dependencies()
    assert findings[0].status == "ok"


@mock.patch("fls_pilot.doctor._check_importable", return_value=False)
def test_core_deps_missing(mock_import):
    findings = doctor.check_core_dependencies()
    assert findings[0].status == "failed"
    assert "Missing core dependencies" in findings[0].evidence


@mock.patch("fls_pilot.doctor._check_importable", return_value=False)
def test_optional_deps_missing(mock_import):
    findings = doctor.check_optional_dependencies()
    assert len(findings) == 2
    assert findings[0].status == "manual_check"
    assert findings[1].status == "probe_needed"


@mock.patch("fls_pilot.connection.list_ports")
def test_midi_ports_ok(mock_list):
    mock_list.return_value = {
        "inputs": [protocol.DEFAULT_PORT_FROM_FL],
        "outputs": [protocol.DEFAULT_PORT_TO_FL],
    }
    findings = doctor.check_midi_ports()
    assert findings[0].status == "ok"


@mock.patch("fls_pilot.connection.list_ports")
def test_midi_ports_missing(mock_list):
    mock_list.return_value = {"inputs": [], "outputs": []}
    findings = doctor.check_midi_ports()
    assert findings[0].status == "failed"


def test_mcp_config_defaults():
    config = doctor.resolve_mcp_server_config()
    assert config.transport == "stdio"
    assert config.transport_source == "default"
    assert config.sse_host == "127.0.0.1"
    assert config.sse_port == 8080


@mock.patch.dict(
    os.environ,
    {
        "FLS_PILOT_SERVER_TRANSPORT": "sse",
        "FLS_PILOT_SSE_HOST": "127.0.0.2",
        "FLS_PILOT_SSE_PORT": "9009",
    },
)
def test_mcp_config_env_sources():
    config = doctor.resolve_mcp_server_config()
    assert config.transport == "sse"
    assert config.transport_source == "env: FLS_PILOT_SERVER_TRANSPORT"
    assert config.sse_host == "127.0.0.2"
    assert config.sse_port == 9009


@mock.patch.dict(os.environ, {"FLS_PILOT_SSE_PORT": "bad"})
def test_mcp_config_invalid_sse_port_reported():
    config = doctor.resolve_mcp_server_config()
    findings = doctor.check_mcp_client_hints(config)
    assert config.sse_port is None
    assert any(f.component == "MCP SSE/HTTP Configuration" for f in findings)


@mock.patch.dict(os.environ, {"FLS_PILOT_TRANSPORT": "tcp"})
@mock.patch("fls_pilot.connection.TCPBridge.close", return_value=None)
@mock.patch("fls_pilot.connection.TCPBridge.is_alive", return_value=True)
@mock.patch("fls_pilot.connection.TCPBridge.__init__", return_value=None)
def test_tcp_requires_daemon(mock_init, mock_alive, mock_close):
    findings = doctor.check_tcp_daemon()
    assert findings[0].severity == "blocker"
    assert findings[0].status == "ok"


@mock.patch.dict(os.environ, {"FLS_PILOT_TRANSPORT": "tcp"})
@mock.patch(
    "fls_pilot.connection.TCPBridge.__init__",
    side_effect=ConnectionRefusedError("refused"),
)
def test_daemon_down_tcp_active(mock_init):
    findings = doctor.check_tcp_daemon()
    assert findings[0].severity == "blocker"
    assert findings[0].status == "failed"
    assert "not reachable" in findings[0].evidence


@mock.patch.dict(os.environ, {"FLS_PILOT_TRANSPORT": "midi"})
@mock.patch(
    "fls_pilot.connection.TCPBridge.__init__",
    side_effect=ConnectionRefusedError("refused"),
)
def test_daemon_down_tcp_inactive(mock_init):
    findings = doctor.check_tcp_daemon()
    assert findings[0].severity == "advisory"
    assert findings[0].status == "manual_check"


@mock.patch("fls_pilot.connection.get_bridge")
def test_fl_controller_unreachable(mock_get_bridge):
    mock_get_bridge.side_effect = connection.FLPortMissing("ports missing")
    findings = doctor.check_fl_controller()
    statuses = {f.component: f.status for f in findings}
    assert statuses["FL Studio Controller Script"] == "failed"
    assert statuses["Heartbeat Freshness"] == "probe_needed"
    assert statuses["Read-only Ping/Status"] == "probe_needed"


@mock.patch("fls_pilot.connection.get_bridge")
def test_fl_heartbeat_stale(mock_get_bridge):
    bridge = mock.Mock()
    bridge.heartbeat_age.return_value = 10.0
    bridge.is_alive.return_value = False
    mock_get_bridge.return_value = bridge

    findings = doctor.check_fl_controller()
    statuses = {f.component: f.status for f in findings}
    assert statuses["FL Studio Controller Script"] == "manual_check"
    assert statuses["Heartbeat Freshness"] == "manual_check"
    assert statuses["Read-only Ping/Status"] == "probe_needed"


@mock.patch("fls_pilot.connection.get_bridge")
def test_fl_ping_returns_marker(mock_get_bridge):
    bridge = mock.Mock()
    bridge.heartbeat_age.return_value = 0.1
    bridge.is_alive.return_value = True
    bridge.call.return_value = {"build_marker": "FL24_1_2_3"}
    mock_get_bridge.return_value = bridge

    findings = doctor.check_fl_controller()
    statuses = {f.component: f.status for f in findings}
    ping = next(f for f in findings if f.component == "Read-only Ping/Status")
    assert statuses["FL Studio Controller Script"] == "ok"
    assert statuses["Heartbeat Freshness"] == "ok"
    assert ping.status == "ok"
    assert "FL24_1_2_3" in ping.evidence


@mock.patch("fls_pilot.doctor._run_stdio_mcp_smoke")
def test_stdio_smoke_succeeds(mock_smoke):
    mock_smoke.return_value = {
        "tool_count": 87,
        "resource_count": 7,
        "has_fl_transport": True,
        "has_status_resource": True,
    }
    findings = doctor.check_mcp_stdio_transport()
    assert findings[0].status == "ok"
    assert "protocol ping succeeded" in findings[0].evidence
    assert "read fl://status succeeded" in findings[0].evidence


@mock.patch("fls_pilot.doctor._run_stdio_mcp_smoke", side_effect=RuntimeError("fatal"))
def test_stdio_smoke_fails(mock_smoke):
    findings = doctor.check_mcp_stdio_transport()
    assert findings[0].status == "failed"
    assert "fatal" in findings[0].evidence


@mock.patch("fls_pilot.doctor._run_sse_mcp_smoke")
def test_sse_smoke_succeeds(mock_smoke):
    mock_smoke.return_value = {
        "tool_count": 87,
        "resource_count": 7,
        "has_fl_transport": True,
        "has_status_resource": True,
    }
    config = doctor.resolve_mcp_server_config(server_transport="sse", sse_port=9010)
    findings = doctor.check_mcp_sse_transport(config)
    assert findings[0].status == "ok"
    assert "127.0.0.1:9010" in findings[0].evidence
    assert "read fl://status succeeded" in findings[0].evidence


@mock.patch("fls_pilot.doctor._run_sse_mcp_smoke", side_effect=OSError("in use"))
def test_sse_smoke_port_unavailable(mock_smoke):
    config = doctor.resolve_mcp_server_config(server_transport="sse", sse_port=9010)
    findings = doctor.check_mcp_sse_transport(config)
    assert findings[0].status == "failed"
    assert "in use" in findings[0].evidence


def test_json_stable_keys():
    finding = doctor.Finding("test", "blocker", "ok", "ev", "rem", "conf")
    data = json.loads(doctor.format_json([finding]))
    assert len(data) == 1
    assert data[0]["component"] == "test"
    assert data[0]["severity"] == "blocker"
    assert data[0]["status"] == "ok"
    assert data[0]["evidence"] == "ev"
    assert data[0]["remediation"] == "rem"
    assert data[0]["config_source"] == "conf"


def _ok(component: str, severity: str = "blocker") -> list[doctor.Finding]:
    return [doctor.Finding(component, severity, "ok", "evidence", "", "src")]


def _fail(component: str, severity: str = "blocker") -> list[doctor.Finding]:
    return [doctor.Finding(component, severity, "failed", "evidence", "", "src")]


def _manual(component: str, severity: str = "warning") -> list[doctor.Finding]:
    return [doctor.Finding(component, severity, "manual_check", "evidence", "", "src")]


def _p(name: str, **kw):  # noqa: ANN001, ANN202
    return mock.patch(f"fls_pilot.doctor.{name}", **kw)


# ---------------------------------------------------------------------------
# FL Studio application probe unit tests
# ---------------------------------------------------------------------------


@mock.patch("subprocess.run")
@mock.patch("sys.platform", "darwin")
def test_fl_studio_application_detected(mock_run):
    mock_run.return_value = mock.Mock(
        returncode=0,
        stdout="12345 /Applications/FL Studio.app/Contents/MacOS/FL Studio\n",
        stderr="",
    )
    findings = doctor.check_fl_studio_application()
    assert len(findings) == 1
    assert findings[0].component == "FL Studio Application"
    assert findings[0].status == "ok"
    assert findings[0].severity == "blocker"


@mock.patch("subprocess.run")
@mock.patch("sys.platform", "darwin")
def test_fl_studio_application_missing_is_blocker(mock_run):
    mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="")
    findings = doctor.check_fl_studio_application()
    assert len(findings) == 1
    assert findings[0].status == "failed"
    assert findings[0].severity == "blocker"
    assert "Open FL Studio" in findings[0].remediation


@mock.patch(
    "subprocess.run",
    side_effect=OSError("pgrep not found"),
)
@mock.patch("sys.platform", "darwin")
def test_fl_studio_application_unknown_is_manual_check(mock_run):
    findings = doctor.check_fl_studio_application()
    assert len(findings) == 1
    assert findings[0].status == "manual_check"
    assert findings[0].severity == "warning"


@mock.patch("sys.platform", "linux")
def test_fl_studio_application_unsupported_platform_is_manual_check():
    findings = doctor.check_fl_studio_application()
    assert len(findings) == 1
    assert findings[0].status == "manual_check"
    assert findings[0].severity == "warning"



def test_orchestration_core_fail_defers_midi_tcp_fl():
    with (
        _p("check_python_environment", return_value=_ok("Python Environment")),
        _p("check_core_dependencies", return_value=_fail("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_fl_studio_application") as mock_app,
        _p("check_midi_ports") as mock_midi,
        _p("check_tcp_daemon") as mock_tcp,
        _p("check_fl_controller") as mock_fl,
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses["MIDI/IAC/loopMIDI Ports"] == "probe_needed"
    assert statuses["TCP Daemon / Bridge"] == "probe_needed"
    assert statuses["FL Studio Controller Script"] == "probe_needed"
    mock_app.assert_not_called()
    mock_midi.assert_not_called()
    mock_tcp.assert_not_called()
    mock_fl.assert_not_called()


def test_orchestration_server_fail_defers_configured_stdio_transport():
    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_fail("MCP Server Entrypoint")),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller", return_value=[]),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_mcp_stdio_transport") as mock_stdio,
        _p("check_mcp_sse_transport") as mock_sse,
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses.get("MCP stdio Transport") == "probe_needed"
    mock_stdio.assert_not_called()
    mock_sse.assert_not_called()


@mock.patch.dict(os.environ, {"FLS_PILOT_SERVER_TRANSPORT": "sse"})
def test_orchestration_respects_sse_transport_env():
    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller", return_value=[]),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_mcp_stdio_transport") as mock_stdio,
        _p("check_mcp_sse_transport", return_value=[]) as mock_sse,
    ):
        doctor.run_all_checks()
    mock_stdio.assert_not_called()
    mock_sse.assert_called_once()


def test_orchestration_all_transports_runs_stdio_and_sse():
    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller", return_value=[]),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_mcp_stdio_transport", return_value=[]) as mock_stdio,
        _p("check_mcp_sse_transport", return_value=[]) as mock_sse,
    ):
        doctor.run_all_checks(all_transports=True)
    mock_stdio.assert_called_once()
    mock_sse.assert_called_once()


@mock.patch.dict(os.environ, {"FLS_PILOT_TRANSPORT": "midi"})
def test_orchestration_midi_fail_defers_fl_controller():
    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_fail("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_fl_controller") as mock_fl,
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses.get("FL Studio Controller Script") == "probe_needed"
    mock_fl.assert_not_called()


@mock.patch.dict(os.environ, {"FLS_PILOT_TRANSPORT": "tcp"})
def test_orchestration_tcp_fail_defers_fl_controller():
    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=_fail("TCP Daemon / Bridge")),
        _p("check_piano_roll_bridge", return_value=[]),
        _p("check_fl_controller") as mock_fl,
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses.get("FL Studio Controller Script") == "probe_needed"
    mock_fl.assert_not_called()


def test_orchestration_tcp_mode_uses_explicit_daemon_and_advisory_local_midi():
    bridge = mock.Mock()
    bridge.heartbeat_age.return_value = 0.1
    bridge.is_alive.return_value = True
    bridge.call.return_value = {"build_marker": "TCP_TEST"}

    with (
        _p("check_python_environment", return_value=[]),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p(
            "check_midi_ports",
            return_value=[
                doctor.Finding(
                    "MIDI/IAC/loopMIDI Ports",
                    "advisory",
                    "manual_check",
                    "local MIDI not visible",
                    "",
                    "test",
                )
            ],
        ) as mock_midi,
        _p("check_tcp_daemon", return_value=_ok("TCP Daemon / Bridge")) as mock_tcp,
        _p("check_piano_roll_bridge", return_value=[]),
        mock.patch("fls_pilot.doctor.connection.TCPBridge", return_value=bridge) as mock_bridge,
    ):
        findings = doctor.run_all_checks(
            bridge_transport="tcp",
            tcp_host="127.0.0.2",
            tcp_port=9791,
        )

    statuses = {f.component: f.status for f in findings}
    ping = next(f for f in findings if f.component == "Read-only Ping/Status")
    tcp_config = mock_tcp.call_args.args[0]
    mock_midi.assert_called_once_with(severity="advisory", failed_status="manual_check")
    assert tcp_config.host == "127.0.0.2"
    assert tcp_config.port == 9791
    mock_bridge.assert_called_once_with("127.0.0.2", 9791)
    assert statuses["MIDI/IAC/loopMIDI Ports"] == "manual_check"
    assert statuses["FL Studio Controller Script"] == "ok"
    assert ping.status == "ok"
    assert "TCP_TEST" in ping.evidence


def test_orchestration_all_ok_no_deferrals():
    with (
        _p("check_python_environment", return_value=_ok("Python Environment")),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]) as mock_stdio,
        _p("check_fl_studio_application", return_value=_ok("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller", return_value=[]) as mock_fl,
        _p("check_piano_roll_bridge", return_value=[]),
    ):
        findings = doctor.run_all_checks()

    assert not any(f.status == "probe_needed" for f in findings)
    mock_stdio.assert_called_once()
    mock_fl.assert_called_once()


# ---------------------------------------------------------------------------
# FL Studio app probe gate orchestration tests
# ---------------------------------------------------------------------------


def test_orchestration_fl_app_missing_defers_controller():
    """When FL Studio is confirmed not running, controller check is skipped."""
    with (
        _p("check_python_environment", return_value=_ok("Python Environment")),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_fl_studio_application", return_value=_fail("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller") as mock_fl,
        _p("check_piano_roll_bridge", return_value=[]),
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses["FL Studio Application"] == "failed"
    assert statuses["FL Studio Controller Script"] == "probe_needed"
    assert "FL Studio application is not running" in next(
        f.evidence for f in findings if f.component == "FL Studio Controller Script"
    )
    mock_fl.assert_not_called()


def test_orchestration_fl_app_unknown_does_not_block_controller():
    """When the app probe is uncertain (manual_check), controller still runs."""
    with (
        _p("check_python_environment", return_value=_ok("Python Environment")),
        _p("check_core_dependencies", return_value=_ok("Core Dependencies")),
        _p("check_optional_dependencies", return_value=[]),
        _p("check_mcp_client_hints", return_value=[]),
        _p("check_mcp_server_entrypoint", return_value=_ok("MCP Server Entrypoint")),
        _p("check_mcp_stdio_transport", return_value=[]),
        _p("check_fl_studio_application", return_value=_manual("FL Studio Application")),
        _p("check_midi_ports", return_value=_ok("MIDI/IAC/loopMIDI Ports")),
        _p("check_tcp_daemon", return_value=[]),
        _p("check_fl_controller", return_value=[]) as mock_fl,
        _p("check_piano_roll_bridge", return_value=[]),
    ):
        findings = doctor.run_all_checks()

    statuses = {f.component: f.status for f in findings}
    assert statuses["FL Studio Application"] == "manual_check"
    mock_fl.assert_called_once()
