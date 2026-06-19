"""Read-only setup diagnostics for FL Studio Pilot.

The Setup Doctor separates MCP transport checks, the optional TCP daemon, MIDI
ports, and the FL Studio controller script so first-run troubleshooting does not
mistake one healthy layer for a fully working installation.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any

from . import __version__, connection, protocol, pyscript_gen
from .runtime_config import DEFAULT_SSE_HOST, DEFAULT_SSE_PORT

FindingStatus = str
FindingSeverity = str

DEFAULT_MCP_SMOKE_TIMEOUT_SECONDS = 35.0
_VALID_MCP_TRANSPORTS = {"stdio", "sse"}


@dataclass
class Finding:
    component: str
    severity: FindingSeverity
    status: FindingStatus
    evidence: str
    remediation: str
    config_source: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class MCPServerConfig:
    transport: str
    transport_source: str
    sse_host: str
    sse_host_source: str
    sse_port: int | None
    sse_port_source: str
    all_transports: bool
    smoke_timeout_seconds: float
    transport_error: str | None = None
    sse_port_error: str | None = None


@dataclass(frozen=True)
class TCPDaemonConfig:
    transport: str
    transport_source: str
    active: bool
    host: str
    host_source: str
    port: int | None
    port_source: str
    port_error: str | None = None


@dataclass(frozen=True)
class FLStudioProcessProbeResult:
    """Result of the read-only FL Studio process presence probe.

    ``found`` is ``True`` when an FL Studio process was detected, ``False``
    when the probe ran successfully but found nothing, and ``None`` when the
    outcome is uncertain (unsupported platform, timeout, or unexpected error).
    """

    found: bool | None
    platform_supported: bool
    evidence: str


def _check_importable(module_name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(module_name) is not None


def _any_blocker_failed(findings: list[Finding]) -> bool:
    """Return True when any blocker-severity check definitively failed."""
    return any(f.severity == "blocker" and f.status == "failed" for f in findings)


def _deferred_finding(component: str, severity: str, reason: str) -> Finding:
    """Return a finding for a check that could not run because a prerequisite failed."""
    return Finding(
        component=component,
        severity=severity,
        status="probe_needed",
        evidence=f"Not run: {reason}",
        remediation="Resolve the prerequisite finding, then rerun Setup Doctor.",
        config_source="orchestrator",
    )


def _source_for_cli_env_default(
    cli_value: object | None,
    env_name: str,
    default_value: object,
    cli_label: str,
) -> tuple[object, str]:
    if cli_value is not None:
        return cli_value, f"cli: {cli_label}"
    if env_name in os.environ:
        return os.environ[env_name], f"env: {env_name}"
    return default_value, "default"


def resolve_mcp_server_config(
    *,
    server_transport: str | None = None,
    sse_host: str | None = None,
    sse_port: int | str | None = None,
    all_transports: bool = False,
    smoke_timeout_seconds: float = DEFAULT_MCP_SMOKE_TIMEOUT_SECONDS,
) -> MCPServerConfig:
    """Resolve MCP server transport settings from CLI values, env, and defaults."""
    raw_transport, transport_source = _source_for_cli_env_default(
        server_transport,
        "FLS_PILOT_SERVER_TRANSPORT",
        "stdio",
        "--server-transport",
    )
    transport = str(raw_transport).strip().lower()
    transport_error = None
    if transport not in _VALID_MCP_TRANSPORTS:
        transport_error = (
            f"Unsupported MCP server transport {raw_transport!r}; expected 'stdio' or 'sse'."
        )
        transport = "stdio"

    raw_host, host_source = _source_for_cli_env_default(
        sse_host,
        "FLS_PILOT_SSE_HOST",
        DEFAULT_SSE_HOST,
        "--sse-host",
    )

    raw_port, port_source = _source_for_cli_env_default(
        sse_port,
        "FLS_PILOT_SSE_PORT",
        DEFAULT_SSE_PORT,
        "--sse-port",
    )
    port_error = None
    try:
        resolved_port = int(raw_port)
        if resolved_port <= 0 or resolved_port > 65535:
            raise ValueError("port must be between 1 and 65535")
    except (TypeError, ValueError) as exc:
        resolved_port = None
        port_error = f"Invalid SSE port {raw_port!r}: {exc}"

    return MCPServerConfig(
        transport=transport,
        transport_source=transport_source,
        sse_host=str(raw_host),
        sse_host_source=host_source,
        sse_port=resolved_port,
        sse_port_source=port_source,
        all_transports=bool(all_transports),
        smoke_timeout_seconds=max(1.0, float(smoke_timeout_seconds)),
        transport_error=transport_error,
        sse_port_error=port_error,
    )


def resolve_tcp_daemon_config(
    *,
    bridge_transport: str | None = None,
    tcp_host: str | None = None,
    tcp_port: int | str | None = None,
) -> TCPDaemonConfig:
    """Resolve bridge TCP daemon settings from explicit values, env, and defaults."""
    raw_transport, transport_source = _source_for_cli_env_default(
        bridge_transport,
        "FLS_PILOT_TRANSPORT",
        "direct",
        "--bridge-transport",
    )
    transport = str(raw_transport).strip().lower()

    raw_host, host_source = _source_for_cli_env_default(
        tcp_host,
        "FLS_PILOT_TCP_HOST",
        connection.DEFAULT_TCP_HOST,
        "--tcp-host",
    )
    raw_port, port_source = _source_for_cli_env_default(
        tcp_port,
        "FLS_PILOT_TCP_PORT",
        connection.DEFAULT_TCP_PORT,
        "--tcp-port",
    )

    port_error = None
    try:
        resolved_port = int(raw_port)
        if resolved_port <= 0 or resolved_port > 65535:
            raise ValueError("port must be between 1 and 65535")
    except (TypeError, ValueError) as exc:
        resolved_port = None
        port_error = f"Invalid FLS_PILOT_TCP_PORT: {raw_port!r}: {exc}"

    return TCPDaemonConfig(
        transport=transport,
        transport_source=transport_source,
        active=transport == "tcp",
        host=str(raw_host),
        host_source=host_source,
        port=resolved_port,
        port_source=port_source,
        port_error=port_error,
    )


def check_python_environment() -> list[Finding]:
    """Check Python version and fls-pilot importability."""
    py_ver = sys.version.split(" ")[0]
    return [
        Finding(
            component="Python Environment",
            severity="blocker",
            status="ok",
            evidence=(f"Python {py_ver}, platform: {platform.platform()}, fls-pilot {__version__}"),
            remediation="",
            config_source="system",
        )
    ]


def check_core_dependencies() -> list[Finding]:
    """Check required runtime dependencies."""
    missing = [dep for dep in ("fastmcp", "mcp", "mido", "rtmidi") if not _check_importable(dep)]
    if missing:
        return [
            Finding(
                component="Core Dependencies",
                severity="blocker",
                status="failed",
                evidence=f"Missing core dependencies: {', '.join(missing)}",
                remediation="Run: pip install fls-pilot",
                config_source="environment",
            )
        ]
    return [
        Finding(
            component="Core Dependencies",
            severity="blocker",
            status="ok",
            evidence="fastmcp, mcp, mido, and python-rtmidi are installed.",
            remediation="",
            config_source="environment",
        )
    ]


def check_optional_dependencies() -> list[Finding]:
    """Check optional extras used by non-core workflows."""
    findings = []

    has_gui = _check_importable("pyautogui")
    if sys.platform == "win32" and not _check_importable("pygetwindow"):
        has_gui = False

    findings.append(
        Finding(
            component="UI Triggers (Piano Roll Apply)",
            severity="advisory",
            status="ok" if has_gui else "manual_check",
            evidence=(
                "pyautogui (+ pygetwindow on Windows) available"
                if has_gui
                else "UI trigger dependencies are not installed."
            ),
            remediation="Run: pip install fls-pilot" if not has_gui else "",
            config_source="environment",
        )
    )

    has_audio = all(_check_importable(m) for m in ("librosa", "soundfile", "numpy", "scipy"))
    findings.append(
        Finding(
            component="Audio Analysis",
            severity="advisory",
            status="ok" if has_audio else "probe_needed",
            evidence=(
                "Audio analysis libraries are installed."
                if has_audio
                else "Audio extras are not installed."
            ),
            remediation="Run: pip install fls-pilot[audio]" if not has_audio else "",
            config_source="environment",
        )
    )

    return findings


# ---------------------------------------------------------------------------
# FL Studio application process probe
# ---------------------------------------------------------------------------

_FL_WINDOWS_NAMES = frozenset(["fl.exe", "fl64.exe", "fl studio.exe"])


def _probe_fl_studio_windows() -> FLStudioProcessProbeResult:
    """Probe for a running FL Studio process on Windows via tasklist."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FLStudioProcessProbeResult(
            found=None,
            platform_supported=True,
            evidence=f"tasklist probe failed: {exc}",
        )

    for line in result.stdout.splitlines():
        # CSV rows: "ImageName","PID","Session","SessionNum","MemUsage"
        image = line.split(",")[0].strip('"').lower()
        if image in _FL_WINDOWS_NAMES or image.startswith("fl studio"):
            return FLStudioProcessProbeResult(
                found=True,
                platform_supported=True,
                evidence=f"FL Studio process detected: {image}",
            )
    return FLStudioProcessProbeResult(
        found=False,
        platform_supported=True,
        evidence="No FL Studio process found in tasklist output.",
    )


