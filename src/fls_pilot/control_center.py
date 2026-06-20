"""Local first-run and runtime Control Center for FL Studio Pilot."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any

from . import doctor, kb_policy, protocol
from . import project_templates as templates
from .analysis import (
    AnalysisReport,
    Coverage,
    EntityRef,
    Finding,
    Freshness,
    Prerequisite,
    StaticSnapshotPolicy,
    analysis_report_for_control_center,
    confidence_from_coverage,
    low_end_health_score,
    mix_health_score,
    mixer_entity_id,
    organizer_score,
    risk_from_severities,
    routing_analysis_report_from_legacy_payload,
    routing_health_score,
)
from .analysis.live import LiveMeterPolicy
from .connection import DEFAULT_TCP_HOST, DEFAULT_TCP_PORT, TCPBridge, fetch_all_pages
from .music import mix_doctor as mix_review
from .rules import RuleCondition, RuleDefinition, evaluate_rules
from .runtime.audio_worker import AUDIO_FEATURE_JOB_KIND, build_audio_job_request
from .runtime.client import RuntimeClient
from .runtime_config import (
    DEFAULT_CONTROL_CENTER_HOST,
    DEFAULT_CONTROL_CENTER_PORT,
    DEFAULT_SSE_HOST,
    DEFAULT_SSE_PORT,
    can_bind_tcp,
    find_available_tcp_port,
    tcp_port_status,
)
from .status import collect_status as collect_status_report
from .workflows.registry import (
    DEFAULT_WORKFLOW_REGISTRY,
    WorkflowRegistry,
    build_effective_workflow_registry,
)

STATIC_PACKAGE = "fls_pilot.control_center_static"
MAX_LOG_LINES = 80
MANUAL_CHECKPOINTS = {
    "created_midi_ports",
    "opened_fl_studio",
    "configured_fl_midi",
    "ran_mcp_apply",
    "granted_macos_accessibility",
}
def _read_project_version() -> str:
    try:
        project_root = Path(__file__).resolve().parent.parent.parent
        pyproject_path = project_root / "pyproject.toml"
        if pyproject_path.exists():
            for line in pyproject_path.read_text("utf-8").splitlines():
                if line.startswith("version = "):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    from . import __version__

    return __version__


PROJECT_VERSION = _read_project_version()


@dataclass
class ManagedProcess:
    name: str
    args: list[str]
    env: dict[str, str]
    process: subprocess.Popen
    started_at: str
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOG_LINES))
    reader_threads: list[threading.Thread] = field(default_factory=list)

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "pid": self.process.pid,
            "state": "running" if self.running else "exited",
            "running": self.running,
            "returncode": self.process.poll(),
            "started_at": self.started_at,
            "args": _redact_args(self.args),
            "logs": list(self.logs),
        }


class ControlCenterState:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        sse_host: str,
        sse_port: int,
        workflow_registry: WorkflowRegistry | None = None,
        admin_enabled: bool = False,
    ) -> None:
        daemon_host, daemon_port = _resolve_daemon_endpoint()
        self.host = host
        self.port = port
        self.sse_host = sse_host
        self.sse_port = sse_port
        self.daemon_host = daemon_host
        self.daemon_port = daemon_port
        self.daemon_fallback_port: int | None = None
        self.admin_enabled: bool = admin_enabled
        self.runtime_client = RuntimeClient(daemon_host, daemon_port)
        self.workflow_registry = workflow_registry or build_effective_workflow_registry(
            DEFAULT_WORKFLOW_REGISTRY,
            (),
        )
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.processes: dict[str, ManagedProcess] = {}
        self.last_findings: list[doctor.Finding] = []
        self.daemon_autostart_attempted = False
        self.daemon_autostart: dict[str, Any] = {
            "state": "pending",
            "message": "Daemon auto-start has not run yet.",
        }
        self.sse_probe: dict[str, Any] = _sse_probe_state(
            "not_required",
            "SSE server is stopped. Start it only if your MCP client uses SSE/HTTP.",
            sse_host,
            sse_port,
        )
        self.started_at = _now_iso()
        self.lock = threading.RLock()

    def shutdown(self) -> None:
        with self.lock:
            for name in list(self.processes):
                _stop_managed_process(self.processes[name])
            self.processes.clear()


def collect_status(state: ControlCenterState, *, refresh: bool = True) -> dict[str, Any]:
    """Collect Control Center status without mutating FL Studio project state."""
    with state.lock:
        daemon_host, daemon_port = _selected_daemon_endpoint(state)
        if refresh or not state.last_findings:
            state.last_findings = _run_doctor_checks(state, daemon_host, daemon_port)
            autostart = _auto_start_daemon_if_ready(state, state.last_findings)
            if autostart.get("rerun_checks"):
                daemon_host, daemon_port = _selected_daemon_endpoint(state)
                state.last_findings = _run_doctor_checks(state, daemon_host, daemon_port)
        findings = [finding.to_dict() for finding in state.last_findings]
        groups = _group_findings(state.last_findings)
        readiness = _readiness(state.last_findings, state.checkpoints)
        _sync_sse_probe_state(state, refresh=refresh)
        process_state = _process_status(state)
        ports = _port_state(state)
        status_report_data = collect_status_report(
            offline=False,
            bridge_factory=lambda: TCPBridge(daemon_host, daemon_port),
        )
        ui = _ui_payload(
            status_report=status_report_data,
            readiness=readiness,
            processes=process_state,
            ports=ports,
            workflow_registry=state.workflow_registry,
        )
        return {
            "version": PROJECT_VERSION,
            "generated_at": _now_iso(),
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "python": sys.version.split()[0],
                "executable": sys.executable,
            },
            "control_center": {
                "host": state.host,
                "port": state.port,
                "url": f"http://{state.host}:{state.port}/",
                "started_at": state.started_at,
            },
            "ports": ports,
            "readiness": readiness,
            "groups": groups,
            "findings": findings,
            "checkpoints": dict(state.checkpoints),
            "processes": process_state,
            "automation": {"daemon_autostart": dict(state.daemon_autostart)},
            "mcp": {"sse_probe": dict(state.sse_probe)},
            "setup_guidance": _setup_guidance(
                groups=groups,
                readiness=readiness,
                processes=process_state,
                ports=ports,
                daemon_autostart=state.daemon_autostart,
                sse_probe=state.sse_probe,
            ),
            "snippets": client_snippets(state),
            "status_report": status_report_data,
            "ui": ui,
        }


def _ui_payload(
    *,
    status_report: dict[str, Any],
    readiness: dict[str, Any],
    processes: dict[str, Any],
    ports: dict[str, dict[str, Any]],
    workflow_registry: WorkflowRegistry = DEFAULT_WORKFLOW_REGISTRY,
) -> dict[str, Any]:
    return {
        "workflow_catalog": [
            dict(item) for item in workflow_registry.control_center_catalog()
        ],
        "next_action": _ui_next_action(
            status_report=status_report,
            readiness=readiness,
            processes=processes,
        ),
        "service_actions": _ui_service_actions(processes=processes, ports=ports),
    }


def _ui_next_action(
    *,
    status_report: dict[str, Any],
    readiness: dict[str, Any],
    processes: dict[str, Any],
) -> dict[str, Any]:
    bridge = status_report.get("bridge") or {}
    daemon_process = processes.get("daemon") or {}
    daemon_running = _process_running(daemon_process)
    live = bridge.get("state") == "live"

    if not daemon_running:
        return {
            "label": "Start FL Studio Bridge Service",
            "detail": (
                "The local bridge service is stopped. Start it before checking "
                "FL Studio controller data."
            ),
            "target_panel": "overview",
            "action_path": "/api/process/daemon/start",
            "action_label": "Start Service",
            "kind": "service",
        }

    if not live:
        return {
            "label": "Connect FL Studio Controller",
            "detail": (
                "The bridge service is running, but FL Studio is not sending "
                "fresh controller data yet."
            ),
            "target_panel": "setup",
            "action_path": "/api/refresh",
            "action_label": "Re-check",
            "kind": "setup",
        }

    if readiness.get("read_only_review_ready"):
        return {
            "label": "Run Health Scan",
            "detail": (
                "FL Studio is connected. Start with a read-only project overview "
                "before opening detailed workflow panels."
            ),
            "target_panel": "producer_health",
            "action_path": None,
            "action_label": "Open Health",
            "kind": "workflow",
        }

    return {
        "label": "Review Setup Doctor",
        "detail": "A setup check still needs attention before project review is ready.",
        "target_panel": "setup",
        "action_path": "/api/refresh",
        "action_label": "Re-check",
        "kind": "setup",
    }


def _ui_service_actions(
    *,
    processes: dict[str, Any],
    ports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        "daemon": _ui_service_action(
            "daemon",
            "FL Studio Bridge Service",
            processes.get("daemon") or {},
            ports.get("daemon") or {},
        ),
        "sse": _ui_service_action(
            "sse",
            "AI Client Server",
            processes.get("sse") or {},
            ports.get("sse") or {},
        ),
    }


def _ui_service_action(
    key: str,
    label: str,
    process: dict[str, Any],
    port: dict[str, Any],
) -> dict[str, Any]:
    state_value = str(process.get("state") or "stopped")
    external = state_value == "external"
    managed_running = bool(process.get("running")) or state_value == "running"
    reachable = managed_running or external
    selected_port = port.get("selected_port")
    host = port.get("host") or "127.0.0.1"
    return {
        "label": label,
        "state": state_value,
        "managed": managed_running and not external,
        "external": external,
        "host": host,
        "selected_port": selected_port,
        "start": {
            "enabled": not reachable,
            "path": f"/api/process/{key}/start",
            "label": "Start Service" if key == "daemon" else "Start AI Client Server",
        },
        "stop": {
            "enabled": managed_running and not external,
            "path": f"/api/process/{key}/stop",
            "label": "Stop Service" if key == "daemon" else "Stop AI Client Server",
        },
        "detail": _ui_service_detail(label, state_value, host, selected_port, external),
    }


def _run_runtime_product_workflow(
    state: ControlCenterState,
    workflow_id: str,
    *,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a declared read-only Runtime workflow for a Control Center panel."""
    try:
        return _runtime_client(state).run_workflow(workflow_id, inputs=inputs)
    except Exception as exc:
        return {
            "contract_version": "fls-pilot.analysis-report.v1",
            "workflow": workflow_id,
            "title": state.workflow_registry.get(workflow_id).title,
            "analysis_mode": "manual_check",
            "evidence_mode": "unavailable",
            "freshness": {"status": "unavailable"},
            "coverage": {
                "required": 1,
                "available": 0,
                "missing": ["runtime_workflow"],
                "score": 0,
                "status": "unavailable",
            },
            "risk_score": 0,
            "health_score": 0,
            "confidence_score": 0,
            "findings": [],
            "limitations": [f"{type(exc).__name__}: {exc}"],
            "manual_checks": [
                {
                    "id": f"{workflow_id}.runtime_unavailable",
                    "title": "Connect the FL Studio Runtime and run the check again.",
                }
            ],
            "next_actions": [
                {
                    "type": "setup",
                    "label": "Open Setup Doctor",
                    "target_panel": "setup",
                }
            ],
            "proposed_changes": [],
            "applied_changes": [],
            "safety": {"read_only": True, "project_changes": False},
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _run_audio_analysis_action(
    state: ControlCenterState,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Run one Control Center audio-job action through canonical Runtime RPCs."""
    try:
        action = str(payload.get("action") or "").strip().lower()
        client = _runtime_client(state)
        if action == "submit":
            request = build_audio_job_request(str(payload.get("path") or ""))
            job = client.submit_job(
                request["kind"],
                input=request["input"],
                input_summary=request["input_summary"],
                idempotency_key=request["idempotency_key"],
                idempotent=True,
                max_retries=2,
            )
            return {"ok": True, "job": job}
        if action == "list":
            limit = max(1, min(int(payload.get("limit", 20)), 100))
            offset = max(0, int(payload.get("offset", 0)))
            return {
                "ok": True,
                "jobs": client.list_jobs(
                    kind=AUDIO_FEATURE_JOB_KIND,
                    limit=limit,
                    offset=offset,
                ),
                "limit": limit,
                "offset": offset,
            }
        if action not in {"status", "result", "cancel"}:
            raise ValueError("action must be submit, status, result, cancel, or list")
        job_id = str(payload.get("job_id") or "").strip()
        if not job_id:
            raise ValueError(f"job_id is required for {action}")
        if action == "status":
            return {"ok": True, "job": client.job_status(job_id)}
        if action == "cancel":
            return {"ok": True, "job": client.cancel_job(job_id)}

        job = client.job_result(job_id)
        response: dict[str, Any] = {"ok": True, "job": job}
        artifact_id = str((job.get("result_ref") or {}).get("artifact_id") or "")
        link_requested = bool(payload.get("link_evidence"))
        if artifact_id and link_requested:
            targets = payload.get("workflow_targets") or []
            if not isinstance(targets, list) or not all(
                isinstance(item, str) for item in targets
            ):
                raise ValueError("workflow_targets must be a list of workflow ids")
            response["report"] = client.run_workflow(
                "audio_evidence",
                inputs={
                    "artifact_id": artifact_id,
                    "evidence_kind": str(
                        payload.get("evidence_kind") or "rendered_master"
                    ),
                    "stem_role": (
                        str(payload["stem_role"]).strip()
                        if payload.get("stem_role")
                        else None
                    ),
                    "workflow_links": [item.strip() for item in targets if item.strip()],
                    "confirmed_by_user": bool(payload.get("confirmed_by_user")),
                },
            )
        return response
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _ui_service_detail(
    label: str,
    state_value: str,
    host: str,
    selected_port: Any,
    external: bool,
) -> str:
    endpoint = f"{host}:{selected_port}" if selected_port is not None else host
    if external:
        return f"{label} is reachable at {endpoint}. Control Center did not start it."
    if state_value == "running":
        return f"{label} is running at {endpoint}."
    return f"{label} is not running."


def _run_doctor_checks(
    state: ControlCenterState,
    daemon_host: str,
    daemon_port: int,
) -> list[doctor.Finding]:
    return doctor.run_all_checks(
        server_transport="stdio",
        sse_host=state.sse_host,
        sse_port=state.sse_port,
        bridge_transport="tcp",
        tcp_host=daemon_host,
        tcp_port=daemon_port,
        smoke_timeout_seconds=1.5,
    )


def _auto_start_daemon_if_ready(
    state: ControlCenterState,
    findings: list[doctor.Finding],
) -> dict[str, Any]:
    if state.daemon_autostart_attempted:
        return {}

    if not _environment_ready(findings):
        state.daemon_autostart = {
            "state": "skipped",
            "message": "Daemon auto-start waits until Python and core dependencies are OK.",
        }
        return {}

    state.daemon_autostart_attempted = True
    existing = state.processes.get("daemon")
    if existing and existing.running:
        state.daemon_autostart = {
            "state": "running",
            "message": "Daemon is already running under this Control Center.",
            "port": _selected_daemon_endpoint(state)[1],
        }
        return {}

    health = _daemon_health(state.daemon_host, state.daemon_port)
    if health.get("reachable"):
        state.daemon_fallback_port = None
        state.daemon_autostart = {
            "state": "external",
            "message": "A daemon is already reachable. Control Center will use it.",
            "port": state.daemon_port,
        }
        return {}

    port_status = tcp_port_status(state.daemon_host, state.daemon_port)
    target_port = state.daemon_port
    fallback_used = False
    if not port_status["available"]:
        target_port = int(port_status["fallback_port"])
        state.daemon_fallback_port = target_port
        fallback_used = True
    else:
        state.daemon_fallback_port = None

    try:
        proc = _spawn_daemon(state, target_port)
    except Exception as exc:
        state.daemon_autostart = {
            "state": "failed",
            "message": f"Daemon auto-start failed: {type(exc).__name__}: {exc}",
            "port": target_port,
        }
        return {}

    state.processes["daemon"] = proc
    health = _wait_for_daemon_health(state.daemon_host, target_port)
    state.daemon_autostart = {
        "state": "started" if health.get("reachable") else "starting",
        "message": (
            f"Started daemon on fallback port {target_port}."
            if fallback_used
            else f"Started daemon on port {target_port}."
        ),
        "port": target_port,
        "fallback_used": fallback_used,
        "reachable": bool(health.get("reachable")),
    }
    return {"rerun_checks": True}


def _environment_ready(findings: list[doctor.Finding]) -> bool:
    required = {"Python Environment", "Core Dependencies"}
    seen: set[str] = set()
    for finding in findings:
        if finding.component not in required:
            continue
        seen.add(finding.component)
        if finding.status != "ok":
            return False
    return required.issubset(seen)


def _spawn_daemon(state: ControlCenterState, port: int) -> ManagedProcess:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["FLS_PILOT_TCP_HOST"] = state.daemon_host
    env["FLS_PILOT_TCP_PORT"] = str(port)
    return _spawn("daemon", [sys.executable, "-m", "fls_pilot.daemon"], env)


def _wait_for_daemon_health(host: str, port: int, *, timeout: float = 2.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = {"reachable": False}
    while time.monotonic() < deadline:
        last = _daemon_health(host, port)
        if last.get("reachable"):
            return last
        time.sleep(0.1)
    return last


def _sync_sse_probe_state(state: ControlCenterState, *, refresh: bool) -> None:
    proc = state.processes.get("sse")
    if proc is None:
        state.sse_probe = _sse_probe_state(
            "not_required",
            "SSE server is stopped. Start it only if your MCP client uses SSE/HTTP.",
            state.sse_host,
            state.sse_port,
        )
        return
    if not proc.running:
        if state.sse_probe.get("state") not in {"not_required", "stopped"}:
            state.sse_probe = _sse_probe_state(
                "failed",
                f"SSE server is not running. Last exit code: {proc.process.poll()}.",
                state.sse_host,
                state.sse_port,
                checked_at=_now_iso(),
            )
        return

    expected_url = _sse_url(state.sse_host, state.sse_port)
    probe_state = str(state.sse_probe.get("state") or "")
    should_probe = (
        state.sse_probe.get("url") != expected_url
        or probe_state
        in {
            "",
            "not_required",
            "stopped",
            "pending",
            "checking",
        }
        or (refresh and probe_state == "failed")
    )
    if should_probe:
        _probe_sse_connection(state)


def _probe_sse_connection(
    state: ControlCenterState,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    url = _sse_url(state.sse_host, state.sse_port)
    state.sse_probe = _sse_probe_state(
        "checking",
        "Testing the MCP connection over SSE...",
        state.sse_host,
        state.sse_port,
    )
    proc = state.processes.get("sse")
    try:
        _wait_for_tcp_listener(
            state.sse_host,
            state.sse_port,
            process=proc.process if proc is not None else None,
            timeout=timeout,
        )
        import anyio

        result = anyio.run(doctor._sse_mcp_client_smoke_async, url, timeout)
    except Exception as exc:
        state.sse_probe = _sse_probe_state(
            "failed",
            f"SSE MCP connection test failed at {url}: {type(exc).__name__}: {exc}",
            state.sse_host,
            state.sse_port,
            checked_at=_now_iso(),
            error=f"{type(exc).__name__}: {exc}",
        )
    else:
        state.sse_probe = _sse_probe_state(
            "ok",
            _sse_probe_success_message(url, result),
            state.sse_host,
            state.sse_port,
            checked_at=_now_iso(),
            result=result,
        )
    return dict(state.sse_probe)


def _wait_for_tcp_listener(
    host: str,
    port: int,
    *,
    process: subprocess.Popen | None = None,
    timeout: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    connect_host = _connect_host_for_bind_host(host)
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"SSE server exited early with code {process.returncode}.")
        try:
            with socket.create_connection((connect_host, int(port)), timeout=0.3):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for SSE server at {host}:{port}: {last_error}")


def _sse_probe_state(
    state: str,
    message: str,
    host: str,
    port: int,
    *,
    checked_at: str | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "state": state,
        "message": message,
        "host": host,
        "port": int(port),
        "url": _sse_url(host, port),
    }
    if checked_at is not None:
        data["checked_at"] = checked_at
    if error:
        data["error"] = error
    if result is not None:
        data["result"] = result
    return data


def _sse_probe_success_message(url: str, result: dict[str, Any]) -> str:
    pieces = [
        f"SSE MCP connection test passed at {url}.",
        f"Tools: {result.get('tool_count', 'unknown')}.",
        f"Resources: {result.get('resource_count', 'unknown')}.",
    ]
    if result.get("has_fl_transport"):
        pieces.append("fl_transport is available.")
    if result.get("has_status_resource"):
        pieces.append("fl://status is readable.")
    return " ".join(pieces)


def _sse_url(host: str, port: int) -> str:
    connect_host = _connect_host_for_bind_host(host)
    if connect_host == "127.0.0.1":
        connect_host = "localhost"
    connect_host = _url_host(connect_host)
    return f"http://{connect_host}:{int(port)}/sse"


def _connect_host_for_bind_host(host: str) -> str:
    if host in {"0.0.0.0", ""}:
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def _url_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def client_snippets(state: ControlCenterState) -> dict[str, Any]:
    chatgpt_url = f"http://localhost:{state.sse_port}/sse"
    command = _console_script_path("fls-pilot")
    daemon_host, daemon_port = _selected_daemon_endpoint(state)
    mcp_tcp_env = {
        "FLS_PILOT_TRANSPORT": "tcp",
        "FLS_PILOT_TCP_HOST": daemon_host,
        "FLS_PILOT_TCP_PORT": str(daemon_port),
    }
    return {
        "chatgpt": {
            "name": "fls-pilot",
            "type": "sse",
            "url": chatgpt_url,
        },
        "claude": {
            "mcpServers": {
                "fls-pilot": {
                    "command": command,
                    "env": dict(mcp_tcp_env),
                }
            }
        },
        "cursor": {
            "mcpServers": {
                "fls-pilot": {
                    "command": command,
                    "env": dict(mcp_tcp_env),
                }
            }
        },
        "terminal": {
            "daemon": _daemon_terminal_command(daemon_host, daemon_port),
            "sse": _sse_terminal_command(state, command),
        },
    }


def setup_report(state: ControlCenterState) -> str:
    status = collect_status(state, refresh=False)
    lines = [
        "# fls-pilot setup report",
        "",
        f"Generated: {status['generated_at']}",
        f"Version: {status['version']}",
        f"OS: {status['platform']['system']} {status['platform']['release']}",
        f"Python: {status['platform']['python']}",
        f"Executable: {_redact_path(status['platform']['executable'])}",
        "",
        "## Ports",
    ]
    for name, data in status["ports"].items():
        lines.append(
            f"- {name}: default {data['host']}:{data['preferred_port']}; "
            f"selected {data['host']}:{data['selected_port']}; "
            f"fallback {data.get('fallback_port') or 'none'}"
        )
    lines.extend(["", "## Readiness", f"- State: {status['readiness']['state']}"])
    lines.extend(["", "## Manual checkpoints"])
    if status["checkpoints"]:
        for key, value in status["checkpoints"].items():
            lines.append(f"- {key}: {value.get('status')} at {value.get('updated_at')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Processes"])
    for name, proc in status["processes"].items():
        lines.append(f"- {name}: {_process_state_text(proc)}")
        for log in proc.get("logs", [])[-10:]:
            lines.append(f"  - {log}")
    autostart = status.get("automation", {}).get("daemon_autostart", {})
    sse_probe = status.get("mcp", {}).get("sse_probe", {})
    lines.extend(
        [
            "",
            "## Automation",
            f"- Daemon auto-start: {autostart.get('state', 'unknown')} - "
            f"{autostart.get('message', 'no detail')}",
            f"- MCP SSE probe: {sse_probe.get('state', 'unknown')} - "
            f"{sse_probe.get('message', 'no detail')}",
        ]
    )
    lines.extend(["", "## Guided troubleshooting"])
    for item in status.get("setup_guidance", []):
        lines.append(f"- [{item.get('status')}] {item.get('title')}: {item.get('text')}")
    lines.extend(["", "## Doctor findings"])
    for finding in status["findings"]:
        lines.append(
            f"- [{finding['severity']}/{finding['status']}] {finding['component']}: "
            f"{_redact_path(finding['evidence'])}"
        )
        if finding.get("remediation"):
            lines.append(f"  Fix: {finding['remediation']}")
    return "\n".join(lines) + "\n"


MIX_POLICY_RULE_IDS = [
    "master_peak_boundary",
    "mix_doctor_master_output_boundary",
    "mix_doctor_insert_headroom_context",
    "mix_doctor_source_trim_first",
    "source_or_bus_trim_before_master_trim",
    "mix_doctor_existing_plugin_only",
]
LOW_END_RULESET_ID = "core.low-end.metadata"
LOW_END_RULESET_VERSION = "1.0.0"
LOW_END_PROFILE_ID = "default"
LOW_END_METADATA_RULES = (
    RuleDefinition(
        id="low_end.stereo_metadata_risk",
        title="Low-end track has wide or panned mixer metadata",
        severity="info",
        risk_score=0,
        confidence_score=65,
        evidence_mode="static_snapshot",
        conditions=(
            RuleCondition(
                "track.low_end_role",
                "in",
                ("kick", "sub", "bass"),
            ),
            RuleCondition("track.stereo_risk", "truthy"),
        ),
        metadata={
            "ruleset_id": LOW_END_RULESET_ID,
            "profile_id": LOW_END_PROFILE_ID,
        },
    ),
)


def _collect_mix_snapshot(
    state: ControlCenterState,
    bridge: TCPBridge,
) -> dict[str, Any]:
    static_snapshot = state.broker.get_static_project_snapshot(
        bridge,
        StaticSnapshotPolicy(),
    )
    watcher = mix_review.get_watcher()
    live_window = state.broker.get_live_meter_window(
        bridge,
        policy=LiveMeterPolicy(require_playing=False, min_capture_seconds=30.0),
        watcher_provider=watcher,
        static_snapshot=static_snapshot,
    )
    watch_peaks = (
        {int(track): peak for track, peak in live_window.track_meter_summaries.items()}
        if live_window.freshness == "fresh"
        else None
    )
    return mix_review.gather_snapshot(
        bridge,
        peaks_override=watch_peaks or None,
        live_window=live_window,
        static_snapshot=static_snapshot,
    )


def _run_mix_review(
    state: ControlCenterState,
    *,
    bridge_override: Any | None = None,
) -> dict[str, Any]:
    """Run the read-only Mix Review workflow for the Control Center UI."""
    if bridge_override is None and hasattr(state, "runtime_client"):
        try:
            return _runtime_client(state).run_workflow("mix_review")
        except Exception as exc:
            report = _mix_review_unavailable_report(f"{type(exc).__name__}: {exc}")
            analysis = _generic_analysis_report_from_legacy(
                report, "mix_review", "Mix Review"
            )
            return analysis_report_for_control_center(analysis, report)
    bridge = bridge_override
    owns_bridge = bridge is None
    try:
        if bridge is None:
            with state.lock:
                daemon_host, daemon_port = _selected_daemon_endpoint(state)
            bridge = TCPBridge(daemon_host, daemon_port)
        wait = getattr(bridge, "wait_for_heartbeat", None)
        if callable(wait):
            wait(timeout=1.0)
        alive = bool(getattr(bridge, "is_alive", lambda: False)())
        if not alive:
            raise ConnectionError(
                "No fresh FL Studio controller heartbeat. Open FL Studio and refresh "
                "the connection."
            )

        snapshot = _collect_mix_snapshot(state, bridge)
        report_payload = _build_mix_review_report(snapshot)
        analysis_report = _generic_analysis_report_from_legacy(
            report_payload,
            "mix_review",
            "Mix Review",
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return analysis_report_for_control_center(analysis_report, report_payload)
    except Exception as exc:
        report = _mix_review_unavailable_report(f"{type(exc).__name__}: {exc}")
        analysis_report = _generic_analysis_report_from_legacy(
            report,
            "mix_review",
            "Mix Review",
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return analysis_report_for_control_center(analysis_report, report)
    finally:
        if owns_bridge and bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()


def _run_low_end_analysis(
    state: ControlCenterState,
    *,
    bridge_override: Any | None = None,
) -> dict[str, Any]:
    """Run the read-only Low-End Analysis workflow for the Control Center UI."""
    if bridge_override is None and hasattr(state, "runtime_client"):
        try:
            return _runtime_client(state).run_workflow("low_end_analysis")
        except Exception as exc:
            report = _low_end_unavailable_report(f"{type(exc).__name__}: {exc}")
            analysis = _build_low_end_analysis_report(report)
            return analysis_report_for_control_center(analysis, report)
    bridge = bridge_override
    owns_bridge = bridge is None
    try:
        if bridge is None:
            with state.lock:
                daemon_host, daemon_port = _selected_daemon_endpoint(state)
            bridge = TCPBridge(daemon_host, daemon_port)
        wait = getattr(bridge, "wait_for_heartbeat", None)
        if callable(wait):
            wait(timeout=1.0)
        if not bool(getattr(bridge, "is_alive", lambda: False)()):
            report = _low_end_unavailable_report(
                "No fresh FL Studio controller heartbeat. Open FL Studio and "
                "refresh the connection."
            )
        else:
            report = _build_low_end_legacy_report(_collect_mix_snapshot(state, bridge))
        return _store_low_end_report(state, report)
    except Exception as exc:
        return _store_low_end_report(
            state,
            _low_end_unavailable_report(f"{type(exc).__name__}: {exc}"),
        )
    finally:
        if owns_bridge and bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()


def _store_low_end_report(
    state: ControlCenterState,
    legacy_report: dict[str, Any],
) -> dict[str, Any]:
    analysis_report = _build_low_end_analysis_report(legacy_report)
    store = getattr(state, "report_store", None)
    if store is not None:
        analysis_report = store.add_report(analysis_report)
    return analysis_report_for_control_center(analysis_report, legacy_report)


def _build_low_end_legacy_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    low_end = mix_review.low_end_stereo_safety(snapshot)
    band_balance = mix_review.mix_band_balance(snapshot)
    tracks = [dict(row) for row in snapshot.get("tracks", []) if isinstance(row, dict)]
    master = next((row for row in tracks if _as_int(row.get("index")) == 0), None)
    master_peak = _as_float(master.get("peak_db")) if master else None
    findings = [
        _mix_finding_summary(row, index=index)
        for index, row in enumerate(low_end.get("findings") or [], start=1)
    ]
    low_tracks = [
        {
            **dict(row),
            "low_end": True,
            "low_end_role": _low_end_role(row.get("name")),
        }
        for row in low_end.get("low_end_tracks") or []
        if isinstance(row, dict)
    ]
    levels_valid = bool(low_end.get("levels_valid"))
    health_score = low_end_health_score(
        high=sum(1 for row in findings if row["severity"] in {"high", "critical"}),
        medium=sum(1 for row in findings if row["severity"] in {"medium", "warning"}),
        low=sum(1 for row in findings if row["severity"] == "low"),
        stereo_risks=sum(
            1
            for row in low_tracks
            if (
                abs(_as_float(row.get("pan")) or 0.0) >= 0.2
                or abs(_as_float(row.get("stereo_sep")) or 0.0) >= 0.25
            )
        ),
        levels_valid=levels_valid,
    )
    evidence_mode = _snapshot_evidence_mode(snapshot)
    return {
        "ok": True,
        "state": "live",
        "workflow": "low_end_analysis",
        "title": "Low-End Analysis",
        "evidence_mode": evidence_mode,
        "generated_at": _now_iso(),
        "summary": {
            "health_score": health_score,
            "health_label": _mix_health_label(health_score),
            "levels_valid": levels_valid,
            "playing": bool(snapshot.get("playing")),
            "peak_source": (snapshot.get("peak_window") or {}).get("source"),
            "master_peak_db": _round_optional(master_peak),
            "master_headroom_db": _round_optional(
                -master_peak if master_peak is not None else None
            ),
            "low_end_tracks": len(low_tracks),
            "low_end_findings": len(findings),
        },
        "findings": findings,
        "proposals": [],
        "visuals": {
            "band_balance": band_balance,
            "stereo_tracks": low_tracks,
        },
        "details": {
            "tracks": low_tracks,
            "notes": list(low_end.get("notes") or []),
            "limits": [str(low_end.get("analysis_limits") or "")],
            "gather_errors": list(snapshot.get("gather_errors") or []),
            "project_fingerprint": snapshot.get("project_fingerprint"),
            "source_observation_ids": list(snapshot.get("source_observation_ids") or []),
            "low_end": {
                "summary": dict(low_end.get("summary") or {}),
                "tracks": low_tracks,
                "findings": findings,
                "manual_checks": list(low_end.get("manual_checks") or []),
                "analysis_limits": low_end.get("analysis_limits"),
            },
            "kb_policy_refs": kb_policy.rule_refs(MIX_POLICY_RULE_IDS),
        },
        "safety": {"read_only": True, "project_changes": False},
    }


def _low_end_unavailable_report(message: str) -> dict[str, Any]:
    report = _mix_review_unavailable_report(message)
    report["workflow"] = "low_end_analysis"
    report["title"] = "Low-End Analysis"
    report["evidence_mode"] = "no_level_evidence"
    report["findings"][0]["id"] = "low_end_analysis_unavailable"
    report["summary"]["health_score"] = 0
    return report


def _low_end_role(name: Any) -> str:
    normalized = str(name or "").lower()
    if "kick" in normalized:
        return "kick"
    if "sub" in normalized or "808" in normalized:
        return "sub"
    if "bass" in normalized:
        return "bass"
    return "other"


def _snapshot_evidence_mode(snapshot: dict[str, Any]) -> str:
    live_window = snapshot.get("live_window")
    levels_valid = bool(snapshot.get("levels_valid"))
    if isinstance(live_window, dict):
        freshness = live_window.get("freshness")
        captured = _as_float(live_window.get("captured_seconds")) or 0.0
        target = _as_float(live_window.get("target_capture_seconds")) or 0.0
        if freshness == "fresh" and captured >= target > 0:
            return "sufficient_watch_window"
        if freshness == "fresh":
            return "recent_live_meter_window"
    if levels_valid:
        return "short_live_snapshot"
    return "static_snapshot_only"


def _build_low_end_analysis_report(report: dict[str, Any]) -> AnalysisReport:
    summary = dict(report.get("summary") or {})
    details = dict(report.get("details") or {})
    low_end = dict(details.get("low_end") or {})
    low_end_findings = [dict(row) for row in low_end.get("findings") or [] if isinstance(row, dict)]
    low_end_tracks = [dict(row) for row in low_end.get("tracks") or [] if isinstance(row, dict)]
    levels_valid = bool(summary.get("levels_valid"))
    ok = bool(report.get("ok"))
    analysis_mode = _low_end_analysis_mode(summary)
    evidence_mode = str(report.get("evidence_mode") or "static_snapshot_only")
    required = 3
    available = 0
    missing: list[str] = []
    if ok:
        available += 1
    else:
        missing.append("fl_session_alive")
    if low_end or low_end_tracks:
        available += 1
    else:
        missing.append("low_end_metadata")
    if levels_valid:
        available += 1
    else:
        missing.append("live_meter_window")

    coverage = Coverage(required=required, available=available, missing=tuple(missing))
    confidence = confidence_from_coverage(
        required=required,
        available=available,
        evidence_mode=analysis_mode,
    )
    risk = risk_from_severities(tuple(row.get("severity", "info") for row in low_end_findings))
    freshness_status = "fresh" if ok and not missing else "partial" if ok else "unavailable"
    track_index_by_name = _low_end_track_index_by_name(details, low_end_tracks)
    legacy_findings = tuple(
        _low_end_analysis_finding(
            row,
            index=index,
            analysis_mode=analysis_mode,
            confidence_score=confidence,
            track_index_by_name=track_index_by_name,
        )
        for index, row in enumerate(low_end_findings, start=1)
    )
    rule_findings, rule_errors = _low_end_rule_findings(
        low_end_tracks,
        analysis_mode=analysis_mode,
        confidence_score=confidence,
    )
    findings = (*legacy_findings, *rule_findings)
    limits = _unique_strings(
        [
            *list(details.get("limits") or []),
            low_end.get("analysis_limits"),
            (
                "Low-end detection is based on names plus mixer pan, stereo separation, "
                "and peak metadata; it is not true phase-correlation analysis."
            ),
            *[
                f"Declarative low-end rules were skipped: {error}"
                for error in rule_errors
            ],
        ]
    )
    assumptions = _unique_strings(
        [
            "Low-end roles are inferred from names such as kick, sub, bass, 808, or boom.",
            (
                "Mixer metadata is treated as static evidence unless a watch or live "
                "window is present."
            ),
        ]
    )
    stereo_risks = 0
    for track in low_end_tracks:
        pan = _as_float(track.get("pan"))
        stereo_sep = _as_float(track.get("stereo_sep"))
        if (pan is not None and abs(pan) >= 0.2) or (
            stereo_sep is not None and abs(stereo_sep) >= 0.25
        ):
            stereo_risks += 1

    health_score = low_end_health_score(
        high=sum(
            1
            for row in low_end_findings
            if str(row.get("severity", "")).lower() in ("high", "critical")
        ),
        medium=sum(
            1
            for row in low_end_findings
            if str(row.get("severity", "")).lower() in ("medium", "warning")
        ),
        low=sum(
            1
            for row in low_end_findings
            if str(row.get("severity", "")).lower() == "low"
        ),
        stereo_risks=stereo_risks,
        levels_valid=levels_valid,
    )
    created_at, valid_until = _report_validity(report.get("generated_at"))
    source_observations = tuple(details.get("source_observation_ids") or ())
    return AnalysisReport(
        workflow="low_end_analysis",
        title="Low-End Analysis",
        analysis_mode=analysis_mode,
        evidence_mode=evidence_mode,
        ruleset_id=LOW_END_RULESET_ID,
        ruleset_version=LOW_END_RULESET_VERSION,
        profile_id=LOW_END_PROFILE_ID,
        created_at=created_at,
        project_fingerprint=details.get("project_fingerprint"),
        freshness=Freshness(
            status=freshness_status,
            created_at=created_at,
            valid_until=valid_until,
            source_observation_ids=source_observations,
            details="Control Center legacy payload adapted into the shared analysis contract.",
        ),
        coverage=coverage,
        prerequisites=(
            Prerequisite(
                "fl_session_alive",
                "ok" if ok else "unavailable",
                None if ok else str(report.get("error") or "Mix data unavailable."),
            ),
            Prerequisite("static_project_snapshot", "ok" if ok else "unavailable"),
            Prerequisite("live_meter_window", "ok" if levels_valid else "missing"),
        ),
        risk_score=risk,
        health_score=health_score,
        confidence_score=confidence,
        findings=findings,
        assumptions=tuple(assumptions),
        limitations=tuple(limits),
        source_observations=source_observations,
        manual_checks=tuple(
            dict(row) for row in low_end.get("manual_checks") or [] if isinstance(row, dict)
        ),
        next_actions=(
            {
                "type": "evidence_upgrade",
                "id": "rendered_audio_features",
                "label": "Analyze a manually bounced audio file for stronger low-end evidence.",
            },
        ),
        safety={"read_only": True, "project_changes": False},
        metadata={
            "legacy_workflow": report.get("workflow"),
            "peak_source": summary.get("peak_source"),
            "low_end_summary": low_end.get("summary") or {},
            "low_end_track_count": len(low_end_tracks),
            "rule_evaluation_errors": rule_errors,
        },
    )


def _low_end_analysis_mode(summary: dict[str, Any]) -> str:
    peak_source = str(summary.get("peak_source") or "").lower()
    if peak_source == "watch":
        return "watch_window"
    if bool(summary.get("levels_valid")):
        return "live_runtime"
    return "static_snapshot"


def _low_end_analysis_finding(
    row: dict[str, Any],
    *,
    index: int,
    analysis_mode: str,
    confidence_score: int,
    track_index_by_name: dict[str, int],
) -> Finding:
    rule = str(row.get("rule") or row.get("id") or "low_end_finding")
    severity = str(row.get("severity") or "info")
    track_index = _low_end_finding_track_index(row, track_index_by_name)
    entities = ()
    if track_index is not None:
        entities = (
            EntityRef(
                "mixer_track",
                mixer_entity_id(track_index),
                str(row.get("track") or _display_track_name(track_index, None)),
            ),
        )
    return Finding(
        id=str(row.get("id") or f"{rule}_{index}"),
        rule_id=f"low_end.{rule}",
        title=str(row.get("title") or _mix_rule_title(rule)),
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=confidence_score,
        evidence_mode=analysis_mode,
        entities=entities,
        evidence=(
            {
                "detail": row.get("detail"),
                "track": row.get("track"),
                "evidence": row.get("evidence"),
                "proposed_fix": row.get("proposed_fix") or {},
            },
        ),
        limitations=("Mixer pan/stereo metadata cannot prove true low-band phase behavior.",),
        metadata={"legacy_finding": row},
    )


def _low_end_rule_findings(
    low_end_tracks: list[dict[str, Any]],
    *,
    analysis_mode: str,
    confidence_score: int,
) -> tuple[tuple[Finding, ...], list[str]]:
    findings: list[Finding] = []
    errors: list[str] = []
    for offset, track in enumerate(low_end_tracks, start=1):
        track_index = _as_int(track.get("track"))
        pan = _as_float(track.get("pan"))
        stereo_sep = _as_float(track.get("stereo_sep"))
        observation = {
            "track": {
                "low_end_role": str(
                    track.get("low_end_role") or _low_end_role(track.get("name"))
                ),
                "stereo_risk": (
                    pan is not None
                    and abs(pan) >= 0.2
                    or stereo_sep is not None
                    and abs(stereo_sep) >= 0.25
                ),
                "pan": pan,
                "stereo_sep": stereo_sep,
            }
        }
        try:
            matches = evaluate_rules(observation, LOW_END_METADATA_RULES)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue
        for match in matches:
            entities = ()
            if track_index is not None:
                entities = (
                    EntityRef(
                        "mixer_track",
                        mixer_entity_id(track_index),
                        str(
                            track.get("name")
                            or _display_track_name(track_index, None)
                        ),
                    ),
                )
            findings.append(
                Finding(
                    id=f"{match.id}:{track_index if track_index is not None else offset}",
                    rule_id=match.rule_id,
                    title=match.title,
                    severity=match.severity,
                    risk_score=match.risk_score,
                    confidence_score=min(
                        confidence_score,
                        match.confidence_score,
                    ),
                    evidence_mode=analysis_mode,
                    entities=entities,
                    evidence=(
                        *match.evidence,
                        {
                            "pan": pan,
                            "stereo_sep": stereo_sep,
                            "name_based_role": observation["track"]["low_end_role"],
                        },
                    ),
                    assumptions=(
                        "The low-end role is inferred from the mixer track name.",
                    ),
                    limitations=(
                        "Mixer metadata cannot prove low-band phase or mono compatibility.",
                    ),
                    metadata={
                        **match.metadata,
                        "declarative_rule": True,
                    },
                )
            )
    return tuple(findings), errors


def _low_end_track_index_by_name(
    details: dict[str, Any],
    low_end_tracks: list[dict[str, Any]],
) -> dict[str, int]:
    rows = [
        *low_end_tracks,
        *[dict(row) for row in details.get("tracks") or [] if isinstance(row, dict)],
    ]
    out: dict[str, int] = {}
    for row in rows:
        idx = _as_int(row.get("track"))
        name = str(row.get("name") or "").strip().lower()
        if idx is not None and name:
            out[name] = idx
    return out


def _low_end_finding_track_index(
    row: dict[str, Any],
    track_index_by_name: dict[str, int],
) -> int | None:
    fix = row.get("proposed_fix") if isinstance(row.get("proposed_fix"), dict) else {}
    args = fix.get("args") if isinstance(fix.get("args"), dict) else {}
    idx = _as_int(args.get("track"))
    if idx is not None:
        return idx
    track = row.get("track")
    if str(track).strip().lower() == "master":
        return 0
    return track_index_by_name.get(str(track or "").strip().lower())


def _mix_review_unavailable_report(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "unavailable",
        "workflow": "mix_review",
        "title": "Mix Review",
        "evidence_mode": "no_level_evidence",
        "generated_at": _now_iso(),
        "error": message,
        "summary": {
            "health_score": 0,
            "health_label": "Unavailable",
            "tracks": 0,
            "used_tracks": 0,
            "levels_valid": False,
            "playing": False,
            "peak_source": "none",
            "findings": 1,
            "high": 0,
            "medium": 0,
            "low": 0,
            "proposals": 0,
            "master_peak_db": None,
            "master_headroom_db": None,
            "hot_tracks": 0,
            "muted_tracks": 0,
            "solo_tracks": 0,
            "eq_coverage_pct": 0,
            "compressor_coverage_pct": 0,
            "low_end_findings": 0,
        },
        "findings": [
            {
                "id": "mix_review_unavailable",
                "severity": "warning",
                "rule": "unavailable",
                "title": "Mix data unavailable",
                "detail": message,
                "track": None,
                "evidence": message,
            }
        ],
        "proposals": [],
        "visuals": {
            "level_tracks": [],
            "stereo_tracks": [],
            "band_balance": {
                "bands_pct": {"low": 0, "mid": 0, "high": 0},
                "tracks": {"low": [], "mid": [], "high": []},
            },
        },
        "details": {
            "tracks": [],
            "notes": ["Mix Review is read-only and does not modify FL Studio project state."],
            "limits": ["Level findings require playback or a recent Mix Review watch capture."],
            "gather_errors": [],
            "low_end": {
                "summary": {},
                "tracks": [],
                "findings": [],
                "manual_checks": [],
            },
            "kb_policy_refs": kb_policy.rule_refs(MIX_POLICY_RULE_IDS),
        },
        "safety": {"read_only": True, "project_changes": False},
    }


def _build_mix_review_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    diagnosis = mix_review.diagnose(snapshot)
    fix_plan = mix_review.plan_fixes(snapshot)
    gain_plan = mix_review.gain_stage_plan(snapshot)
    band_balance = mix_review.mix_band_balance(snapshot)
    low_end = mix_review.low_end_stereo_safety(snapshot)
    tracks = [dict(row) for row in snapshot.get("tracks", []) if isinstance(row, dict)]
    used_tracks = [row for row in tracks if _mix_track_used(row)]
    master = next((row for row in tracks if _as_int(row.get("index")) == 0), None)

    findings = [
        _mix_finding_summary(finding, index=index)
        for index, finding in enumerate(diagnosis.get("findings") or [], start=1)
    ]
    proposals = _mix_proposal_summaries(
        list(fix_plan.get("plans") or []),
        list(gain_plan.get("plans") or []),
    )
    high = sum(1 for row in findings if row["severity"] == "high")
    medium = sum(1 for row in findings if row["severity"] == "medium")
    low = sum(1 for row in findings if row["severity"] == "low")
    levels_valid = bool(snapshot.get("levels_valid"))
    master_peak = _as_float(master.get("peak_db")) if master else None
    health_score = mix_health_score(
        high=high,
        medium=medium,
        low=low,
        levels_valid=levels_valid,
        master_peak=master_peak,
    )
    audible = [row for row in used_tracks if _as_int(row.get("index")) != 0 and not row.get("mute")]
    eq_count = sum(1 for row in audible if _mix_has_plugin_keyword(row, ("eq",)))
    comp_count = sum(
        1
        for row in audible
        if _mix_has_plugin_keyword(
            row,
            ("comp", "limit", "max", "ott", "dynamics", "level"),
        )
    )
    hot_tracks = 0
    for row in audible:
        peak = _as_float(row.get("peak_db"))
        if peak is not None and peak > -3.0:
            hot_tracks += 1
    master_headroom = -master_peak if master_peak is not None else None

    notes = [
        *list(diagnosis.get("notes") or []),
        *list(fix_plan.get("notes") or []),
        *list(gain_plan.get("notes") or []),
        *list(low_end.get("notes") or []),
    ]
    limits = []
    if not levels_valid:
        limits.append("Level findings require playback or a recent full-song watch capture.")
    limits.append("Tone balance is a rough name-and-peak estimate, not an output spectrum.")
    if low_end.get("analysis_limits"):
        limits.append(str(low_end["analysis_limits"]))

    return {
        "ok": True,
        "state": "live",
        "workflow": "mix_review",
        "title": "Mix Review",
        "evidence_mode": diagnosis.get("evidence_mode", "static_snapshot_only"),
        "generated_at": _now_iso(),
        "summary": {
            "health_score": health_score,
            "health_label": _mix_health_label(health_score),
            "tracks": len(tracks),
            "used_tracks": len(used_tracks),
            "levels_valid": levels_valid,
            "playing": bool(snapshot.get("playing")),
            "peak_source": (snapshot.get("peak_window") or {}).get("source"),
            "findings": len(findings),
            "high": high,
            "medium": medium,
            "low": low,
            "proposals": len(proposals),
            "master_peak_db": _round_optional(master_peak),
            "master_headroom_db": _round_optional(master_headroom),
            "hot_tracks": hot_tracks,
            "muted_tracks": sum(1 for row in tracks if row.get("mute")),
            "solo_tracks": sum(1 for row in tracks if row.get("solo")),
            "eq_coverage_pct": _coverage_pct(eq_count, len(audible)),
            "compressor_coverage_pct": _coverage_pct(comp_count, len(audible)),
            "low_end_findings": len(low_end.get("findings") or []),
        },
        "findings": findings,
        "proposals": proposals,
        "visuals": {
            "level_tracks": _mix_level_tracks(tracks),
            "stereo_tracks": _mix_stereo_tracks(tracks),
            "band_balance": band_balance,
        },
        "details": {
            "tracks": [_mix_track_detail(row) for row in tracks],
            "notes": _unique_strings(notes),
            "limits": _unique_strings(limits),
            "gather_errors": list(snapshot.get("gather_errors") or []),
            "project_fingerprint": snapshot.get("project_fingerprint"),
            "source_observation_ids": list(snapshot.get("source_observation_ids") or []),
            "template_context": templates.compact_context(
                diagnosis.get("template_context") or snapshot.get("template_context") or {}
            ),
            "low_end": {
                "summary": low_end.get("summary") or {},
                "tracks": list(low_end.get("low_end_tracks") or []),
                "findings": [
                    _mix_finding_summary(finding, index=index)
                    for index, finding in enumerate(low_end.get("findings") or [], start=1)
                ],
                "manual_checks": list(low_end.get("manual_checks") or []),
            },
            "kb_policy_refs": kb_policy.rule_refs(MIX_POLICY_RULE_IDS),
        },
        "safety": {"read_only": True, "project_changes": False},
    }


def _mix_finding_summary(finding: dict[str, Any], *, index: int) -> dict[str, Any]:
    rule = str(finding.get("rule") or "finding")
    return {
        "id": f"{rule}_{index}",
        "severity": str(finding.get("severity") or "info"),
        "rule": rule,
        "title": _mix_rule_title(rule),
        "detail": str(finding.get("message") or finding.get("evidence") or ""),
        "track": finding.get("track"),
        "evidence": finding.get("evidence"),
        "proposed_fix": finding.get("proposed_fix") or {},
        "kb_rule_ids": list(finding.get("kb_rule_ids") or []),
    }


def _mix_proposal_summaries(
    fix_plans: list[dict[str, Any]],
    gain_plans: list[dict[str, Any]],
    limit: int = 12,
) -> list[dict[str, Any]]:
    out = []
    seen: set[tuple[Any, Any, Any]] = set()
    for source, plans in (("mix_review", fix_plans), ("gain_stage", gain_plans)):
        for plan in plans:
            key = (plan.get("kind"), plan.get("track"), plan.get("target_fader_db"))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "id": f"{source}_{len(out) + 1}",
                    "source": source,
                    "kind": plan.get("kind"),
                    "severity": plan.get("severity") or "info",
                    "track": plan.get("track"),
                    "track_name": plan.get("track_name"),
                    "title": plan.get("human") or plan.get("reason") or "Mix proposal",
                    "detail": plan.get("reason") or plan.get("note") or "",
                    "actionable": bool(plan.get("actionable")),
                    "alternative": bool(plan.get("alternative")),
                    "current_fader_db": _round_optional(plan.get("current_fader_db")),
                    "target_fader_db": _round_optional(plan.get("target_fader_db")),
                    "current_peak_db": _round_optional(plan.get("current_peak_db")),
                    "target_peak_db": _round_optional(plan.get("target_peak_db")),
                    "kb_rule_ids": list(plan.get("kb_rule_ids") or []),
                }
            )
            if len(out) >= limit:
                return out
    return out


def _mix_level_tracks(tracks: list[dict[str, Any]], limit: int = 18) -> list[dict[str, Any]]:
    rows = []
    for row in tracks:
        if not _mix_track_used(row):
            continue
        peak = _as_float(row.get("peak_db"))
        fader = _as_float(row.get("vol_db"))
        rows.append(
            {
                "track": _as_int(row.get("index")),
                "name": _mix_track_name(row),
                "peak_db": _round_optional(peak),
                "avg_db": _round_optional(row.get("peak_avg_db")),
                "fader_db": _round_optional(fader),
                "mute": bool(row.get("mute")),
                "solo": bool(row.get("solo")),
                "role": row.get("template_role") or "insert",
                "level_state": _mix_level_state(peak, row),
            }
        )
    rows.sort(
        key=lambda item: (
            1 if item["track"] == 0 else 0,
            _mix_peak_sort_value(item.get("peak_db")),
        ),
        reverse=True,
    )
    master = [row for row in rows if row["track"] == 0]
    others = [row for row in rows if row["track"] != 0]
    return (master + others)[:limit]


def _mix_stereo_tracks(tracks: list[dict[str, Any]], limit: int = 14) -> list[dict[str, Any]]:
    rows = []
    for row in tracks:
        if _as_int(row.get("index")) == 0 or not _mix_track_used(row):
            continue
        pan = _as_float(row.get("pan"))
        stereo = _as_float(row.get("stereo_sep"))
        peak = _as_float(row.get("peak_db"))
        if pan is None and stereo is None and peak is None:
            continue
        rows.append(
            {
                "track": _as_int(row.get("index")),
                "name": _mix_track_name(row),
                "pan": _round_optional(pan),
                "stereo_sep": _round_optional(stereo),
                "peak_db": _round_optional(peak),
                "low_end": _mix_name_has_any(
                    row,
                    ("kick", "sub", "bass", "808", "boom"),
                ),
            }
        )
    rows.sort(
        key=lambda item: (
            bool(item.get("low_end")),
            abs(item.get("pan") or 0),
            abs(item.get("stereo_sep") or 0),
            _mix_peak_sort_value(item.get("peak_db")),
        ),
        reverse=True,
    )
    return rows[:limit]


def _mix_track_detail(row: dict[str, Any]) -> dict[str, Any]:
    plugins = [
        {
            "slot": plugin.get("slot"),
            "name": plugin.get("name"),
        }
        for plugin in row.get("plugins") or []
        if isinstance(plugin, dict)
    ]
    role = row.get("template_role")
    if not role:
        role = "master" if _as_int(row.get("index")) == 0 else "insert"
    return {
        "track": _as_int(row.get("index")),
        "name": _mix_track_name(row),
        "role": role,
        "fader_db": _round_optional(row.get("vol_db")),
        "peak_db": _round_optional(row.get("peak_db")),
        "pan": _round_optional(row.get("pan")),
        "stereo_sep": _round_optional(row.get("stereo_sep")),
        "mute": bool(row.get("mute")),
        "solo": bool(row.get("solo")),
        "plugins": plugins,
        "routes_to": _normalise_routes(row.get("routes_to") or []),
        "used": _mix_track_used(row),
    }


def _mix_track_used(row: dict[str, Any]) -> bool:
    idx = _as_int(row.get("index"))
    if idx == 0:
        return True
    if row.get("template_role") == templates.ROLE_RESERVED_PLACEHOLDER:
        return False
    if row.get("plugins"):
        return True
    name = _mix_track_name(row)
    if name and name.lower() not in {"master", f"insert {idx}".lower()}:
        return True
    peak = _as_float(row.get("peak_db"))
    if peak is not None and peak > -60.0:
        return True
    return any(
        _as_int(route.get("dst") if isinstance(route, dict) else route) not in (None, 0)
        for route in row.get("routes_to") or []
    )


def _mix_level_state(peak: float | None, row: dict[str, Any]) -> str:
    if row.get("mute"):
        return "muted"
    if peak is None:
        return "unknown"
    if peak >= 0:
        return "clip"
    if peak > -1:
        return "risk"
    if peak > -3:
        return "hot"
    if peak < -24:
        return "quiet"
    return "ok"


def _mix_health_label(score: int) -> str:
    if score >= 90:
        return "Good"
    if score >= 75:
        return "Needs Review"
    return "At Risk"


def _mix_rule_title(rule: str) -> str:
    labels = {
        "clipping": "Clipping / Peak Risk",
        "headroom": "Headroom",
        "imbalance": "Level Imbalance",
        "missing_hpf": "Missing High-Pass",
        "missing_compressor": "Missing Dynamics",
        "ungrouped": "Ungrouped Tracks",
        "eq_clash": "EQ Clash",
        "low_end_pan": "Low-End Pan Risk",
        "low_end_width": "Low-End Width Risk",
        "low_end_layering": "Low-End Layering",
        "master_headroom_risk": "Master Headroom",
    }
    return labels.get(rule, rule.replace("_", " ").title())


def _mix_track_name(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip()
    idx = _as_int(row.get("index"))
    if name:
        return name
    return "Master" if idx == 0 else f"Insert {idx}" if idx is not None else "Track"


def _mix_has_plugin_keyword(row: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    for plugin in row.get("plugins") or []:
        name = str((plugin or {}).get("name") or "").lower()
        if any(keyword in name for keyword in keywords):
            return True
    return False


def _mix_name_has_any(row: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    name = _mix_track_name(row).lower()
    return any(keyword in name for keyword in keywords)


def _mix_peak_sort_value(value: Any) -> float:
    numeric = _as_float(value)
    return numeric if numeric is not None else -999.0


def _coverage_pct(count_value: int, total: int) -> int:
    if total <= 0:
        return 0
    return round(100 * count_value / total)


def _round_optional(value: Any, digits: int = 1) -> float | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _unique_strings(values: list[Any]) -> list[str]:
    out = []
    seen = set()
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        out.append(text_value)
    return out


ROUTING_POLICY_RULE_IDS = [
    "preserve_existing_structure_first",
    "channel_rack_workflow_requires_routing_inference",
    "routing_ui_guidance_vs_mcp_write",
    "send_effects_for_shared_space",
]


ORGANIZER_POLICY_RULE_IDS = [
    "preserve_existing_structure_first",
    "instrument_audio_track_workflow",
    "channel_rack_workflow_requires_routing_inference",
    "routing_ui_guidance_vs_mcp_write",
]


def _run_project_organizer(
    state: ControlCenterState,
    *,
    bridge_override: Any | None = None,
) -> dict[str, Any]:
    """Run the read-only Project Organizer workflow for the Control Center UI."""
    if bridge_override is None and hasattr(state, "runtime_client"):
        try:
            return _runtime_client(state).run_workflow("project_organizer")
        except Exception as exc:
            report = _project_organizer_unavailable_report(
                f"{type(exc).__name__}: {exc}"
            )
            analysis = _generic_analysis_report_from_legacy(
                report, "project_organizer", "Organizer"
            )
            return analysis_report_for_control_center(analysis, report)
    bridge = bridge_override
    owns_bridge = bridge is None
    try:
        if bridge is None:
            with state.lock:
                daemon_host, daemon_port = _selected_daemon_endpoint(state)
            bridge = TCPBridge(daemon_host, daemon_port)
        wait = getattr(bridge, "wait_for_heartbeat", None)
        if callable(wait):
            wait(timeout=1.0)
        alive = bool(getattr(bridge, "is_alive", lambda: False)())
        if not alive:
            raise ConnectionError(
                "No fresh FL Studio controller heartbeat. Open FL Studio and refresh "
                "the connection."
            )

        static_snapshot = state.broker.get_static_project_snapshot(bridge)
        channel_routing = list(static_snapshot.channels)
        channel_list = fetch_all_pages(
            bridge,
            protocol.CMD_CHANNEL_LIST,
            "channels",
        ).get("channels", [])
        mixer_tracks = list(static_snapshot.mixer_tracks)
        patterns = list(static_snapshot.patterns)
        playlist_tracks = list(static_snapshot.playlist_tracks)
        routing = list(static_snapshot.routing)
        merged_channels = _merge_channel_snapshots(
            routing_rows=_dict_rows(channel_routing),
            channel_rows=_dict_rows(channel_list),
        )
        report_payload = _build_project_organizer_report(
            channels=merged_channels,
            mixer_tracks=_dict_rows(mixer_tracks),
            patterns=_dict_rows(patterns),
            playlist_tracks=_dict_rows(playlist_tracks),
            routing=_dict_rows(routing),
            template_context=static_snapshot.template_context,
        )
        report_payload.setdefault("details", {}).update(
            {
                "project_fingerprint": static_snapshot.project_fingerprint,
                "source_observation_ids": list(static_snapshot.source_observation_ids),
            }
        )
        analysis_report = _generic_analysis_report_from_legacy(
            report_payload,
            "project_organizer",
            "Organizer",
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return analysis_report_for_control_center(analysis_report, report_payload)
    except Exception as exc:
        report = _project_organizer_unavailable_report(f"{type(exc).__name__}: {exc}")
        analysis_report = _generic_analysis_report_from_legacy(
            report,
            "project_organizer",
            "Organizer",
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return analysis_report_for_control_center(analysis_report, report)
    finally:
        if owns_bridge and bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()


def _generic_analysis_report_from_legacy(
    report: dict[str, Any],
    workflow: str,
    title: str,
) -> AnalysisReport:
    summary = dict(report.get("summary") or {})
    ok = bool(report.get("ok"))
    evidence_mode = str(report.get("evidence_mode") or "static_snapshot_only")
    details = dict(report.get("details") or {})

    available = 0
    missing: list[str] = []
    prereqs: list[Prerequisite] = []

    if ok:
        available += 1
        prereqs.append(Prerequisite("fl_session_alive", "ok"))
    else:
        missing.append("fl_session_alive")
        prereqs.append(Prerequisite("fl_session_alive", "missing"))

    if workflow == "mix_review":
        has_level_evidence = evidence_mode in {
            "short_live_snapshot",
            "recent_live_meter_window",
            "sufficient_watch_window",
        }
        if has_level_evidence:
            available += 1
        else:
            missing.append("live_meter_window")
        playback_status = (
            "ok"
            if evidence_mode == "short_live_snapshot"
            else "skipped"
            if evidence_mode in {"recent_live_meter_window", "sufficient_watch_window"}
            else "missing"
        )
        prereqs.extend(
            (
                Prerequisite("requires_playback", playback_status),
                Prerequisite(
                    "requires_meter_window",
                    "ok" if has_level_evidence else "missing",
                ),
                Prerequisite(
                    "requires_recent_watch",
                    (
                        "ok"
                        if evidence_mode in {"recent_live_meter_window", "sufficient_watch_window"}
                        else "missing"
                    ),
                ),
            )
        )
        required = 2
    else:
        required = 1

    coverage = Coverage(
        required=required,
        available=available,
        missing=tuple(missing),
    )

    legacy_findings = [dict(row) for row in report.get("findings") or [] if isinstance(row, dict)]
    risk = risk_from_severities(tuple(row.get("severity", "info") for row in legacy_findings))
    confidence = confidence_from_coverage(
        required=required,
        available=available,
        evidence_mode=_broad_analysis_mode(evidence_mode),
    )
    freshness_status = "fresh" if ok and not missing else "partial" if ok else "unavailable"
    created_at, valid_until = _report_validity(report.get("generated_at"))
    limitations = list(details.get("limits") or [])
    limitations.extend(f"Missing prerequisite: {item}" for item in missing)
    findings = tuple(
        _generic_analysis_finding(
            row,
            workflow=workflow,
            index=index,
            evidence_mode=_broad_analysis_mode(evidence_mode),
            confidence_score=confidence,
        )
        for index, row in enumerate(legacy_findings, start=1)
    )

    return AnalysisReport(
        workflow=workflow,
        title=title,
        analysis_mode=_broad_analysis_mode(evidence_mode),
        evidence_mode=evidence_mode,
        created_at=created_at,
        project_fingerprint=details.get("project_fingerprint"),
        freshness=Freshness(
            status=freshness_status,
            created_at=created_at,
            valid_until=valid_until,
            source_observation_ids=tuple(details.get("source_observation_ids") or ()),
        ),
        coverage=coverage,
        prerequisites=tuple(prereqs),
        risk_score=risk,
        health_score=summary.get("health_score", summary.get("organization_score")),
        confidence_score=confidence,
        findings=findings,
        limitations=tuple(limitations),
        source_observations=tuple(details.get("source_observation_ids") or ()),
        safety=report.get("safety") or {"read_only": True},
    )


def _broad_analysis_mode(evidence_mode: str) -> str:
    if evidence_mode in {"short_live_snapshot", "recent_live_meter_window"}:
        return "live_runtime"
    if evidence_mode == "sufficient_watch_window":
        return "watch_window"
    return "static_snapshot"


def _report_validity(generated_at: Any, *, ttl_seconds: float = 120.0) -> tuple[str, str]:
    try:
        created = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        created = datetime.now(timezone.utc)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created = created.astimezone(timezone.utc)
    return created.isoformat(), (created + timedelta(seconds=ttl_seconds)).isoformat()


def _generic_analysis_finding(
    row: dict[str, Any],
    *,
    workflow: str,
    index: int,
    evidence_mode: str,
    confidence_score: int,
) -> Finding:
    severity = str(row.get("severity") or "info")
    rule = str(row.get("rule") or row.get("id") or "finding")
    entities: tuple[EntityRef, ...] = ()
    track = _as_int(row.get("track"))
    if track is not None:
        entities = (
            EntityRef(
                "mixer_track",
                mixer_entity_id(track),
                str(row.get("track_name") or row.get("track") or ""),
            ),
        )
    return Finding(
        id=str(row.get("id") or f"{workflow}.{rule}.{index}"),
        rule_id=f"{workflow}.{rule}",
        title=str(row.get("title") or row.get("detail") or rule),
        severity=severity,
        risk_score=risk_from_severities((severity,)),
        confidence_score=confidence_score,
        evidence_mode=evidence_mode,
        entities=entities,
        evidence=(dict(row),),
        metadata={"legacy_finding": row},
    )


def _project_organizer_unavailable_report(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "unavailable",
        "workflow": "project_organizer",
        "title": "Project Organizer",
        "generated_at": _now_iso(),
        "error": message,
        "summary": {
            "organization_score": 0,
            "health_label": "Unavailable",
            "channels": 0,
            "mixer_tracks": 0,
            "patterns": 0,
            "playlist_tracks": 0,
            "diagnostics": 1,
            "proposed_changes": 0,
            "unnamed_channels": 0,
            "routing_cleanup": 0,
            "naming_cleanup": 0,
            "color_readback_missing": 0,
            "grouping_candidates": 0,
        },
        "findings": [
            {
                "id": "project_organizer_unavailable",
                "severity": "warning",
                "title": "Project data unavailable",
                "detail": message,
                "count": 1,
                "items": [],
            }
        ],
        "cleanup_plan": {"steps": []},
        "guided": {
            "state": "unavailable",
            "priority": "Connection",
            "next_issue": "Connect FL Studio before starting Project Organizer.",
            "steps": _organizer_guided_steps(active_index=0),
        },
        "standards": _organizer_standards([], []),
        "grouping": {"candidate_groups": [], "tool": "fl_group_tracks"},
        "details": {
            "items": [],
            "notes": [
                "Project Organizer is read-only in Control Center.",
                "Writes must be approved and run through MCP write-safe tools.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(ORGANIZER_POLICY_RULE_IDS),
        },
        "safety": {
            "read_only": True,
            "project_changes": False,
            "requires_explicit_approval": True,
        },
    }


def _build_project_organizer_report(
    *,
    channels: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    playlist_tracks: list[dict[str, Any]],
    routing: list[dict[str, Any]],
    template_context: dict[str, Any],
) -> dict[str, Any]:
    mixer_by_index = {
        idx: dict(row)
        for row in mixer_tracks
        if (idx := _as_int(row.get("i", row.get("index")))) is not None
    }
    routing_by_index = {
        idx: dict(row)
        for row in routing
        if (idx := _as_int(row.get("i", row.get("index")))) is not None
    }
    track_by_index = {
        idx: {**routing_by_index.get(idx, {}), **mixer_by_index.get(idx, {})}
        for idx in set(mixer_by_index) | set(routing_by_index)
    }
    routes_by_src = {
        idx: _normalise_routes(row.get("routes_to") or []) for idx, row in routing_by_index.items()
    }

    unnamed_channels = [
        _organizer_channel_item(row)
        for row in channels
        if _looks_default_channel_name(row.get("name"))
    ]
    routing_cleanup = [
        _organizer_channel_item(row)
        for row in channels
        if _organizer_channel_needs_routing(row, template_context)
    ]
    unnamed_patterns = [
        _organizer_named_item(row, "pattern")
        for row in patterns
        if _looks_default_named_item(row, "pattern")
    ]
    unnamed_playlist_tracks = [
        _organizer_named_item(row, "playlist_track")
        for row in playlist_tracks
        if _looks_default_named_item(row, "playlist_track")
    ]
    duplicate_mixer = _duplicate_name_rows(mixer_tracks, "mixer")
    duplicate_patterns = _duplicate_name_rows(patterns, "pattern")
    color_readback_missing = _color_readback_missing(
        channels + mixer_tracks + patterns + playlist_tracks
    )
    direct_master_tracks = _direct_master_source_tracks(
        channels=channels,
        routes_by_src=routes_by_src,
        track_by_index=track_by_index,
        template_context=template_context,
    )
    candidate_groups = _organizer_group_candidates(direct_master_tracks)

    findings = _organizer_findings(
        unnamed_channels=unnamed_channels,
        routing_cleanup=routing_cleanup,
        unnamed_patterns=unnamed_patterns,
        unnamed_playlist_tracks=unnamed_playlist_tracks,
        duplicate_mixer=duplicate_mixer,
        duplicate_patterns=duplicate_patterns,
        color_readback_missing=color_readback_missing,
        candidate_groups=candidate_groups,
        template_context=template_context,
    )
    cleanup_steps = _organizer_cleanup_steps(
        unnamed_channels=unnamed_channels,
        routing_cleanup=routing_cleanup,
        duplicate_mixer=duplicate_mixer,
        unnamed_patterns=unnamed_patterns,
        candidate_groups=candidate_groups,
    )
    naming_rules = [
        step
        for step in cleanup_steps
        if step.get("kind") in {"channel_naming", "mixer_naming", "pattern_naming"}
    ]
    color_rules = _organizer_color_standard_rules(channels, mixer_tracks)
    score = organizer_score(
        unnamed_channels=len(unnamed_channels),
        routing_cleanup=len(routing_cleanup),
        unnamed_patterns=len(unnamed_patterns),
        unnamed_playlist_tracks=len(unnamed_playlist_tracks),
        duplicate_mixer=len(duplicate_mixer),
        duplicate_patterns=len(duplicate_patterns),
        grouping_candidates=len(candidate_groups),
    )

    return {
        "ok": True,
        "state": "live",
        "workflow": "project_organizer",
        "title": "Project Organizer",
        "generated_at": _now_iso(),
        "summary": {
            "organization_score": score,
            "health_label": _organizer_health_label(score),
            "channels": len(channels),
            "mixer_tracks": len(mixer_tracks),
            "patterns": len(patterns),
            "playlist_tracks": len(playlist_tracks),
            "diagnostics": len(findings),
            "proposed_changes": len(cleanup_steps),
            "unnamed_channels": len(unnamed_channels),
            "routing_cleanup": len(routing_cleanup),
            "naming_cleanup": len(naming_rules),
            "color_readback_missing": color_readback_missing,
            "grouping_candidates": len(candidate_groups),
        },
        "findings": findings,
        "cleanup_plan": {
            "steps": cleanup_steps,
            "mode": "proposal",
            "apply_tool": "fl_apply_project_cleanup_step",
        },
        "guided": _organizer_guided_context(findings, cleanup_steps),
        "standards": _organizer_standards(naming_rules, color_rules),
        "grouping": {
            "candidate_groups": candidate_groups,
            "tool": "fl_group_tracks",
            "approval_required": True,
        },
        "details": {
            "items": _organizer_detail_rows(
                channels=channels,
                mixer_tracks=mixer_tracks,
                patterns=patterns,
                playlist_tracks=playlist_tracks,
            ),
            "routing_rows": len(routing),
            "template_context": templates.compact_context(template_context),
            "notes": [
                "Project Organizer is read-only in Control Center.",
                "Apply only one approved cleanup step or one named rollback unit at a time.",
                (
                    "Color counts only flag missing readback fields; default FL colors "
                    "are not guessed."
                ),
                (
                    "Playlist clip editing, pattern deletion, plugin loading, save, "
                    "and render are not part of cleanup."
                ),
            ],
            "kb_policy_refs": kb_policy.rule_refs(ORGANIZER_POLICY_RULE_IDS),
        },
        "safety": {
            "read_only": True,
            "project_changes": False,
            "requires_explicit_approval": True,
            "apply_path": "Use MCP write-safe tools after reviewing an exact proposal.",
        },
    }


def _dict_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _merge_channel_snapshots(
    *,
    routing_rows: list[dict[str, Any]],
    channel_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_index = {
        idx: dict(row) for row in channel_rows if (idx := _organizer_item_index(row)) is not None
    }
    merged = []
    seen: set[int] = set()
    for row in routing_rows:
        idx = _organizer_item_index(row)
        if idx is None:
            merged.append(dict(row))
            continue
        seen.add(idx)
        merged.append({**by_index.get(idx, {}), **row})
    for idx, row in sorted(by_index.items()):
        if idx not in seen:
            merged.append(dict(row))
    return merged


def _looks_default_channel_name(name: Any) -> bool:
    value = str(name or "").strip()
    if not value:
        return True
    return value.split(" ")[0] in {"Channel", "Sampler", "Insert", "AudioClip"}


def _looks_default_named_item(row: dict[str, Any], kind: str) -> bool:
    name = str(row.get("name") or "").strip()
    if not name:
        return True
    idx = _organizer_item_index(row)
    if kind == "pattern":
        return idx is not None and name == f"Pattern {idx}"
    if kind == "playlist_track":
        return idx is not None and name in {f"Track {idx}", f"Playlist Track {idx}"}
    return False


def _organizer_item_index(row: dict[str, Any]) -> int | None:
    return _as_int(row.get("index", row.get("i", row.get("channel", row.get("pattern")))))


def _organizer_channel_needs_routing(
    row: dict[str, Any],
    template_context: dict[str, Any],
) -> bool:
    target = _as_int(row.get("target_mixer_track"))
    return target is None or (
        target == 0 and not templates.is_template_bus(template_context, target)
    )


def _organizer_channel_item(row: dict[str, Any]) -> dict[str, Any]:
    idx = _organizer_item_index(row)
    return {
        "type": "channel",
        "index": idx,
        "name": _channel_name(row),
        "kind": _channel_type_label(row),
        "target": _as_int(row.get("target_mixer_track")),
        "target_name": row.get("target_name"),
    }


def _organizer_named_item(row: dict[str, Any], kind: str) -> dict[str, Any]:
    idx = _organizer_item_index(row)
    return {
        "type": kind,
        "index": idx,
        "name": str(row.get("name") or "").strip() or _organizer_default_label(kind, idx),
        "color": row.get("color"),
    }


def _organizer_default_label(kind: str, idx: int | None) -> str:
    if kind == "pattern":
        return f"Pattern {idx}" if idx is not None else "Pattern"
    if kind == "playlist_track":
        return f"Playlist Track {idx}" if idx is not None else "Playlist Track"
    return f"Item {idx}" if idx is not None else "Item"


def _duplicate_name_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        by_name.setdefault(name, []).append(row)
    duplicates = []
    for name, grouped in by_name.items():
        if len(grouped) < 2:
            continue
        for row in grouped[1:]:
            idx = _organizer_item_index(row)
            duplicates.append(
                {
                    "type": kind,
                    "index": idx,
                    "name": name,
                    "suggested_name": f"{name} ({idx})" if idx is not None else name,
                }
            )
    return duplicates


def _color_readback_missing(rows: list[dict[str, Any]]) -> int:
    missing = 0
    for row in rows:
        if "color" not in row and "color_hex" not in row:
            missing += 1
            continue
        color = row.get("color_hex", row.get("color"))
        if color in (None, "", "N/A"):
            missing += 1
    return missing


def _direct_master_source_tracks(
    *,
    channels: list[dict[str, Any]],
    routes_by_src: dict[int, list[dict[str, Any]]],
    track_by_index: dict[int, dict[str, Any]],
    template_context: dict[str, Any],
) -> list[dict[str, Any]]:
    source_tracks: dict[int, dict[str, Any]] = {}
    for channel in channels:
        target = _as_int(channel.get("target_mixer_track"))
        if target in (None, 0) or templates.is_template_bus(template_context, target):
            continue
        routes = routes_by_src.get(target, [])
        if not any(_as_int(route.get("dst")) == 0 for route in routes):
            continue
        source_tracks.setdefault(
            target,
            {
                "track": target,
                "name": _track_name(track_by_index, target),
                "channels": [],
            },
        )["channels"].append(_channel_name(channel))
    return list(source_tracks.values())


def _organizer_group_candidates(
    direct_master_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(direct_master_tracks) < 2:
        return []
    groups: dict[str, list[dict[str, Any]]] = {
        "Drum Bus": [],
        "Bass Bus": [],
        "Music Bus": [],
        "Vocal Bus": [],
        "FX Bus": [],
    }
    fallback: list[dict[str, Any]] = []
    for row in direct_master_tracks:
        name = str(row.get("name") or "").lower()
        if any(token in name for token in ("kick", "snare", "hat", "drum", "perc", "clap")):
            groups["Drum Bus"].append(row)
        elif any(token in name for token in ("bass", "sub", "808")):
            groups["Bass Bus"].append(row)
        elif any(token in name for token in ("vox", "vocal", "voice", "lead vocal")):
            groups["Vocal Bus"].append(row)
        elif any(token in name for token in ("fx", "riser", "impact", "sweep")):
            groups["FX Bus"].append(row)
        else:
            fallback.append(row)
    if len(fallback) >= 2:
        groups["Music Bus"].extend(fallback)
    candidates = []
    for name, rows in groups.items():
        if len(rows) < 2:
            continue
        candidates.append(
            {
                "name": name,
                "sources": [row["track"] for row in rows if row.get("track") is not None],
                "source_names": [row["name"] for row in rows],
                "tool": "fl_group_tracks",
                "risk": "medium",
                "requires_bus": True,
            }
        )
    return candidates[:4]


def _organizer_findings(
    *,
    unnamed_channels: list[dict[str, Any]],
    routing_cleanup: list[dict[str, Any]],
    unnamed_patterns: list[dict[str, Any]],
    unnamed_playlist_tracks: list[dict[str, Any]],
    duplicate_mixer: list[dict[str, Any]],
    duplicate_patterns: list[dict[str, Any]],
    color_readback_missing: int,
    candidate_groups: list[dict[str, Any]],
    template_context: dict[str, Any],
) -> list[dict[str, Any]]:
    findings = []
    _append_organizer_finding(
        findings,
        "unnamed_channels",
        "warning",
        "Default Channel Names",
        "Channels with empty or default-looking names.",
        unnamed_channels,
    )
    _append_organizer_finding(
        findings,
        "routing_cleanup",
        "critical",
        "Channels Need Mixer Targets",
        "Channels routed only to Master or with unknown routing.",
        routing_cleanup,
    )
    _append_organizer_finding(
        findings,
        "unnamed_patterns",
        "warning",
        "Default Pattern Names",
        "Patterns with empty or default-looking names.",
        unnamed_patterns,
    )
    _append_organizer_finding(
        findings,
        "unnamed_playlist_tracks",
        "info",
        "Playlist Track Names",
        "Playlist tracks with empty or default-looking names.",
        unnamed_playlist_tracks,
    )
    _append_organizer_finding(
        findings,
        "duplicate_mixer_names",
        "warning",
        "Duplicate Mixer Names",
        "Mixer tracks sharing the same visible name.",
        duplicate_mixer,
    )
    _append_organizer_finding(
        findings,
        "duplicate_pattern_names",
        "warning",
        "Duplicate Pattern Names",
        "Patterns sharing the same visible name.",
        duplicate_patterns,
    )
    if color_readback_missing:
        findings.append(
            {
                "id": "color_readback_missing",
                "severity": "info",
                "title": "Color Readback Limited",
                "detail": "Some rows did not include color data in the read-only snapshot.",
                "count": color_readback_missing,
                "items": [],
            }
        )
    if candidate_groups:
        findings.append(
            {
                "id": "grouping_candidates",
                "severity": "info",
                "title": "Possible Mixer Groups",
                "detail": "Direct Master source tracks could be grouped after bus review.",
                "count": len(candidate_groups),
                "items": candidate_groups,
            }
        )
    compact_template = templates.compact_context(template_context)
    if compact_template:
        findings.append(
            {
                "id": "template_context",
                "severity": "ok",
                "title": "Template Context Detected",
                "detail": f"{compact_template.get('template_name')} structure is preserved.",
                "count": 1,
                "items": [],
            }
        )
    if not findings:
        findings.append(
            {
                "id": "organizer_clear",
                "severity": "ok",
                "title": "No Organizer Blockers",
                "detail": "The read-only organizer scan did not find naming or routing cleanup.",
                "count": 0,
                "items": [],
            }
        )
    return findings


def _append_organizer_finding(
    findings: list[dict[str, Any]],
    finding_id: str,
    severity: str,
    title: str,
    detail: str,
    items: list[dict[str, Any]],
) -> None:
    if not items:
        return
    findings.append(
        {
            "id": finding_id,
            "severity": severity,
            "title": title,
            "detail": detail,
            "count": len(items),
            "items": items[:8],
        }
    )


def _organizer_cleanup_steps(
    *,
    unnamed_channels: list[dict[str, Any]],
    routing_cleanup: list[dict[str, Any]],
    duplicate_mixer: list[dict[str, Any]],
    unnamed_patterns: list[dict[str, Any]],
    candidate_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    steps = []
    for item in routing_cleanup[:6]:
        channel = item.get("index")
        if channel is None:
            continue
        steps.append(
            _organizer_step(
                step_id=f"route_channel_{channel}",
                kind="channel_routing",
                priority="high",
                title=f"Route channel {channel} to a free mixer track",
                detail="Creates a one-step routing proposal using an existing free mixer track.",
                tool="fl_apply_project_cleanup_step",
                params={"routing": [{"channel": channel, "mode": "free"}], "approved": True},
                risk="low",
            )
        )
    for item in unnamed_channels[:6]:
        channel = item.get("index")
        if channel is None:
            continue
        suggested = _suggest_organizer_channel_name(item)
        steps.append(
            _organizer_step(
                step_id=f"rename_channel_{channel}",
                kind="channel_naming",
                priority="medium",
                title=f"Rename channel {channel} to {suggested}",
                detail="Uses the current channel type and mixer target as naming evidence.",
                tool="fl_apply_project_cleanup_step",
                params={
                    "renames": [{"type": "channel", "index": channel, "name": suggested}],
                    "approved": True,
                },
                risk="low",
            )
        )
    for item in duplicate_mixer[:4]:
        track = item.get("index")
        if track is None:
            continue
        steps.append(
            _organizer_step(
                step_id=f"rename_mixer_{track}",
                kind="mixer_naming",
                priority="low",
                title=f"Rename mixer track {track} to {item.get('suggested_name')}",
                detail="Avoids duplicate mixer labels while preserving the original name.",
                tool="fl_apply_project_cleanup_step",
                params={
                    "renames": [
                        {
                            "type": "mixer",
                            "index": track,
                            "name": item.get("suggested_name"),
                        }
                    ],
                    "approved": True,
                },
                risk="low",
            )
        )
    for item in unnamed_patterns[:4]:
        pattern = item.get("index")
        if pattern is None:
            continue
        steps.append(
            _organizer_step(
                step_id=f"rename_pattern_{pattern}",
                kind="pattern_naming",
                priority="low",
                title=f"Rename pattern {pattern}",
                detail="Pattern names use the pattern domain tool and need the same approval flow.",
                tool="fl_pattern",
                params={"action": "set_name", "index": pattern, "name": f"Pattern {pattern}"},
                risk="low",
            )
        )
    for group in candidate_groups[:2]:
        steps.append(
            _organizer_step(
                step_id=f"group_{str(group.get('name', 'bus')).lower().replace(' ', '_')}",
                kind="mixer_grouping",
                priority="medium",
                title=f"Prepare {group.get('name')}",
                detail="Select an existing bus track before applying grouped routing.",
                tool="fl_group_tracks",
                params={
                    "sources": group.get("sources", []),
                    "bus": "select_existing_bus",
                    "name": group.get("name"),
                    "approved": True,
                },
                risk="medium",
            )
        )
    return steps[:12]


def _organizer_step(
    *,
    step_id: str,
    kind: str,
    priority: str,
    title: str,
    detail: str,
    tool: str,
    params: dict[str, Any],
    risk: str,
) -> dict[str, Any]:
    return {
        "id": step_id,
        "kind": kind,
        "priority": priority,
        "title": title,
        "detail": detail,
        "tool": tool,
        "params": params,
        "risk": risk,
        "requires_explicit_approval": True,
        "readback": "Read back the affected channel, mixer, pattern, or route after applying.",
        "rollback": "Rollback through the MCP changelog if the result is not intended.",
    }


def _suggest_organizer_channel_name(item: dict[str, Any]) -> str:
    target_name = str(item.get("target_name") or "").strip()
    if target_name and target_name.lower() != "master" and not target_name.startswith("Insert "):
        return target_name
    idx = item.get("index")
    kind = str(item.get("kind") or "channel").strip().lower()
    if kind == "audioclip":
        return f"Audio Clip {idx}"
    if kind == "genplug":
        return f"Instrument {idx}"
    return f"Channel {idx}"


def _organizer_color_standard_rules(
    channels: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rules = []
    for row in channels[:6]:
        idx = _organizer_item_index(row)
        if idx is None:
            continue
        ctype = _channel_type_label(row).lower()
        color = "#55EF87" if "audio" in ctype else "#27D7FF"
        rules.append({"type": "channel", "index": idx, "hex": color})
    bus_tracks = [
        row
        for row in mixer_tracks
        if _looks_like_bus_name(row.get("name")) and _organizer_item_index(row) is not None
    ]
    for row in bus_tracks[:4]:
        rules.append({"type": "mixer", "index": _organizer_item_index(row), "hex": "#9D75FF"})
    return rules[:10]


def _organizer_standards(
    naming_rules: list[dict[str, Any]],
    color_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "naming": {
            "tool": "fl_apply_naming_standard",
            "style": "dynamic",
            "suggested_rule_count": len(naming_rules),
            "rules": [
                _standard_naming_rule_from_step(step)
                for step in naming_rules
                if _standard_naming_rule_from_step(step)
            ],
            "approval_required": True,
        },
        "color": {
            "tool": "fl_apply_color_standard",
            "style": "dynamic",
            "suggested_rule_count": len(color_rules),
            "rules": color_rules,
            "approval_required": True,
        },
    }


def _standard_naming_rule_from_step(step: dict[str, Any]) -> dict[str, Any] | None:
    renames = step.get("params", {}).get("renames")
    if not isinstance(renames, list) or not renames:
        return None
    first = renames[0]
    if not isinstance(first, dict):
        return None
    return {
        "type": first.get("type"),
        "index": first.get("index"),
        "name": first.get("name"),
    }


def _organizer_guided_context(
    findings: list[dict[str, Any]],
    cleanup_steps: list[dict[str, Any]],
) -> dict[str, Any]:
    next_step = next((step for step in cleanup_steps if step.get("priority") == "high"), None)
    if next_step is None and cleanup_steps:
        next_step = cleanup_steps[0]
    if next_step:
        return {
            "state": "ready",
            "priority": next_step.get("priority", "medium").title(),
            "next_issue": next_step.get("title"),
            "next_tool": next_step.get("tool"),
            "next_step_id": next_step.get("id"),
            "steps": _organizer_guided_steps(active_index=1),
        }
    ok_finding = next((finding for finding in findings if finding.get("severity") == "ok"), None)
    return {
        "state": "clear",
        "priority": "Review",
        "next_issue": ok_finding.get("title") if ok_finding else "No cleanup step is queued.",
        "next_tool": None,
        "next_step_id": None,
        "steps": _organizer_guided_steps(active_index=0),
    }


def _organizer_guided_steps(active_index: int) -> list[dict[str, Any]]:
    labels = [
        ("Scan", "fl_analyze_project_organization"),
        ("Plan", "fl_plan_project_cleanup"),
        ("Approve One Step", "User confirmation"),
        ("Apply", "fl_apply_project_cleanup_step"),
        ("Read Back", "MCP readback and rollback note"),
    ]
    return [
        {
            "label": label,
            "tool": tool,
            "state": (
                "active"
                if index == active_index
                else ("done" if index < active_index else "pending")
            ),
        }
        for index, (label, tool) in enumerate(labels)
    ]


def _organizer_detail_rows(
    *,
    channels: list[dict[str, Any]],
    mixer_tracks: list[dict[str, Any]],
    patterns: list[dict[str, Any]],
    playlist_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in channels[:18]:
        rows.append(
            {
                "area": "Channel",
                "index": _organizer_item_index(row),
                "name": _channel_name(row),
                "status": "Needs name" if _looks_default_channel_name(row.get("name")) else "Named",
                "detail": _organizer_route_detail(row),
            }
        )
    for row in mixer_tracks[:12]:
        idx = _organizer_item_index(row)
        rows.append(
            {
                "area": "Mixer",
                "index": idx,
                "name": _display_track_name(idx or 0, row.get("name")),
                "status": "Default" if _is_default_mixer_name(idx, row.get("name")) else "Named",
                "detail": "Bus-like" if _looks_like_bus_name(row.get("name")) else "Insert",
            }
        )
    for row in patterns[:12]:
        rows.append(
            {
                "area": "Pattern",
                "index": _organizer_item_index(row),
                "name": str(row.get("name") or "").strip() or "Unnamed pattern",
                "status": "Needs name" if _looks_default_named_item(row, "pattern") else "Named",
                "detail": f"Color: {safe_debug_value(row.get('color'))}",
            }
        )
    for row in playlist_tracks[:8]:
        rows.append(
            {
                "area": "Playlist",
                "index": _organizer_item_index(row),
                "name": str(row.get("name") or "").strip() or "Unnamed playlist track",
                "status": "Needs name"
                if _looks_default_named_item(row, "playlist_track")
                else "Named",
                "detail": "Muted" if row.get("mute") else "Visible",
            }
        )
    return rows[:48]


def _organizer_route_detail(row: dict[str, Any]) -> str:
    target = _as_int(row.get("target_mixer_track"))
    if target is None or target == 0:
        return "No mixer target"
    target_name = str(row.get("target_name") or "").strip()
    return f"{target_name} ({target})" if target_name else f"Track {target}"


def safe_debug_value(value: Any) -> str:
    if value in (None, ""):
        return "Unavailable"
    return str(value)


def _organizer_health_label(score: int) -> str:
    if score >= 90:
        return "Organized"
    if score >= 75:
        return "Needs Cleanup"
    return "At Risk"


def _run_routing_audit(
    state: ControlCenterState,
    *,
    bridge_override: Any | None = None,
) -> dict[str, Any]:
    """Run the read-only Routing Audit workflow for the Control Center UI."""
    if bridge_override is None and hasattr(state, "runtime_client"):
        try:
            return _runtime_client(state).run_workflow("routing_audit")
        except Exception as exc:
            report = _routing_unavailable_report(f"{type(exc).__name__}: {exc}")
            analysis = routing_analysis_report_from_legacy_payload(
                report,
                workflow="routing_audit",
                title="Routing Audit",
                created_at=report["generated_at"],
            )
            return analysis_report_for_control_center(analysis, report)
    bridge = bridge_override
    owns_bridge = bridge is None
    try:
        if bridge is None:
            with state.lock:
                daemon_host, daemon_port = _selected_daemon_endpoint(state)
            bridge = TCPBridge(daemon_host, daemon_port)
        wait = getattr(bridge, "wait_for_heartbeat", None)
        if callable(wait):
            wait(timeout=1.0)
        alive = bool(getattr(bridge, "is_alive", lambda: False)())
        if not alive:
            raise ConnectionError(
                "No fresh FL Studio controller heartbeat. Open FL Studio and refresh "
                "the connection."
            )

        static_snapshot = state.broker.get_static_project_snapshot(bridge)
        channels = list(static_snapshot.channels)
        routing = list(static_snapshot.routing)
        template_context = static_snapshot.template_context
        unused_probe = _probe_unused_mixer_tracks(
            bridge,
            tracks=routing,
            channels=channels,
            template_context=template_context,
        )
        analysis_report, legacy_report = _build_routing_audit_report(
            channels=channels,
            routing=routing,
            template_context=template_context,
            unused_mixer_tracks=unused_probe["tracks"],
            unused_mixer_track_truncated=unused_probe["truncated"],
            unused_mixer_track_probe_failed=unused_probe["probe_failed"],
            project_fingerprint=static_snapshot.project_fingerprint,
            source_observation_ids=static_snapshot.source_observation_ids,
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return legacy_report
    except Exception as exc:
        report = _routing_unavailable_report(f"{type(exc).__name__}: {exc}")
        analysis_report = routing_analysis_report_from_legacy_payload(
            report,
            workflow="routing_audit",
            title="Routing Audit",
            created_at=report["generated_at"],
        )
        analysis_report = state.report_store.add_report(analysis_report)
        return analysis_report_for_control_center(analysis_report, report)
    finally:
        if owns_bridge and bridge is not None:
            with contextlib.suppress(Exception):
                bridge.close()


def _routing_unavailable_report(message: str) -> dict[str, Any]:
    report = {
        "ok": False,
        "state": "unavailable",
        "workflow": "routing_audit",
        "title": "Routing Audit",
        "generated_at": _now_iso(),
        "error": message,
        "summary": {
            "health_score": 0,
            "health_label": "Unavailable",
            "channels": 0,
            "mixer_tracks": 0,
            "routes": 0,
            "direct_to_master": 0,
            "unrouted_channels": 0,
            "dead_end_tracks": 0,
            "unused_mixer_tracks": 0,
        },
        "findings": [
            {
                "id": "routing_unavailable",
                "severity": "warning",
                "title": "Routing data unavailable",
                "detail": message,
                "count": 1,
            }
        ],
        "graph": {"nodes": [], "links": [], "omitted_source_count": 0},
        "details": {
            "channels": [],
            "tracks": [],
            "routes": [],
            "policy_notes": [
                "Routing Audit is read-only and does not modify FL Studio project state."
            ],
            "kb_policy_refs": kb_policy.rule_refs(ROUTING_POLICY_RULE_IDS),
        },
        "safety": {"read_only": True, "project_changes": False},
    }

    return report


def _build_routing_audit_report(
    *,
    channels: list[dict[str, Any]],
    routing: list[dict[str, Any]],
    template_context: dict[str, Any] | None = None,
    unused_mixer_tracks: list[dict[str, Any]] | None = None,
    unused_mixer_track_truncated: bool = False,
    unused_mixer_track_probe_failed: bool = False,
    project_fingerprint: str | None = None,
    source_observation_ids: tuple[str, ...] = (),
) -> tuple[AnalysisReport, dict[str, Any]]:
    unrouted_automation_clips = 0
    filtered_channels = []
    for c in channels:
        ctype = _channel_type_label(c).lower()
        target = _as_int(c.get("target_mixer_track"))
        if ("automation" in ctype or "autoclip" in ctype) and (target is None or target == 0):
            unrouted_automation_clips += 1
        else:
            filtered_channels.append(c)
    channels = filtered_channels

    template_context = template_context or templates.classify_topology(routing, routing, channels)
    track_by_index = {
        idx: dict(row)
        for row in routing
        if (idx := _as_int(row.get("i", row.get("index")))) is not None
    }
    routes_by_src: dict[int, list[dict[str, Any]]] = {
        idx: _normalise_routes(row.get("routes_to") or []) for idx, row in track_by_index.items()
    }
    incoming_by_dst: dict[int, list[int]] = {}
    route_rows: list[dict[str, Any]] = []
    for src, routes in routes_by_src.items():
        for route in routes:
            dst = _as_int(route.get("dst"))
            if dst is None:
                continue
            incoming_by_dst.setdefault(dst, []).append(src)
            route_rows.append(
                {
                    "src": src,
                    "src_name": _track_name(track_by_index, src),
                    "dst": dst,
                    "dst_name": route.get("dst_name") or _track_name(track_by_index, dst),
                    "level": route.get("level"),
                }
            )

    targeted_tracks: dict[int, list[dict[str, Any]]] = {}
    unrouted_channels: list[dict[str, Any]] = []
    direct_to_master: list[dict[str, Any]] = []
    dead_end_tracks: dict[int, dict[str, Any]] = {}

    for channel in channels:
        ctype = _channel_type_label(channel)
        target = _as_int(channel.get("target_mixer_track"))
        if target is None or target == 0:
            if ctype != "unknown":
                unrouted_channels.append(_channel_summary(channel, route_state="unrouted"))
            continue

        targeted_tracks.setdefault(target, []).append(channel)
        target_routes = routes_by_src.get(target, [])
        if not target_routes:
            dead_end_tracks[target] = {
                "track": target,
                "name": _track_name(track_by_index, target),
                "channels": len(targeted_tracks.get(target, [])),
            }
            continue

        routes_to_master = any(_as_int(route.get("dst")) == 0 for route in target_routes)
        if (
            routes_to_master
            and ctype == "genplug"
            and not templates.is_template_bus(template_context, target)
        ):
            direct_to_master.append(
                {
                    **_channel_summary(channel, route_state="direct_to_master"),
                    "mixer_track": target,
                    "mixer_name": _track_name(track_by_index, target),
                }
            )

    bus_indices = {
        idx
        for idx, row in track_by_index.items()
        if idx != 0
        and (
            idx in incoming_by_dst
            or templates.is_template_bus(template_context, idx)
            or _looks_like_bus_name(row.get("name"))
        )
    }
    if unused_mixer_tracks is None:
        unused_mixer_tracks = _candidate_unused_mixer_tracks(
            tracks=routing,
            channels=channels,
            template_context=template_context,
        )

    graph = _build_routing_graph(
        channels=channels,
        track_by_index=track_by_index,
        routes_by_src=routes_by_src,
        bus_indices=bus_indices,
    )
    health_score = routing_health_score(
        direct_count=len(direct_to_master),
        unrouted_count=len(unrouted_channels),
        dead_end_count=len(dead_end_tracks),
        unused_count=len(unused_mixer_tracks),
    )

    findings = _routing_findings(
        direct_to_master=direct_to_master,
        unrouted_channels=unrouted_channels,
        dead_end_tracks=list(dead_end_tracks.values()),
        unused_mixer_tracks=unused_mixer_tracks,
        template_context=template_context,
        unused_probe_failed=unused_mixer_track_probe_failed,
    )

    track_details = []
    for idx, _row in sorted(track_by_index.items()):
        track_details.append(
            {
                "track": idx,
                "name": _track_name(track_by_index, idx),
                "role": templates.role_for(template_context, idx)
                or ("bus" if idx in bus_indices else ("master" if idx == 0 else "insert")),
                "incoming_count": len(incoming_by_dst.get(idx, [])),
                "targeted_channel_count": len(targeted_tracks.get(idx, [])),
                "routes_to": routes_by_src.get(idx, []),
            }
        )

    report = {
        "ok": True,
        "state": "live",
        "workflow": "routing_audit",
        "title": "Routing Audit",
        "generated_at": _now_iso(),
        "summary": {
            "health_score": health_score,
            "health_label": _routing_health_label(health_score),
            "channels": len(channels),
            "unrouted_automation_clips": unrouted_automation_clips,
            "mixer_tracks": len(track_by_index),
            "routes": len(route_rows),
            "direct_to_master": len(direct_to_master),
            "unrouted_channels": len(unrouted_channels),
            "dead_end_tracks": len(dead_end_tracks),
            "unused_mixer_tracks": len(unused_mixer_tracks),
            "unused_mixer_track_truncated": unused_mixer_track_truncated,
        },
        "findings": findings,
        "graph": graph,
        "details": {
            "channels": [
                _channel_summary(
                    channel,
                    route_state=_channel_route_state(channel, routes_by_src),
                )
                for channel in channels
            ],
            "tracks": track_details,
            "routes": route_rows,
            "template_context": templates.compact_context(template_context),
            "policy_notes": [
                "Preserve recognizable existing routing structure before proposing cleanup.",
                "Infer Channel Rack to Mixer relationships from channel target tracks.",
                (
                    "Treat plugin insertion, external inputs, and UI drag-and-drop routing "
                    "as manual guidance."
                ),
                "This Control Center audit is read-only; it does not apply cleanup changes.",
            ],
            "kb_policy_refs": kb_policy.rule_refs(ROUTING_POLICY_RULE_IDS),
            "project_fingerprint": project_fingerprint,
            "source_observation_ids": list(source_observation_ids),
        },
        "safety": {"read_only": True, "project_changes": False},
    }
    analysis_report = routing_analysis_report_from_legacy_payload(
        report,
        workflow="routing_audit",
        title="Routing Audit",
        created_at=report["generated_at"],
    )
    return analysis_report, analysis_report_for_control_center(
        analysis_report,
        report,
    )


def _payload_rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _probe_unused_mixer_tracks(
    bridge: Any,
    *,
    tracks: list[dict[str, Any]],
    channels: list[dict[str, Any]],
    template_context: dict[str, Any],
    max_plugin_checks: int = 60,
) -> dict[str, Any]:
    candidates = _candidate_unused_mixer_tracks(
        tracks=tracks,
        channels=channels,
        template_context=template_context,
    )
    unused = []
    probe_failed = False
    for row in candidates[:max_plugin_checks]:
        track = _as_int(row.get("track"))
        if track is None:
            continue
        try:
            slots = bridge.call(protocol.CMD_PLUGIN_LIST, {"track": track}).get("slots") or []
        except Exception:
            probe_failed = True
            break
        if not slots:
            unused.append(row)
    return {
        "tracks": unused,
        "truncated": len(candidates) > max_plugin_checks,
        "probe_failed": probe_failed,
    }


def _candidate_unused_mixer_tracks(
    *,
    tracks: list[dict[str, Any]],
    channels: list[dict[str, Any]],
    template_context: dict[str, Any],
) -> list[dict[str, Any]]:
    targeted = {
        target
        for channel in channels
        if (target := _as_int(channel.get("target_mixer_track"))) is not None
    }
    incoming: dict[int, list[int]] = {}
    for row in tracks:
        src = _as_int(row.get("i", row.get("index")))
        if src is None:
            continue
        for route in _normalise_routes(row.get("routes_to") or []):
            dst = _as_int(route.get("dst"))
            if dst is not None:
                incoming.setdefault(dst, []).append(src)

    unused = []
    for row in tracks:
        idx = _as_int(row.get("i", row.get("index")))
        if idx in (None, 0) or idx in targeted:
            continue
        if incoming.get(idx) or templates.is_reserved_placeholder(template_context, idx):
            continue
        if not _is_default_mixer_name(idx, row.get("name")):
            continue
        unused.append({"track": idx, "name": _display_track_name(idx, row.get("name"))})
    return unused


def _build_routing_graph(
    *,
    channels: list[dict[str, Any]],
    track_by_index: dict[int, dict[str, Any]],
    routes_by_src: dict[int, list[dict[str, Any]]],
    bus_indices: set[int],
    max_sources: int = 18,
) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []

    def add_node(node_id: str, **data: Any) -> None:
        nodes.setdefault(node_id, {"id": node_id, **data})

    def add_link(src: str, dst: str, kind: str, label: str | None = None) -> None:
        links.append({"from": src, "to": dst, "kind": kind, "label": label})

    add_node("master", label=_track_name(track_by_index, 0), column="master", kind="master")
    add_node("unrouted", label="Unrouted", column="buses", kind="unrouted")
    add_node("dead_end", label="No Output", column="buses", kind="dead_end")

    problem_channel_ids = set()
    for channel in channels:
        target = _as_int(channel.get("target_mixer_track"))
        channel_id = _channel_node_id(channel)
        if target in (None, 0) or not routes_by_src.get(target):
            problem_channel_ids.add(channel_id)
            continue
        if any(_as_int(route.get("dst")) == 0 for route in routes_by_src.get(target, [])):
            problem_channel_ids.add(channel_id)

    sorted_channels = sorted(
        channels,
        key=lambda c: (
            _channel_node_id(c) not in problem_channel_ids,
            _as_int(c.get("channel")) if _as_int(c.get("channel")) is not None else 9999,
            str(c.get("name") or ""),
        ),
    )
    visible_channels = sorted_channels[:max_sources]
    visible_channel_ids = {_channel_node_id(channel) for channel in visible_channels}

    for idx in sorted(bus_indices):
        add_node(
            f"track:{idx}",
            label=_track_name(track_by_index, idx),
            column="buses",
            kind="bus",
            track=idx,
        )

    for channel in visible_channels:
        source_id = _channel_node_id(channel)
        target = _as_int(channel.get("target_mixer_track"))
        add_node(
            source_id,
            label=_channel_name(channel),
            column="sources",
            kind=_channel_type_label(channel),
            target_track=target,
        )
        if target is None or target == 0:
            add_link(source_id, "unrouted", "unrouted")
            continue

        if target in bus_indices:
            add_node(
                f"track:{target}",
                label=_track_name(track_by_index, target),
                column="buses",
                kind="bus",
                track=target,
            )
            add_link(source_id, f"track:{target}", "audio")
            continue

        target_routes = routes_by_src.get(target, [])
        if not target_routes:
            add_link(source_id, "dead_end", "dead_end")
            continue

        for route in target_routes:
            dst = _as_int(route.get("dst"))
            if dst is None:
                continue
            if dst == 0:
                add_link(source_id, "master", "direct")
            else:
                add_node(
                    f"track:{dst}",
                    label=_track_name(track_by_index, dst),
                    column="buses",
                    kind="bus",
                    track=dst,
                )
                add_link(source_id, f"track:{dst}", "send" if _route_is_send(route) else "audio")

    for idx in sorted(bus_indices):
        src_id = f"track:{idx}"
        for route in routes_by_src.get(idx, []):
            dst = _as_int(route.get("dst"))
            if dst is None:
                continue
            if dst == 0:
                add_link(src_id, "master", "audio")
            elif f"track:{dst}" in nodes:
                add_link(src_id, f"track:{dst}", "send" if _route_is_send(route) else "audio")

    used_node_ids = {link["from"] for link in links} | {link["to"] for link in links}
    kept_nodes = [
        node for node_id, node in nodes.items() if node_id in used_node_ids or node_id == "master"
    ]
    return {
        "nodes": kept_nodes,
        "links": links,
        "omitted_source_count": max(0, len(channels) - len(visible_channel_ids)),
    }


def _routing_findings(
    *,
    direct_to_master: list[dict[str, Any]],
    unrouted_channels: list[dict[str, Any]],
    dead_end_tracks: list[dict[str, Any]],
    unused_mixer_tracks: list[dict[str, Any]],
    template_context: dict[str, Any],
    unused_probe_failed: bool,
) -> list[dict[str, Any]]:
    findings = []
    if direct_to_master:
        findings.append(
            {
                "id": "generators_direct_to_master",
                "severity": "warning",
                "title": "Generators Direct to Master",
                "detail": "Generator channels route through inserts that feed Master directly.",
                "count": len(direct_to_master),
                "items": direct_to_master[:8],
            }
        )
    if unrouted_channels:
        findings.append(
            {
                "id": "unrouted_channels",
                "severity": "critical",
                "title": "Unrouted Channels",
                "detail": (
                    "Channels without a usable mixer target may be silent or bypass bus processing."
                ),
                "count": len(unrouted_channels),
                "items": unrouted_channels[:8],
            }
        )
    if dead_end_tracks:
        findings.append(
            {
                "id": "dead_end_tracks",
                "severity": "critical",
                "title": "Mixer Paths Without Output",
                "detail": "Targeted mixer inserts have no outgoing route in the routing matrix.",
                "count": len(dead_end_tracks),
                "items": dead_end_tracks[:8],
            }
        )
    if unused_mixer_tracks:
        findings.append(
            {
                "id": "unused_mixer_tracks",
                "severity": "warning",
                "title": "Unused Mixer Inserts",
                "detail": (
                    "Default mixer inserts with no channels, incoming routes, or plugin slots."
                ),
                "count": len(unused_mixer_tracks),
                "items": unused_mixer_tracks[:8],
            }
        )
    if unused_probe_failed:
        findings.append(
            {
                "id": "unused_probe_limited",
                "severity": "info",
                "title": "Unused Insert Probe Limited",
                "detail": "Plugin slot readback failed during unused-insert verification.",
                "count": 1,
            }
        )
    compact_template = templates.compact_context(template_context)
    if compact_template:
        findings.append(
            {
                "id": "template_context",
                "severity": "ok",
                "title": "Template Context Detected",
                "detail": f"{compact_template.get('template_name')} routing profile is recognized.",
                "count": 1,
            }
        )
    if not findings:
        findings.append(
            {
                "id": "routing_clear",
                "severity": "ok",
                "title": "No Routing Blockers Detected",
                "detail": (
                    "The current read-only audit did not find direct blockers in the "
                    "routing matrix."
                ),
                "count": 0,
            }
        )
    return findings


def _routing_health_label(score: int) -> str:
    if score >= 90:
        return "Good"
    if score >= 75:
        return "Needs Review"
    return "At Risk"


def _channel_route_state(
    channel: dict[str, Any],
    routes_by_src: dict[int, list[dict[str, Any]]],
) -> str:
    target = _as_int(channel.get("target_mixer_track"))
    if target is None or target == 0:
        return "unrouted"
    routes = routes_by_src.get(target, [])
    if not routes:
        return "no_output"
    if any(_as_int(route.get("dst")) == 0 for route in routes):
        return "direct_to_master"
    return "bus_routed"


def _channel_summary(channel: dict[str, Any], *, route_state: str) -> dict[str, Any]:
    return {
        "channel": _as_int(channel.get("channel")),
        "name": _channel_name(channel),
        "type": _channel_type_label(channel),
        "target_mixer_track": _as_int(channel.get("target_mixer_track")),
        "target_name": channel.get("target_name"),
        "route_state": route_state,
    }


def _normalise_routes(routes: list[Any]) -> list[dict[str, Any]]:
    out = []
    for route in routes:
        if isinstance(route, dict):
            dst = _as_int(route.get("dst", route.get("target")))
            if dst is None:
                continue
            out.append(
                {
                    "dst": dst,
                    "dst_name": route.get("dst_name") or route.get("target_name"),
                    "level": route.get("level"),
                }
            )
        else:
            dst = _as_int(route)
            if dst is not None:
                out.append({"dst": dst, "dst_name": None, "level": None})
    return out


def _route_is_send(route: dict[str, Any]) -> bool:
    level = route.get("level")
    return isinstance(level, int | float) and level < 0.999


def _channel_node_id(channel: dict[str, Any]) -> str:
    idx = _as_int(channel.get("channel"))
    if idx is not None:
        return f"channel:{idx}"
    return f"channel:{_channel_name(channel)}"


def _channel_name(channel: dict[str, Any]) -> str:
    name = str(channel.get("name") or "").strip()
    idx = _as_int(channel.get("channel"))
    if name:
        return name
    return f"Channel {idx}" if idx is not None else "Channel"


def _channel_type_label(channel: dict[str, Any]) -> str:
    raw = channel.get("type")
    if isinstance(raw, dict):
        return str(raw.get("label") or raw.get("name") or "unknown")
    if raw:
        return str(raw)
    return "unknown"


def _track_name(track_by_index: dict[int, dict[str, Any]], idx: int) -> str:
    row = track_by_index.get(idx, {})
    return _display_track_name(idx, row.get("name"))


def _display_track_name(idx: int, name: Any) -> str:
    text_value = str(name or "").strip()
    if text_value:
        return text_value
    return "Master" if idx == 0 else f"Insert {idx}"


def _looks_like_bus_name(name: Any) -> bool:
    value = str(name or "").lower()
    return any(token in value for token in ("bus", "group", "grp", "aux", "send", "stem"))


def _is_default_mixer_name(idx: int | None, name: Any) -> bool:
    if idx is None:
        return False
    value = str(name or "").strip()
    if idx == 0:
        return value in {"", "Master"}
    return value in {"", f"Insert {idx}"}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def create_server(state: ControlCenterState) -> ThreadingHTTPServer:
    handler = _handler_factory(state)
    return ThreadingHTTPServer((state.host, state.port), handler)


def serve_control_center(
    *,
    host: str = DEFAULT_CONTROL_CENTER_HOST,
    port: int = DEFAULT_CONTROL_CENTER_PORT,
    open_browser: bool = False,
    admin: bool = False,
) -> None:
    if not _is_loopback_host(host):
        raise ValueError("Control Center host must be localhost or a loopback address.")
    selected_port = find_available_tcp_port(host, port)
    sse_port = find_available_tcp_port(DEFAULT_SSE_HOST, DEFAULT_SSE_PORT)
    state = ControlCenterState(
        host=host,
        port=selected_port,
        sse_host=DEFAULT_SSE_HOST,
        sse_port=sse_port,
        admin_enabled=admin,
    )
    server = create_server(state)
    url = f"http://{host}:{selected_port}/"
    if selected_port != port:
        print(f"Control Center port {port} is busy; using {selected_port}.")
    print(f"Serving fls-pilot Control Center at {url}")
    if admin:
        print(f"Admin mode enabled. Admin UI at {url}admin")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped Control Center.")
    finally:
        state.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local FL Studio Pilot Control Center.")
    parser.add_argument("--host", default=DEFAULT_CONTROL_CENTER_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_CONTROL_CENTER_PORT)
    parser.add_argument("--open", action="store_true", help="Open the Control Center in a browser.")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Enable local admin mode (exposes /admin and /api/admin/* routes).",
    )
    args = parser.parse_args(argv)
    if not _is_loopback_host(args.host):
        parser.error("--host must be localhost or a loopback address")
    serve_control_center(host=args.host, port=args.port, open_browser=args.open, admin=args.admin)


def _handler_factory(state: ControlCenterState):
    class ControlCenterHandler(BaseHTTPRequestHandler):
        server_version = "FLSPilotControlCenter/1.0"

        # ------------------------------------------------------------------ #
        # Helpers
        # ------------------------------------------------------------------ #

        def _require_admin(self) -> bool:
            """Return True if admin mode is active; otherwise send 403 and return False."""
            if not state.admin_enabled:
                self._json(
                    {"ok": False, "error": "admin mode disabled"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            return True

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _serve_static(self, name: str, content_type: str) -> None:
            try:
                data = resources.files(STATIC_PACKAGE).joinpath(name).read_bytes()
            except FileNotFoundError:
                self._json({"ok": False, "error": "static asset not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, data: Any, *, status: int | HTTPStatus = HTTPStatus.OK) -> None:
            payload = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _text(self, data: str, *, content_type: str) -> None:
            payload = data.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        # ------------------------------------------------------------------ #
        # Normal routes
        # ------------------------------------------------------------------ #

        def do_GET(self) -> None:  # noqa: N802
            if self.path in {"/", "/index.html"}:
                self._serve_static("index.html", "text/html; charset=utf-8")
            elif self.path == "/app.js":
                self._serve_static("app.js", "application/javascript; charset=utf-8")
            elif self.path == "/styles.css":
                self._serve_static("styles.css", "text/css; charset=utf-8")
            elif self.path.startswith("/assets/") and self.path.endswith(".png"):
                self._serve_static(self.path.lstrip("/"), "image/png")
            elif self.path.startswith("/assets/") and self.path.endswith(".svg"):
                self._serve_static(self.path.lstrip("/"), "image/svg+xml")
            elif self.path == "/api/status":
                self._json(collect_status(state))
            elif self.path == "/api/client-snippets":
                self._json(client_snippets(state))
            elif self.path == "/api/setup/report":
                self._text(setup_report(state), content_type="text/markdown; charset=utf-8")
            # ------------------------------------------------------------------ #
            # Admin GET routes — all guarded by _require_admin()
            # ------------------------------------------------------------------ #
            elif self.path == "/admin" or self.path == "/admin/":
                if not self._require_admin():
                    return
                self._serve_static("admin.html", "text/html; charset=utf-8")
            elif self.path == "/admin.js":
                if not self._require_admin():
                    return
                self._serve_static("admin.js", "application/javascript; charset=utf-8")
            elif self.path == "/api/admin/workflows":
                if not self._require_admin():
                    return
                self._json(_admin_list_workflows(state))
            elif self.path.startswith("/api/admin/workflows/") and not self.path.endswith("/run"):
                workflow_id = self.path[len("/api/admin/workflows/"):]
                if not workflow_id or "/" in workflow_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_get_workflow(state, workflow_id))
            elif self.path == "/api/admin/workflow-runs":
                if not self._require_admin():
                    return
                self._json(_admin_list_workflow_runs(state))
            elif self.path.startswith("/api/admin/workflow-runs/") and not self.path.endswith("/cancel"):
                run_id = self.path[len("/api/admin/workflow-runs/"):]
                if not run_id or "/" in run_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_get_workflow_run(state, run_id))
            elif self.path == "/api/admin/job-kinds":
                if not self._require_admin():
                    return
                self._json(_admin_list_job_kinds(state))
            elif self.path == "/api/admin/jobs":
                if not self._require_admin():
                    return
                self._json(_admin_list_jobs(state))
            else:
                self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            body = self._read_json()
            if self.path == "/api/refresh":
                self._json(collect_status(state, refresh=True))
            elif self.path == "/api/process/daemon/start":
                self._json(_start_daemon(state))
            elif self.path == "/api/process/daemon/stop":
                self._json(_stop_process(state, "daemon"))
            elif self.path == "/api/process/sse/start":
                self._json(_start_sse(state))
            elif self.path == "/api/process/sse/test":
                self._json(_test_sse(state))
            elif self.path == "/api/process/sse/stop":
                self._json(_stop_process(state, "sse"))
            elif self.path == "/api/setup/confirm-step":
                step = str(body.get("step", ""))
                self._json(_confirm_step(state, step))
            elif self.path == "/api/audio-analysis":
                self._json(_run_audio_analysis_action(state, body))
            elif self.path == "/api/workflows/mix-review":
                self._json(_run_mix_review(state))
            elif self.path == "/api/workflows/low-end-analysis":
                self._json(_run_low_end_analysis(state))
            elif self.path == "/api/workflows/project-organizer":
                self._json(_run_project_organizer(state))
            elif self.path == "/api/workflows/routing-audit":
                self._json(_run_routing_audit(state))
            elif self.path == "/api/workflows/preflight":
                self._json(_run_runtime_product_workflow(state, "preflight"))
            elif self.path == "/api/workflows/project-health":
                try:
                    self._json(_runtime_client(state).project_health())
                except Exception as exc:
                    self._json(
                        {
                            "overall_status": "unavailable",
                            "overall_health_score": None,
                            "overall_risk_score": None,
                            "overall_coverage_pct": 0,
                            "overall_confidence_score": 0,
                            "sections": [],
                            "missing_workflows": [
                                "project_organizer",
                                "mix_review",
                                "routing_audit",
                                "low_end_analysis",
                            ],
                            "mixed_project_fingerprints": False,
                            "next_suggested_workflows": [],
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            # ------------------------------------------------------------------ #
            # Admin POST routes — all guarded by _require_admin()
            # ------------------------------------------------------------------ #
            elif self.path == "/api/admin/workflows":
                if not self._require_admin():
                    return
                self._json(_admin_create_workflow(state, body))
            elif self.path.endswith("/run") and self.path.startswith("/api/admin/workflows/"):
                workflow_id = self.path[len("/api/admin/workflows/"):-len("/run")]
                if not workflow_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_run_workflow(state, workflow_id, body))
            elif self.path.endswith("/cancel") and self.path.startswith("/api/admin/workflow-runs/"):
                run_id = self.path[len("/api/admin/workflow-runs/"):-len("/cancel")]
                if not run_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_cancel_workflow_run(state, run_id))
            elif self.path.endswith("/cancel") and self.path.startswith("/api/admin/jobs/"):
                job_id = self.path[len("/api/admin/jobs/"):-len("/cancel")]
                if not job_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_cancel_job(state, job_id))
            else:
                self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:  # noqa: N802
            body = self._read_json()
            if self.path.startswith("/api/admin/workflows/"):
                workflow_id = self.path[len("/api/admin/workflows/"):]
                if not workflow_id or "/" in workflow_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                self._json(_admin_update_workflow(state, workflow_id, body))
            else:
                self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def do_DELETE(self) -> None:  # noqa: N802
            if self.path.startswith("/api/admin/workflows/"):
                workflow_id = self.path[len("/api/admin/workflows/"):]
                if not workflow_id or "/" in workflow_id:
                    self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
                if not self._require_admin():
                    return
                # Archive only — never hard delete
                self._json(_admin_archive_workflow(state, workflow_id))
            else:
                self._json({"ok": False, "error": "not found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return ControlCenterHandler


# ---------------------------------------------------------------------------
# Admin route proxy helpers (PR 5)
# ---------------------------------------------------------------------------


def _admin_list_workflows(state: ControlCenterState) -> dict[str, Any]:
    try:
        workflows = _runtime_client(state).workflow_admin_list(include_archived=False)
        return {"ok": True, "workflows": workflows}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_get_workflow(state: ControlCenterState, workflow_id: str) -> dict[str, Any]:
    try:
        workflow = _runtime_client(state).workflow_admin_get(workflow_id)
        return {"ok": True, "workflow": workflow}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_create_workflow(state: ControlCenterState, body: dict[str, Any]) -> dict[str, Any]:
    try:
        definition = body.get("definition") or {}
        if not isinstance(definition, dict):
            return {"ok": False, "error": "definition must be an object"}
        workflow = _runtime_client(state).workflow_admin_create(definition)
        return {"ok": True, "workflow": workflow}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_update_workflow(
    state: ControlCenterState, workflow_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    try:
        patch = body.get("patch") or {}
        if not isinstance(patch, dict):
            return {"ok": False, "error": "patch must be an object"}
        workflow = _runtime_client(state).workflow_admin_update(workflow_id, patch)
        return {"ok": True, "workflow": workflow}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_archive_workflow(state: ControlCenterState, workflow_id: str) -> dict[str, Any]:
    """Archive a workflow — never hard-deletes."""
    try:
        workflow = _runtime_client(state).workflow_admin_archive(workflow_id)
        return {"ok": True, "workflow": workflow}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_run_workflow(
    state: ControlCenterState, workflow_id: str, body: dict[str, Any]
) -> dict[str, Any]:
    """Submit a workflow run via workflow.run.submit."""
    try:
        inputs = body.get("inputs") or {}
        idempotency_key = body.get("idempotency_key") or None
        input_summary = body.get("input_summary") or {}
        if not isinstance(inputs, dict):
            return {"ok": False, "error": "inputs must be an object"}
        result = _runtime_client(state).workflow_run_submit(
            workflow_id,
            inputs=inputs,
            idempotency_key=idempotency_key,
            input_summary=input_summary,
        )
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_list_workflow_runs(state: ControlCenterState) -> dict[str, Any]:
    try:
        runs = _runtime_client(state).workflow_run_list(include_finished=True)
        return {"ok": True, "workflow_runs": runs}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_get_workflow_run(state: ControlCenterState, run_id: str) -> dict[str, Any]:
    try:
        result = _runtime_client(state).workflow_run_status(run_id)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_cancel_workflow_run(state: ControlCenterState, run_id: str) -> dict[str, Any]:
    """Cancel a workflow run via workflow.run.cancel."""
    try:
        result = _runtime_client(state).workflow_run_cancel(run_id)
        return {"ok": True, **result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_list_job_kinds(state: ControlCenterState) -> dict[str, Any]:
    """List registered job kinds via job.kind.list."""
    try:
        kinds = _runtime_client(state).job_kind_list()
        return {"ok": True, "kinds": kinds}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_list_jobs(state: ControlCenterState) -> dict[str, Any]:
    try:
        jobs = _runtime_client(state).list_jobs()
        return {"ok": True, "jobs": jobs}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _admin_cancel_job(state: ControlCenterState, job_id: str) -> dict[str, Any]:
    try:
        job = _runtime_client(state).cancel_job(job_id)
        return {"ok": True, "job": job}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _start_daemon(state: ControlCenterState) -> dict[str, Any]:
    with state.lock:
        existing = state.processes.get("daemon")
        if existing and existing.running:
            return {"ok": True, "process": existing.to_dict(), "message": "daemon already running"}

        health = _daemon_health(state.daemon_host, state.daemon_port)
        if health.get("reachable"):
            state.daemon_fallback_port = None
            return {
                "ok": True,
                "external": True,
                "state": "external",
                "message": (
                    "A fls-pilot daemon is already reachable at "
                    f"{state.daemon_host}:{state.daemon_port}."
                ),
            }
        port_status = tcp_port_status(state.daemon_host, state.daemon_port)
        if not port_status["available"]:
            fallback = int(port_status["fallback_port"])
            state.daemon_fallback_port = fallback
            return {
                "ok": False,
                "state": "port_conflict",
                "message": (
                    f"Port {state.daemon_host}:{state.daemon_port} is occupied by "
                    "a non-daemon process. "
                    f"Start the daemon with FLS_PILOT_TCP_PORT={fallback}."
                ),
                "fallback_port": fallback,
            }

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["FLS_PILOT_TCP_HOST"] = state.daemon_host
        env["FLS_PILOT_TCP_PORT"] = str(state.daemon_port)
        proc = _spawn("daemon", [sys.executable, "-m", "fls_pilot.daemon"], env)
        state.processes["daemon"] = proc
        state.daemon_fallback_port = None
        return {"ok": True, "process": proc.to_dict()}


def _start_sse(state: ControlCenterState) -> dict[str, Any]:
    with state.lock:
        existing = state.processes.get("sse")
        if existing and existing.running:
            probe = _probe_sse_connection(state)
            return {
                "ok": True,
                "process": existing.to_dict(),
                "message": "SSE server already running",
                "probe": probe,
            }

        selected = find_available_tcp_port(state.sse_host, DEFAULT_SSE_PORT)
        state.sse_port = selected
        state.sse_probe = _sse_probe_state(
            "checking",
            "SSE server started. Testing the MCP connection...",
            state.sse_host,
            selected,
        )
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["FLS_PILOT_TRANSPORT"] = "tcp"
        daemon_host, daemon_port = _selected_daemon_endpoint(state)
        env["FLS_PILOT_TCP_HOST"] = daemon_host
        env["FLS_PILOT_TCP_PORT"] = str(daemon_port)
        env["FLS_PILOT_SERVER_TRANSPORT"] = "sse"
        env["FLS_PILOT_SSE_HOST"] = state.sse_host
        env["FLS_PILOT_SSE_PORT"] = str(selected)
        proc = _spawn(
            "sse",
            [sys.executable, "-m", "fls_pilot.server", "--sse", "--port", str(selected)],
            env,
        )
        state.processes["sse"] = proc
        probe = _probe_sse_connection(state)
        return {
            "ok": True,
            "process": proc.to_dict(),
            "url": _sse_url(state.sse_host, selected),
            "probe": probe,
        }


def _test_sse(state: ControlCenterState) -> dict[str, Any]:
    with state.lock:
        proc = state.processes.get("sse")
        if proc is None or not proc.running:
            state.sse_probe = _sse_probe_state(
                "not_required",
                "SSE server is stopped. Start it only if your MCP client uses SSE/HTTP.",
                state.sse_host,
                state.sse_port,
            )
            return {
                "ok": False,
                "state": "stopped",
                "message": "SSE server is not running.",
                "probe": dict(state.sse_probe),
            }
        probe = _probe_sse_connection(state)
        return {"ok": probe.get("state") == "ok", "probe": probe}


def _stop_process(state: ControlCenterState, name: str) -> dict[str, Any]:
    with state.lock:
        proc = state.processes.get(name)
        if proc is None:
            if name == "sse":
                state.sse_probe = _sse_probe_state(
                    "not_required",
                    "SSE server is stopped. Start it only if your MCP client uses SSE/HTTP.",
                    state.sse_host,
                    state.sse_port,
                )
            return {"ok": True, "state": "stopped", "message": f"{name} is not managed here"}
        _stop_managed_process(proc)
        if name == "sse":
            state.sse_probe = _sse_probe_state(
                "not_required",
                "SSE server stopped. SSE is only needed for MCP clients that use SSE/HTTP.",
                state.sse_host,
                state.sse_port,
            )
        return {"ok": True, "process": proc.to_dict()}


def _confirm_step(state: ControlCenterState, step: str) -> dict[str, Any]:
    if step not in MANUAL_CHECKPOINTS:
        return {"ok": False, "error": f"unknown setup checkpoint: {step}"}
    with state.lock:
        state.checkpoints[step] = {"status": "user_confirmed", "updated_at": _now_iso()}
    return collect_status(state, refresh=True)


def _spawn(name: str, args: list[str], env: dict[str, str]) -> ManagedProcess:
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=os.getcwd(),
    )
    managed = ManagedProcess(name=name, args=args, env=env, process=proc, started_at=_now_iso())
    for stream_name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        if stream is None:
            continue
        thread = threading.Thread(
            target=_read_stream,
            args=(managed, stream_name, stream),
            daemon=True,
        )
        thread.start()
        managed.reader_threads.append(thread)
    return managed


def _read_stream(managed: ManagedProcess, stream_name: str, stream: Any) -> None:
    for line in iter(stream.readline, ""):
        managed.logs.append(f"{stream_name}: {line.rstrip()}")


def _stop_managed_process(proc: ManagedProcess) -> None:
    if proc.running:
        proc.process.terminate()
        try:
            proc.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.process.kill()
            proc.process.wait(timeout=5)


def _process_status(state: ControlCenterState) -> dict[str, Any]:
    managed = {name: proc.to_dict() for name, proc in state.processes.items()}
    for name in ("daemon", "sse"):
        if name not in managed:
            managed[name] = {"state": "stopped", "logs": []}
    managed["sse"]["probe"] = dict(state.sse_probe)
    daemon_host, daemon_port = _selected_daemon_endpoint(state)
    daemon_health = _daemon_health(daemon_host, daemon_port)
    daemon_proc = state.processes.get("daemon")
    if daemon_health.get("reachable") and not (daemon_proc and daemon_proc.running):
        managed["daemon"] = {"state": "external", "health": daemon_health, "logs": []}
    else:
        managed["daemon"]["health"] = daemon_health
    return managed


def _port_state(
    state: ControlCenterState,
    *,
    bind_check=None,
    status_provider=None,
) -> dict[str, dict[str, Any]]:
    bind_check = bind_check or can_bind_tcp
    status_provider = status_provider or tcp_port_status
    _, daemon_selected = _selected_daemon_endpoint(state)
    return {
        "control_center": {
            "host": state.host,
            "preferred_port": DEFAULT_CONTROL_CENTER_PORT,
            "selected_port": state.port,
            "fallback_port": None if state.port == DEFAULT_CONTROL_CENTER_PORT else state.port,
        },
        "sse": {
            "host": state.sse_host,
            "preferred_port": DEFAULT_SSE_PORT,
            "available": bind_check(state.sse_host, DEFAULT_SSE_PORT),
            "selected_port": state.sse_port,
            "fallback_port": None if state.sse_port == DEFAULT_SSE_PORT else state.sse_port,
        },
        "daemon": {
            "host": state.daemon_host,
            "preferred_port": state.daemon_port,
            "available": bind_check(state.daemon_host, state.daemon_port),
            "selected_port": daemon_selected,
            "fallback_port": state.daemon_fallback_port,
        },
        "status": status_provider(DEFAULT_CONTROL_CENTER_HOST, 8765),
    }


def _group_findings(findings: list[doctor.Finding]) -> dict[str, list[dict[str, Any]]]:
    groups = {
        "environment": [],
        "fl_app": [],
        "midi": [],
        "controller": [],
        "daemon": [],
        "mcp_stdio": [],
        "mcp_sse": [],
        "mcp_apply": [],
        "optional_dependencies": [],
        "other": [],
    }
    for finding in findings:
        key = _finding_group(finding.component)
        groups[key].append(finding.to_dict())
    return groups


def _finding_group(component: str) -> str:
    lowered = component.lower()
    if "python" in lowered or "core dependencies" in lowered:
        return "environment"
    if "optional" in lowered:
        return "optional_dependencies"
    if "fl studio application" in lowered:
        return "fl_app"
    if "midi" in lowered or "loopmidi" in lowered or "iac" in lowered:
        return "midi"
    if "daemon" in lowered or "bridge" in lowered:
        return "daemon"
    if "controller" in lowered or "heartbeat" in lowered or "ping" in lowered:
        return "controller"
    if "stdio" in lowered:
        return "mcp_stdio"
    if "sse" in lowered or "http" in lowered:
        return "mcp_sse"
    if "mcp_apply" in lowered or "piano roll" in lowered:
        return "mcp_apply"
    return "other"


def _readiness(
    findings: list[doctor.Finding],
    checkpoints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    blockers = [f for f in findings if f.severity == "blocker" and f.status != "ok"]
    manual = [f for f in findings if f.status in {"manual_check", "probe_needed"}]
    if blockers:
        state = "blocked"
    elif manual and not checkpoints:
        state = "needs_manual_action"
    else:
        state = "ready_for_review"
    write_ready = state == "ready_for_review" and "ran_mcp_apply" in checkpoints
    if write_ready:
        state = "ready_for_write_tools"
    return {
        "state": state,
        "blocker_count": len(blockers),
        "manual_count": len(manual),
        "read_only_review_ready": not blockers,
        "write_tools_ready": write_ready,
    }


def _setup_guidance(
    *,
    groups: dict[str, list[dict[str, Any]]],
    readiness: dict[str, Any],
    processes: dict[str, Any],
    ports: dict[str, dict[str, Any]],
    daemon_autostart: dict[str, Any],
    sse_probe: dict[str, Any],
) -> list[dict[str, Any]]:
    guidance: list[dict[str, Any]] = []

    if _group_needs_action(groups, "environment"):
        guidance.append(
            _guidance_item(
                title="Fix the Python environment",
                status="blocked",
                text=_group_guidance_text(
                    groups,
                    "environment",
                    "Run the installer again or install the missing package, then re-check setup.",
                ),
                groups=["environment"],
                action_label="Re-check",
                action_path="/api/refresh",
            )
        )
        return guidance

    daemon_process = processes.get("daemon", {})
    daemon_running = _process_running(daemon_process)
    daemon_start_action_shown = False
    autostart_state = str(daemon_autostart.get("state") or "")
    if autostart_state in {"started", "starting", "external", "failed"}:
        daemon_status = _daemon_startup_status(
            autostart_state,
            daemon_process=daemon_process,
            groups=groups,
        )
        daemon_action_path = "/api/refresh"
        daemon_action_label = "Re-check"
        if daemon_status == "action needed" and not daemon_running:
            daemon_action_path = "/api/process/daemon/start"
            daemon_action_label = "Start daemon"
            daemon_start_action_shown = True
        guidance.append(
            _guidance_item(
                title="Daemon startup",
                status=daemon_status,
                text=_daemon_startup_text(
                    daemon_autostart=daemon_autostart,
                    daemon_process=daemon_process,
                    groups=groups,
                ),
                groups=["daemon"],
                action_label=daemon_action_label,
                action_path=daemon_action_path,
            )
        )

    if (
        _group_needs_action(groups, "daemon")
        and not daemon_running
        and not daemon_start_action_shown
    ):
        guidance.append(
            _guidance_item(
                title="Start the local daemon",
                status="action needed",
                text=(
                    "The daemon owns the MIDI bridge. Start it before checking FL Studio. "
                    f"Target port: {ports.get('daemon', {}).get('host', '127.0.0.1')}:"
                    f"{ports.get('daemon', {}).get('selected_port', 'unknown')}."
                ),
                groups=["daemon"],
                action_label="Start daemon",
                action_path="/api/process/daemon/start",
            )
        )

    if _group_needs_action(groups, "midi"):
        guidance.append(
            _guidance_item(
                title="Create MIDI loopback ports",
                status=_group_status(groups, "midi"),
                text=_group_guidance_text(
                    groups,
                    "midi",
                    "Create FLStudioPilot RX and FLStudioPilot TX, then re-check setup.",
                ),
                groups=["midi"],
                checkpoint="created_midi_ports",
                action_label="I did this",
            )
        )

    if _group_needs_action(groups, "fl_app"):
        guidance.append(
            _guidance_item(
                title="Open FL Studio",
                status=_group_status(groups, "fl_app"),
                text=(
                    "Open FL Studio, load or create a project, wait until it is "
                    "responsive, then re-check setup."
                ),
                groups=["fl_app"],
                action_label="Re-check",
                action_path="/api/refresh",
            )
        )

    if _group_needs_action(groups, "controller"):
        guidance.append(
            _guidance_item(
                title="Connect FL Studio to the controller",
                status=_group_status(groups, "controller"),
                text=_group_guidance_text(
                    groups,
                    "controller",
                    (
                        "Open FL Studio, enable FLStudioPilot RX as the controller input, "
                        "set FLStudioPilot TX to the same port number, then re-check."
                    ),
                ),
                groups=["controller"],
                checkpoint="configured_fl_midi",
                action_label="I did this",
            )
        )

    if _group_needs_action(groups, "mcp_sse"):
        guidance.append(
            _guidance_item(
                title="Check MCP SSE",
                status=_group_status(groups, "mcp_sse"),
                text=_group_guidance_text(
                    groups,
                    "mcp_sse",
                    "Start the SSE server only if your MCP client uses SSE, then re-check.",
                ),
                groups=["mcp_sse"],
                action_label="Start SSE server",
                action_path="/api/process/sse/start",
            )
        )

    sse_probe_state = str(sse_probe.get("state") or "")
    if sse_probe_state in {"ok", "failed", "checking"}:
        guidance.append(
            _guidance_item(
                title="MCP SSE connection",
                status=(
                    "OK"
                    if sse_probe_state == "ok"
                    else ("checking" if sse_probe_state == "checking" else "action needed")
                ),
                text=str(sse_probe.get("message") or "SSE connection test has no detail."),
                groups=["mcp_sse"],
                action_label="Re-test SSE",
                action_path="/api/process/sse/test",
            )
        )

    if _group_needs_action(groups, "mcp_apply"):
        guidance.append(
            _guidance_item(
                title="Arm Piano Roll note writing",
                status=_group_status(groups, "mcp_apply"),
                text=_group_guidance_text(
                    groups,
                    "mcp_apply",
                    "Run MCP_Apply once from the Piano Roll script menu if you need note writing.",
                ),
                groups=["mcp_apply"],
                checkpoint="ran_mcp_apply",
                action_label="I did this",
            )
        )

    if not guidance:
        guidance.append(
            _guidance_item(
                title="Setup is ready",
                status="OK",
                text=(
                    "Read-only workflows are ready."
                    if readiness.get("read_only_review_ready")
                    else "No next setup action is available from the current checks."
                ),
                groups=[],
                action_label="Re-check",
                action_path="/api/refresh",
            )
        )

    return guidance


def _daemon_startup_status(
    autostart_state: str,
    *,
    daemon_process: dict[str, Any],
    groups: dict[str, list[dict[str, Any]]],
) -> str:
    if autostart_state == "starting":
        return "starting"
    if autostart_state == "failed":
        return "action needed"
    if not _process_running(daemon_process):
        return "action needed"
    if _group_needs_action(groups, "daemon"):
        return _group_status(groups, "daemon")
    return "OK"


def _daemon_startup_text(
    *,
    daemon_autostart: dict[str, Any],
    daemon_process: dict[str, Any],
    groups: dict[str, list[dict[str, Any]]],
) -> str:
    if not _process_running(daemon_process):
        return "Daemon is not running. Start the daemon, then re-check setup."
    if _group_needs_action(groups, "daemon"):
        return _group_guidance_text(
            groups,
            "daemon",
            "Daemon is running, but the bridge health check still needs attention.",
        )
    return str(daemon_autostart.get("message") or "Daemon is running.")


def _process_running(process: dict[str, Any]) -> bool:
    return bool(process.get("running")) or process.get("state") in {"running", "external"}


def _guidance_item(
    *,
    title: str,
    status: str,
    text: str,
    groups: list[str],
    action_label: str | None = None,
    action_path: str | None = None,
    checkpoint: str | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "status": status,
        "text": text,
        "groups": groups,
        "action_label": action_label,
        "action_path": action_path,
        "checkpoint": checkpoint,
    }


def _group_status(groups: dict[str, list[dict[str, Any]]], group: str) -> str:
    findings = groups.get(group, [])
    failed = next((item for item in findings if item.get("status") == "failed"), None)
    if failed:
        return "blocked" if failed.get("severity") == "blocker" else "action needed"
    manual = next(
        (item for item in findings if item.get("status") in {"manual_check", "probe_needed"}),
        None,
    )
    if manual:
        return "manual check"
    return "OK" if findings else "not required"


def _group_needs_action(groups: dict[str, list[dict[str, Any]]], group: str) -> bool:
    return _group_status(groups, group).lower() not in {"ok", "not required"}


def _group_guidance_text(
    groups: dict[str, list[dict[str, Any]]],
    group: str,
    fallback: str,
) -> str:
    findings = [
        item
        for item in groups.get(group, [])
        if item.get("status") in {"failed", "manual_check", "probe_needed"}
    ]
    if not findings:
        return fallback
    first = findings[0]
    evidence = str(first.get("evidence") or fallback)
    remediation = str(first.get("remediation") or "")
    return f"{evidence} {remediation}".strip()


def _daemon_health(host: str, port: int) -> dict[str, Any]:
    try:
        with socket.create_connection((host, int(port)), timeout=0.3) as sock:
            sock.sendall(b'{"op":"health"}\n')
            sock.settimeout(0.5)
            raw = sock.recv(4096)
    except OSError:
        return {"reachable": False}
    try:
        data = json.loads(raw.decode("utf-8").strip())
    except json.JSONDecodeError:
        return {"reachable": False, "invalid_response": True}
    data["reachable"] = True
    return data


def _resolve_daemon_endpoint() -> tuple[str, int]:
    host = os.environ.get("FLS_PILOT_TCP_HOST", DEFAULT_TCP_HOST)
    raw_port = os.environ.get("FLS_PILOT_TCP_PORT", str(DEFAULT_TCP_PORT))
    try:
        port = int(raw_port)
        if port <= 0 or port > 65535:
            raise ValueError
    except ValueError:
        port = DEFAULT_TCP_PORT
    return host, port


def _selected_daemon_endpoint(state: ControlCenterState) -> tuple[str, int]:
    return state.daemon_host, state.daemon_fallback_port or state.daemon_port


def _runtime_client(state: ControlCenterState) -> RuntimeClient:
    host, port = _selected_daemon_endpoint(state)
    client = state.runtime_client
    if client.host != host or client.port != port:
        client = RuntimeClient(host, port)
        state.runtime_client = client
    return client


def _console_script_path(script: str) -> str:
    scripts_dir = Path(sys.executable).parent
    suffix = ".exe" if os.name == "nt" else ""
    candidate = scripts_dir / f"{script}{suffix}"
    return str(candidate) if candidate.exists() else script


def _daemon_terminal_command(host: str, port: int) -> str:
    command = _console_script_path("fls-pilot-daemon")
    if host == DEFAULT_TCP_HOST and port == DEFAULT_TCP_PORT:
        return command
    return _prefixed_command(
        {
            "FLS_PILOT_TCP_HOST": host,
            "FLS_PILOT_TCP_PORT": str(port),
        },
        command,
    )


def _sse_terminal_command(state: ControlCenterState, command: str) -> str:
    daemon_host, daemon_port = _selected_daemon_endpoint(state)
    return _prefixed_command(
        {
            "FLS_PILOT_TRANSPORT": "tcp",
            "FLS_PILOT_TCP_HOST": daemon_host,
            "FLS_PILOT_TCP_PORT": str(daemon_port),
            "FLS_PILOT_SSE_PORT": str(state.sse_port),
        },
        f"{command} --sse --port {state.sse_port}",
    )


def _prefixed_command(env: dict[str, str], command: str) -> str:
    if os.name == "nt":
        prefix = " && ".join(f'set "{key}={value}"' for key, value in env.items())
        return f"{prefix} && {command}"
    prefix = " ".join(f"{key}={value}" for key, value in env.items())
    return f"{prefix} {command}"


def _process_state_text(proc: dict[str, Any]) -> str:
    if "state" in proc:
        return str(proc["state"])
    if proc.get("running"):
        return "running"
    if proc.get("returncode") is not None:
        return f"exited ({proc['returncode']})"
    return "stopped"


def _redact_args(args: list[str]) -> list[str]:
    return [_redact_path(arg) for arg in args]


def _redact_path(value: Any) -> str:
    text = str(value)
    home = str(Path.home())
    if home and home in text:
        return text.replace(home, "~")
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


if __name__ == "__main__":
    main()