def _probe_fl_studio_macos() -> FLStudioProcessProbeResult:
    """Probe for a running FL Studio process on macOS via pgrep."""
    try:
        result = subprocess.run(
            ["pgrep", "-fl", "FL Studio"],
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FLStudioProcessProbeResult(
            found=None,
            platform_supported=True,
            evidence=f"pgrep probe failed: {exc}",
        )

    # pgrep exits 0 when matches found, 1 when none found.
    matching_lines = [
        line
        for line in result.stdout.splitlines()
        if "fl studio" in line.lower()
    ]
    if matching_lines:
        return FLStudioProcessProbeResult(
            found=True,
            platform_supported=True,
            evidence=f"FL Studio process detected: {matching_lines[0]}",
        )
    return FLStudioProcessProbeResult(
        found=False,
        platform_supported=True,
        evidence="No FL Studio process found via pgrep.",
    )


_FL_APP_REMEDIATION = (
    "Open FL Studio, load or create a project, wait until it is responsive, "
    "then rerun Setup Doctor or click Re-check in Control Center."
)


def check_fl_studio_application() -> list[Finding]:
    """Read-only check for a running FL Studio process.

    Uses stdlib subprocess only (no psutil).  Returns ``ok`` when a process is
    found, ``failed`` (blocker) when the probe ran on a supported OS and found
    nothing, or ``manual_check`` (warning) when the outcome is uncertain.
    """
    plat = sys.platform
    if plat == "win32":
        probe = _probe_fl_studio_windows()
    elif plat == "darwin":
        probe = _probe_fl_studio_macos()
    else:
        return [
            Finding(
                component="FL Studio Application",
                severity="warning",
                status="manual_check",
                evidence=(
                    f"Process probe is not implemented for platform {plat!r}. "
                    "Confirm FL Studio is running manually."
                ),
                remediation=_FL_APP_REMEDIATION,
                config_source="system",
            )
        ]

    if probe.found is True:
        return [
            Finding(
                component="FL Studio Application",
                severity="blocker",
                status="ok",
                evidence=probe.evidence,
                remediation="",
                config_source="system",
            )
        ]

    if probe.found is False:
        return [
            Finding(
                component="FL Studio Application",
                severity="blocker",
                status="failed",
                evidence=probe.evidence,
                remediation=_FL_APP_REMEDIATION,
                config_source="system",
            )
        ]

    # found is None — uncertain
    return [
        Finding(
            component="FL Studio Application",
            severity="warning",
            status="manual_check",
            evidence=probe.evidence,
            remediation=_FL_APP_REMEDIATION,
            config_source="system",
        )
    ]


def check_midi_ports(
    *,
    severity: str = "blocker",
    failed_status: str = "failed",
) -> list[Finding]:
    """Check loopMIDI / IAC Driver port availability without changing ports."""
    try:
        ports = connection.list_ports()
    except Exception as exc:
        return [
            Finding(
                component="MIDI/IAC/loopMIDI Ports",
                severity=severity,
                status=failed_status,
                evidence=f"Failed to list MIDI ports: {exc}",
                remediation="Ensure mido and python-rtmidi are installed for this platform.",
                config_source="system",
            )
        ]

    port_to_fl = protocol.port_to_fl_name()
    port_from_fl = protocol.port_from_fl_name()
    out_match = any(port_to_fl.lower() in p.lower() for p in ports["outputs"])
    in_match = any(port_from_fl.lower() in p.lower() for p in ports["inputs"])

    remedy = "Create the configured FLStudioPilot ports in your OS virtual MIDI tool."
    if sys.platform == "darwin":
        remedy = (
            "Open Audio MIDI Setup -> IAC Driver and create ports matching the configured names."
        )
    elif sys.platform == "win32":
        remedy = "Open loopMIDI and create ports matching the configured names."

    if not out_match or not in_match:
        missing = []
        if not out_match:
            missing.append(f"output port {port_to_fl!r}")
        if not in_match:
            missing.append(f"input port {port_from_fl!r}")
        return [
            Finding(
                component="MIDI/IAC/loopMIDI Ports",
                severity=severity,
                status=failed_status,
                evidence=f"Missing expected ports: {', '.join(missing)}",
                remediation=remedy,
                config_source="env: FLS_PILOT_PORT_TO_FL / FLS_PILOT_PORT_FROM_FL",
            )
        ]

    return [
        Finding(
            component="MIDI/IAC/loopMIDI Ports",
            severity=severity,
            status="ok",
            evidence=f"Found output {port_to_fl!r} and input {port_from_fl!r}.",
            remediation="",
            config_source="env: FLS_PILOT_PORT_TO_FL / FLS_PILOT_PORT_FROM_FL",
        )
    ]


def check_tcp_daemon(config: TCPDaemonConfig | None = None) -> list[Finding]:
    """Check the optional TCP daemon/bridge without treating it as the MCP server."""
    config = config or resolve_tcp_daemon_config()
    is_tcp_configured = config.active
    host = config.host
    severity = "blocker" if is_tcp_configured else "advisory"
    failed_status = "failed" if is_tcp_configured else "manual_check"

    if config.port is None:
        return [
            Finding(
                component="TCP Daemon / Bridge",
                severity=severity,
                status=failed_status,
                evidence=config.port_error or "Invalid TCP daemon port.",
                remediation="Set FLS_PILOT_TCP_PORT to a valid integer.",
                config_source=config.port_source,
            )
        ]

    bridge = None
    try:
        bridge = connection.TCPBridge(host, config.port)
        is_alive = bridge.is_alive()
    except OSError as exc:
        return [
            Finding(
                component="TCP Daemon / Bridge",
                severity=severity,
                status=failed_status,
                evidence=(
                    f"Daemon not reachable at {host}:{config.port}. "
                    f"TCP bridge mode active: {is_tcp_configured}. Error: {exc}"
                ),
                remediation=(
                    "Run 'fls-pilot-daemon' in a normal terminal when "
                    "FLS_PILOT_TRANSPORT=tcp is configured."
                ),
                config_source=f"{config.host_source}; {config.port_source}",
            )
        ]
    except Exception as exc:
        return [
            Finding(
                component="TCP Daemon / Bridge",
                severity=severity,
                status=failed_status,
                evidence=f"Daemon health check failed at {host}:{config.port}: {exc}",
                remediation="Check daemon logs and TCP bridge configuration.",
                config_source=f"{config.host_source}; {config.port_source}",
            )
        ]
    finally:
        if bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()

    if not is_alive:
        return [
            Finding(
                component="TCP Daemon / Bridge",
                severity=severity,
                status=failed_status,
                evidence=(
                    f"Daemon responded at {host}:{config.port}, but its FL bridge is "
                    f"not alive. TCP bridge mode active: {is_tcp_configured}."
                ),
                remediation="Check daemon logs, MIDI ports, and FL controller heartbeat.",
                config_source=f"{config.host_source}; {config.port_source}",
            )
        ]

    return [
        Finding(
            component="TCP Daemon / Bridge",
            severity=severity,
            status="ok",
            evidence=f"Daemon responding and bridge alive at {host}:{config.port}.",
            remediation="",
            config_source=f"{config.host_source}; {config.port_source}",
        )
    ]


def _probe_not_run(component: str, reason: str) -> Finding:
    return Finding(
        component=component,
        severity="blocker",
        status="probe_needed",
        evidence=f"Not checked: {reason}",
        remediation="Resolve the FL controller finding, then rerun Setup Doctor.",
        config_source="FL bridge",
    )


def check_fl_controller(
    *,
    bridge_factory: Callable[[], Any] | None = None,
    config_source: str = "FL bridge",
) -> list[Finding]:
    """Check FL Studio controller reachability, heartbeat, and read-only ping."""
    try:
        bridge = bridge_factory() if bridge_factory is not None else connection.get_bridge()
    except connection.FLPortMissing as exc:
        return [
            Finding(
                component="FL Studio Controller Script",
                severity="blocker",
                status="failed",
                evidence=f"Bridge could not open MIDI/TCP path: {exc}",
                remediation="Create/configure the MIDI ports or TCP daemon before checking FL.",
                config_source=config_source,
            ),
            _probe_not_run("Heartbeat Freshness", "bridge path is unavailable."),
            _probe_not_run("Read-only Ping/Status", "bridge path is unavailable."),
        ]
    except Exception as exc:
        return [
            Finding(
                component="FL Studio Controller Script",
                severity="blocker",
                status="failed",
                evidence=f"Bridge initialization error: {exc}",
                remediation="Check daemon, local bridge setup, and Python dependencies.",
                config_source=config_source,
            ),
            _probe_not_run("Heartbeat Freshness", "bridge initialization failed."),
            _probe_not_run("Read-only Ping/Status", "bridge initialization failed."),
        ]

    findings: list[Finding] = []
    try:
        age = bridge.heartbeat_age()
        alive = bridge.is_alive()
        if age is None:
            findings.extend(
                [
                    Finding(
                        component="FL Studio Controller Script",
                        severity="blocker",
                        status="failed",
                        evidence="Bridge opened, but no controller heartbeat was received.",
                        remediation=(
                            "Open FL Studio and assign the FLStudioPilot controller "
                            "script to the configured virtual MIDI ports."
                        ),
                        config_source="FL bridge heartbeat",
                    ),
                    Finding(
                        component="Heartbeat Freshness",
                        severity="blocker",
                        status="failed",
                        evidence="No heartbeat timestamp is available.",
                        remediation=(
                            "Confirm the controller script is installed and loaded in FL Studio."
                        ),
                        config_source="FL bridge heartbeat",
                    ),
                    _probe_not_run("Read-only Ping/Status", "no controller heartbeat."),
                ]
            )
            return findings

        if not alive or age > protocol.HEARTBEAT_STALE_SECONDS:
            findings.extend(
                [
                    Finding(
                        component="FL Studio Controller Script",
                        severity="blocker",
                        status="manual_check",
                        evidence=(f"Controller heartbeat exists but is stale ({age:.2f}s old)."),
                        remediation="Reload FL MIDI scripts or restart the FL controller script.",
                        config_source="FL bridge heartbeat",
                    ),
                    Finding(
                        component="Heartbeat Freshness",
                        severity="blocker",
                        status="manual_check",
                        evidence=(
                            f"Heartbeat age {age:.2f}s exceeds "
                            f"{protocol.HEARTBEAT_STALE_SECONDS:.2f}s."
                        ),
                        remediation=(
                            "Confirm FL Studio is responsive and the script is still running."
                        ),
                        config_source="FL bridge heartbeat",
                    ),
                    _probe_not_run("Read-only Ping/Status", "heartbeat is stale."),
                ]
            )
            return findings

        findings.append(
            Finding(
                component="FL Studio Controller Script",
                severity="blocker",
                status="ok",
                evidence="Controller heartbeat is reachable through the configured bridge.",
                remediation="",
                config_source="FL bridge heartbeat",
            )
        )
        findings.append(
            Finding(
                component="Heartbeat Freshness",
                severity="blocker",
                status="ok",
                evidence=f"Heartbeat fresh ({age:.2f}s old).",
                remediation="",
                config_source="FL bridge heartbeat",
            )
        )

        try:
            data = bridge.call(protocol.CMD_PING, {}, timeout=1.0)
        except connection.FLTimeout:
            findings.append(
                Finding(
                    component="Read-only Ping/Status",
                    severity="blocker",
                    status="failed",
                    evidence="Read-only controller ping timed out.",
                    remediation="Ensure the FL controller script matches the server protocol.",
                    config_source="FL bridge read-only ping",
                )
            )
        except Exception as exc:
            findings.append(
                Finding(
                    component="Read-only Ping/Status",
                    severity="blocker",
                    status="failed",
                    evidence=f"Read-only controller ping failed: {exc}",
                    remediation="Check FL Studio script output for controller errors.",
                    config_source="FL bridge read-only ping",
                )
            )
        else:
            marker = data.get("build_marker", "unknown") if isinstance(data, dict) else "unknown"
            findings.append(
                Finding(
                    component="Read-only Ping/Status",
                    severity="blocker",
                    status="ok",
                    evidence=f"Read-only ping succeeded. Build marker: {marker}.",
                    remediation="",
                    config_source="FL bridge read-only ping",
                )
            )
        return findings
    finally:
        with contextlib.suppress(Exception):
            bridge.close()


def check_mcp_server_entrypoint() -> list[Finding]:
    """Check if the FastMCP server can be instantiated in-process."""
    try:
        from fls_pilot.server import build_server

        build_server()
        return [
            Finding(
                component="MCP Server Entrypoint",
                severity="blocker",
                status="ok",
                evidence="Server instantiates cleanly in-process.",
                remediation="",
                config_source="code: fls_pilot.server:build_server",
            )
        ]
    except Exception as exc:
        return [
            Finding(
                component="MCP Server Entrypoint",
                severity="blocker",
                status="failed",
                evidence=f"Failed to build server: {exc}",
                remediation="Check server registration, syntax errors, and dependencies.",
                config_source="code: fls_pilot.server:build_server",
            )
        ]


def _mcp_smoke_evidence(result: dict, transport_label: str) -> str:
    tool_count = result.get("tool_count", "unknown")
    resource_count = result.get("resource_count", "unknown")
    transport_tool = "present" if result.get("has_fl_transport") else "missing"
    status_resource = "present" if result.get("has_status_resource") else "missing"
    return (
        f"MCP {transport_label} session initialized; protocol ping succeeded; "
        f"listed {tool_count} tools and {resource_count} resources; "
        f"fl_transport is {transport_tool}; fl://status is {status_resource}; "
        "read fl://status succeeded."
    )


async def _stdio_mcp_smoke_async(config: MCPServerConfig) -> dict:
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["FLS_PILOT_SERVER_TRANSPORT"] = "stdio"
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fls_pilot.server"],
        env=env,
        cwd=os.getcwd(),
    )
    timeout = config.smoke_timeout_seconds
    with anyio.fail_after(timeout + 5.0):
        with open(os.devnull, "w") as devnull:
            async with stdio_client(params, errlog=devnull) as (read, write):
                async with ClientSession(
                    read,
                    write,
                    read_timeout_seconds=timedelta(seconds=timeout),
                ) as session:
                    await session.initialize()
                    await session.send_ping()
                    tools = (await session.list_tools()).tools
                    resources = (await session.list_resources()).resources
                    await session.read_resource("fl://status")
                    return {
                        "tool_count": len(tools),
                        "resource_count": len(resources),
                        "has_fl_transport": any(t.name == "fl_transport" for t in tools),
                        "has_status_resource": any(str(r.uri) == "fl://status" for r in resources),
                    }


def _run_stdio_mcp_smoke(config: MCPServerConfig) -> dict:
    import anyio

    return anyio.run(_stdio_mcp_smoke_async, config)


def _connect_host_for_bind_host(host: str) -> str:
    if host in {"0.0.0.0", ""}:
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _wait_for_tcp(host: str, port: int, proc: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    connect_host = _connect_host_for_bind_host(host)
    last_error = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=1)
            tail = (err or out or b"").decode("utf-8", "replace")[-600:]
            raise RuntimeError(
                f"SSE server exited early with code {proc.returncode}. {tail}".strip()
            )
        try:
            with socket.create_connection((connect_host, port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)
    raise TimeoutError(
        f"Timed out waiting for SSE server at {host}:{port}. Last error: {last_error}"
    )


async def _sse_mcp_client_smoke_async(url: str, timeout: float) -> dict:
    import anyio
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    with anyio.fail_after(timeout + 5.0):
        async with sse_client(
            url,
            timeout=timeout,
            sse_read_timeout=timeout,
        ) as (read, write):
            async with ClientSession(
                read,
                write,
                read_timeout_seconds=timedelta(seconds=timeout),
            ) as session:
                await session.initialize()
                await session.send_ping()
                tools = (await session.list_tools()).tools
                resources = (await session.list_resources()).resources
                await session.read_resource("fl://status")
                return {
                    "tool_count": len(tools),
                    "resource_count": len(resources),
                    "has_fl_transport": any(t.name == "fl_transport" for t in tools),
                    "has_status_resource": any(str(r.uri) == "fl://status" for r in resources),
                }


def _run_sse_mcp_smoke(config: MCPServerConfig) -> dict:
    import anyio

    if config.sse_port is None:
        raise RuntimeError(config.sse_port_error or "SSE port is not configured.")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["FLS_PILOT_SERVER_TRANSPORT"] = "sse"
    env["FLS_PILOT_SSE_HOST"] = config.sse_host
    env["FLS_PILOT_SSE_PORT"] = str(config.sse_port)

    proc = subprocess.Popen(
        [sys.executable, "-m", "fls_pilot.server", "--sse", "--port", str(config.sse_port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=os.getcwd(),
    )
    try:
        _wait_for_tcp(config.sse_host, config.sse_port, proc, config.smoke_timeout_seconds)
        connect_host = _url_host(_connect_host_for_bind_host(config.sse_host))
        url = f"http://{connect_host}:{config.sse_port}/sse"
        return anyio.run(_sse_mcp_client_smoke_async, url, config.smoke_timeout_seconds)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
        else:
            with contextlib.suppress(Exception):
                proc.communicate(timeout=1)


def check_mcp_stdio_transport(
    config: MCPServerConfig | None = None,
    *,
    severity: str = "blocker",
) -> list[Finding]:
    """Smoke-test the MCP stdio transport with an MCP session and protocol ping."""
    config = config or resolve_mcp_server_config()
    try:
        result = _run_stdio_mcp_smoke(config)
    except Exception as exc:
        return [
            Finding(
                component="MCP stdio Transport",
                severity=severity,
                status="failed",
                evidence=f"stdio MCP smoke failed: {exc}",
                remediation="Run fls-pilot in a terminal and check server startup errors.",
                config_source="subprocess MCP client over stdio",
            )
        ]

    return [
        Finding(
            component="MCP stdio Transport",
            severity=severity,
            status="ok",
            evidence=_mcp_smoke_evidence(result, "stdio"),
            remediation="",
            config_source="subprocess MCP client over stdio",
        )
    ]


def check_mcp_sse_transport(
    config: MCPServerConfig | None = None,
    *,
    severity: str = "blocker",
) -> list[Finding]:
    """Smoke-test MCP SSE/HTTP with the resolved host and port."""
    config = config or resolve_mcp_server_config()
    if config.sse_port is None:
        return [
            Finding(
                component="MCP SSE/HTTP Transport",
                severity=severity,
                status="failed",
                evidence=config.sse_port_error or "SSE port is not configured.",
                remediation="Set FLS_PILOT_SSE_PORT or pass --sse-port with a valid port.",
                config_source=config.sse_port_source,
            )
        ]

    try:
        result = _run_sse_mcp_smoke(config)
    except Exception as exc:
        return [
            Finding(
                component="MCP SSE/HTTP Transport",
                severity=severity,
                status="failed",
                evidence=f"SSE MCP smoke failed at {config.sse_host}:{config.sse_port}: {exc}",
                remediation="Check the SSE host/port, firewall, and FastMCP HTTP dependencies.",
                config_source=(
                    f"{config.sse_host_source}; {config.sse_port_source}; "
                    "subprocess MCP client over SSE"
                ),
            )
        ]

    return [
        Finding(
            component="MCP SSE/HTTP Transport",
            severity=severity,
            status="ok",
            evidence=(
                _mcp_smoke_evidence(result, "SSE/HTTP")
                + f" Endpoint: {config.sse_host}:{config.sse_port}."
            ),
            remediation="",
            config_source=(
                f"{config.sse_host_source}; {config.sse_port_source}; "
                "subprocess MCP client over SSE"
            ),
        )
    ]


def check_piano_roll_bridge() -> list[Finding]:
    """Check whether the Piano Roll apply script is detectable on disk."""
    expected_path = os.path.join(pyscript_gen.PIANO_ROLL_SCRIPTS_DIR, "MCP_Apply.pyscript")
    if os.path.isfile(expected_path):
        return [
            Finding(
                component="Piano Roll MCP_Apply Script",
                severity="advisory",
                status="ok",
                evidence=f"MCP_Apply.pyscript found at {expected_path}",
                remediation="",
                config_source="filesystem",
            )
        ]
    return [
        Finding(
            component="Piano Roll MCP_Apply Script",
            severity="advisory",
            status="manual_check",
            evidence="MCP_Apply.pyscript was not found.",
            remediation=(
                "This is only needed for Piano Roll writes. It can be generated "
                "when that workflow is set up."
            ),
            config_source="filesystem",
        )
    ]


def check_mcp_client_hints(config: MCPServerConfig | None = None) -> list[Finding]:
    """Report effective MCP server configuration and where it came from."""
    config = config or resolve_mcp_server_config()
    findings: list[Finding] = []

    if config.transport_error:
        findings.append(
            Finding(
                component="MCP Client Configuration",
                severity="blocker",
                status="failed",
                evidence=config.transport_error,
                remediation="Use 'stdio' or 'sse' for FLS_PILOT_SERVER_TRANSPORT.",
                config_source=config.transport_source,
            )
        )

    port_text = str(config.sse_port) if config.sse_port is not None else "invalid"
    findings.append(
        Finding(
            component="MCP Client Configuration",
            severity="advisory",
            status="ok" if not config.sse_port_error else "manual_check",
            evidence=(
                f"Effective MCP transport: {config.transport} "
                f"(source: {config.transport_source}). SSE host: {config.sse_host} "
                f"(source: {config.sse_host_source}); SSE port: {port_text} "
                f"(source: {config.sse_port_source}). all-transports: "
                f"{config.all_transports}."
            ),
            remediation=(
                "Set FLS_PILOT_SERVER_TRANSPORT=sse or pass --server-transport sse "
                "when your MCP client uses SSE/HTTP."
            ),
            config_source="CLI/env/default resolution",
        )
    )

    if config.sse_port_error:
        findings.append(
            Finding(
                component="MCP SSE/HTTP Configuration",
                severity="blocker" if config.transport == "sse" else "warning",
                status="failed" if config.transport == "sse" else "manual_check",
                evidence=config.sse_port_error,
                remediation="Set FLS_PILOT_SSE_PORT or pass --sse-port with a valid port.",
                config_source=config.sse_port_source,
            )
        )

    return findings


def run_all_checks(
    all_transports: bool = False,
    *,
    server_transport: str | None = None,
    sse_host: str | None = None,
    sse_port: int | str | None = None,
    bridge_transport: str | None = None,
    tcp_host: str | None = None,
    tcp_port: int | str | None = None,
    smoke_timeout_seconds: float = DEFAULT_MCP_SMOKE_TIMEOUT_SECONDS,
) -> list[Finding]:
    """Run all Setup Doctor checks with dependency gating."""
    config = resolve_mcp_server_config(
        server_transport=server_transport,
        sse_host=sse_host,
        sse_port=sse_port,
        all_transports=all_transports,
        smoke_timeout_seconds=smoke_timeout_seconds,
    )
    tcp_config = resolve_tcp_daemon_config(
        bridge_transport=bridge_transport,
        tcp_host=tcp_host,
        tcp_port=tcp_port,
    )
    findings: list[Finding] = []
    is_tcp_configured = tcp_config.active

    findings.extend(check_python_environment())
    core_findings = check_core_dependencies()
    findings.extend(core_findings)
    core_ok = not _any_blocker_failed(core_findings)

    findings.extend(check_optional_dependencies())
    findings.extend(check_mcp_client_hints(config))

    server_findings = check_mcp_server_entrypoint()
    findings.extend(server_findings)
    server_ok = not _any_blocker_failed(server_findings)

    transport_skip = "MCP Server Entrypoint failed; fix that first."
    run_stdio = config.transport == "stdio" or config.all_transports
    run_sse = config.transport == "sse" or config.all_transports
    stdio_severity = (
        "blocker" if config.transport == "stdio" or config.all_transports else "warning"
    )
    sse_severity = "blocker" if config.transport == "sse" or config.all_transports else "warning"

    if run_stdio:
        if server_ok:
            findings.extend(check_mcp_stdio_transport(config, severity=stdio_severity))
        else:
            findings.append(
                _deferred_finding("MCP stdio Transport", stdio_severity, transport_skip)
            )

    if run_sse:
        if server_ok:
            findings.extend(check_mcp_sse_transport(config, severity=sse_severity))
        else:
            findings.append(
                _deferred_finding("MCP SSE/HTTP Transport", sse_severity, transport_skip)
            )

    core_skip = "Core dependencies missing; run 'pip install fls-pilot' first."
    fl_app_skip = "FL Studio application is not running."

    if core_ok:
        fl_app_findings = check_fl_studio_application()
        findings.extend(fl_app_findings)
        # True = detected, False = not running (blocker), None = uncertain (warning only)
        fl_app_blocker = any(
            f.component == "FL Studio Application"
            and f.severity == "blocker"
            and f.status == "failed"
            for f in fl_app_findings
        )

        midi_findings = (
            check_midi_ports(severity="advisory", failed_status="manual_check")
            if is_tcp_configured
            else check_midi_ports()
        )
        findings.extend(midi_findings)
        midi_ok = not _any_blocker_failed(midi_findings)

        tcp_findings = check_tcp_daemon(tcp_config)
        findings.extend(tcp_findings)
        tcp_ok = all(f.status == "ok" for f in tcp_findings)
    else:
        fl_app_blocker = False
        findings.append(_deferred_finding("MIDI/IAC/loopMIDI Ports", "blocker", core_skip))
        findings.append(_deferred_finding("TCP Daemon / Bridge", "warning", core_skip))
        midi_ok = False
        tcp_ok = False

    if not core_ok:
        findings.append(_deferred_finding("FL Studio Controller Script", "blocker", core_skip))
    elif fl_app_blocker:
        # FL Studio is confirmed not running — skip controller check entirely.
        findings.append(
            _deferred_finding(
                "FL Studio Controller Script",
                "blocker",
                fl_app_skip,
            )
        )
    elif is_tcp_configured:
        if tcp_ok and tcp_config.port is not None:
            findings.extend(
                check_fl_controller(
                    bridge_factory=lambda: connection.TCPBridge(
                        tcp_config.host,
                        tcp_config.port,
                    ),
                    config_source=f"TCP daemon {tcp_config.host}:{tcp_config.port}",
                )
            )
        else:
            findings.append(
                _deferred_finding(
                    "FL Studio Controller Script",
                    "blocker",
                    "TCP daemon/bridge is not alive.",
                )
            )
    elif midi_ok:
        findings.extend(check_fl_controller())
    else:
        findings.append(
            _deferred_finding(
                "FL Studio Controller Script",
                "blocker",
                "MIDI/IAC/loopMIDI ports are not available.",
            )
        )

    findings.extend(check_piano_roll_bridge())
    return findings


def format_human(findings: list[Finding]) -> str:
    """Format findings for CLI consumption."""
    lines: list[str] = [
        "FL Studio Pilot - Setup Doctor",
        "================================",
        "",
    ]

    grouped: dict[str, list[Finding]] = {"blocker": [], "warning": [], "advisory": []}
    for finding in findings:
        grouped.setdefault(finding.severity, []).append(finding)

    symbols = {
        "ok": "[OK]",
        "failed": "[FAIL]",
        "manual_check": "[CHECK]",
        "probe_needed": "[PROBE]",
    }
    section_labels = {
        "blocker": "BLOCKERS",
        "warning": "WARNINGS",
        "advisory": "ADVISORIES",
    }

    for severity in ("blocker", "warning", "advisory"):
        group = grouped.get(severity, [])
        if not group:
            continue
        lines.append(f"--- {section_labels[severity]} ---")
        for finding in group:
            sym = symbols.get(finding.status, "[INFO]")
            lines.append(f"{sym} {finding.component} [{finding.status}]")
            lines.append(f"   Evidence: {finding.evidence}")
            lines.append(f"   Source:   {finding.config_source}")
            if finding.remediation and finding.status != "ok":
                lines.append(f"   Fix:      {finding.remediation}")
            lines.append("")

    return "\n".join(lines)


def format_json(findings: list[Finding]) -> str:
    """Format findings as JSON for agents/CI."""
    return json.dumps([f.to_dict() for f in findings], indent=2)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run read-only Setup Doctor diagnostics for FL Studio Pilot."
    )
    parser.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human).",
    )
    parser.add_argument(
        "--all-transports",
        action="store_true",
        help="Release-validation mode: smoke-test both stdio and SSE/HTTP.",
    )
    parser.add_argument(
        "--server-transport",
        choices=sorted(_VALID_MCP_TRANSPORTS),
        help="MCP server transport to test by default.",
    )
    parser.add_argument("--sse-host", help="SSE host to bind/test.")
    parser.add_argument("--sse-port", type=int, help="SSE port to bind/test.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_MCP_SMOKE_TIMEOUT_SECONDS,
        help="Timeout in seconds for MCP transport smoke tests.",
    )
    args = parser.parse_args(argv)

    findings = run_all_checks(
        all_transports=args.all_transports,
        server_transport=args.server_transport,
        sse_host=args.sse_host,
        sse_port=args.sse_port,
        smoke_timeout_seconds=args.timeout,
    )

    if args.format == "json":
        print(format_json(findings))
    else:
        print(format_human(findings))

    if any(f.severity == "blocker" and f.status != "ok" for f in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
