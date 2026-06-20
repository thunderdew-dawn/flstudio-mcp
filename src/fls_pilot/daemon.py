"""Standalone MIDI bridge daemon (v0.3 split transport).

Why this exists
---------------
The MCP server is launched by the MCP *client* (Cursor, Claude Desktop,
Cursor, ...). Some clients -- notably the Microsoft Store / MSIX build of
stdio clients -- launch their child MCP-server process in an environment
where the Windows MIDI subsystem does not deliver input data: the loopMIDI
ports still enumerate and open without error, but no MIDI ever arrives. A
process started normally (a terminal, a login-startup task) has full MIDI
access.

To make the bridge work under *every* client, all MIDI I/O lives in this
daemon, which the user runs as an ordinary process. The MCP server then talks
to the daemon over a localhost TCP socket -- and TCP is unaffected by the
client's launch context (this is also why socket-based MCPs like AbletonMCP
"just work" everywhere).

    MCP client --stdio--> MCP server --TCP(localhost)--> daemon --MIDI--> FL

Run it::

    fls-pilot-daemon            # or: python -m fls_pilot.daemon

Then point the MCP server at it by setting ``FLS_PILOT_TRANSPORT=tcp`` in
the client's MCP config env.

Wire protocol (newline-delimited JSON, one object per line):

    -> {"op": "health"}
    <- {"alive": bool, "heartbeat_age": float|null}

    -> {"op": "call", "cmd": str, "params": {...}|null, "timeout": float}
    <- {"ok": true, "data": ...}
       {"ok": false, "exc": "FLTimeout"|"FLNotRunning"|..., "error": str, "code": str}
"""

from __future__ import annotations

import json
import logging
import os
import socketserver
import threading

from . import __version__, protocol
from .analysis.broker import StaticProjectSnapshot, StaticSnapshotPolicy
from .analysis.contracts import IncompatibleReportVersionError
from .analysis.live import LiveMeterPolicy
from .analysis.schema import AnalysisReport
from .connection import (
    DEFAULT_TCP_HOST,
    DEFAULT_TCP_PORT,
    FLBridge,
    FLBridgeError,
    FLCommandFailed,
    FLNotRunning,
    FLPortMissing,
    FLTimeout,
)
from .runtime.artifacts import AudioArtifactStore
from .runtime.audio_worker import AudioAnalysisWorker
from .runtime.contracts import RuntimeResponse
from .runtime.core import RuntimeCore
from .runtime.protocol import validate_runtime_request
from .runtime.workflow_runner import run_workflow
from .runtime_config import find_available_tcp_port
from .workflows.registry import canonical_workflow_id

logger = logging.getLogger("fls_pilot.daemon")


_bridge: FLBridge | None = None
_bridge_lock = threading.Lock()
_runtime: RuntimeCore | None = None
_runtime_lock = threading.Lock()
_audio_artifact_store: AudioArtifactStore | None = None


def _get_runtime() -> RuntimeCore:
    """Return (and lazily create) the singleton RuntimeCore."""
    global _runtime, _audio_artifact_store
    with _runtime_lock:
        if _runtime is None:
            _audio_artifact_store = AudioArtifactStore()
            _runtime = RuntimeCore(
                artifact_store=_audio_artifact_store,
                job_result_validator=_audio_artifact_store.validate_result_ref,
            )
            AudioAnalysisWorker(_audio_artifact_store).register(_runtime)
        return _runtime


def _get_bridge() -> FLBridge:
    """Return the singleton FLBridge, opening it lazily.

    Re-tried on every request until the loopMIDI ports exist, so the daemon
    can be started before FL / loopMIDI are ready.
    """
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            b = FLBridge()
            b.open()  # raises FLPortMissing if loopMIDI ports are absent
            _bridge = b
        return _bridge


def _handle_request(req: dict) -> dict:
    op = req.get("op")

    if op == "runtime":
        return _handle_runtime_request(req)

    if op == "health":
        try:
            bridge = _get_bridge()
        except FLPortMissing as e:
            return {"alive": False, "heartbeat_age": None, "error": str(e)}
        return {"alive": bridge.is_alive(), "heartbeat_age": bridge.heartbeat_age()}

    if op == "call":
        command = req.get("cmd")
        params = req.get("params")
        timeout = req.get("timeout")
        try:
            data = _get_bridge().call(command, params, timeout=timeout)
            return {"ok": True, "data": data}
        except FLCommandFailed as e:
            return {
                "ok": False,
                "exc": "FLCommandFailed",
                "error": str(e),
                "code": getattr(e, "code", "error"),
            }
        except FLNotRunning as e:
            return {"ok": False, "exc": "FLNotRunning", "error": str(e)}
        except FLTimeout as e:
            return {"ok": False, "exc": "FLTimeout", "error": str(e)}
        except FLPortMissing as e:
            return {"ok": False, "exc": "FLPortMissing", "error": str(e)}
        except FLBridgeError as e:
            return {"ok": False, "exc": "FLBridgeError", "error": str(e)}
        except Exception as e:  # pragma: no cover - defensive
            return {"ok": False, "exc": "Error", "error": f"{type(e).__name__}: {e}"}

    if op == "apply_notes":
        # Daemon-side note authoring: generate the .pyscript with notes baked
        # in, write it, force-focus FL, fire Ctrl+Alt+Y. Runs here (normal
        # process) so it works even when the MCP server is MSIX-sandboxed.
        try:
            trigger = req.get("trigger", True)
            ensured = None
            if trigger:  # auto-open the piano roll first
                try:
                    ensure_params = {}
                    if req.get("channel") is not None:
                        ensure_params["channel"] = int(req["channel"])
                    if req.get("pattern") is not None:
                        ensure_params["pattern"] = int(req["pattern"])
                    ensured = _get_bridge().call(
                        protocol.CMD_ENSURE_PIANO_ROLL,
                        ensure_params,
                        timeout=5.0,
                    )
                except Exception as e:
                    ensured = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            from .pianoroll import apply_notes

            res = apply_notes(
                req.get("notes") or [],
                req.get("mode", "replace"),
                trigger=trigger,
                quantize=req.get("quantize"),
                snap_ends=req.get("snap_ends", False),
                transpose=req.get("transpose"),
                duplicate_bars=req.get("duplicate_bars"),
                velocity_ramp=req.get("velocity_ramp"),
                marker_add=req.get("marker_add"),
                marker_clear=req.get("marker_clear", False),
            )
            if isinstance(res, dict):
                res["piano_roll_ensured"] = ensured
            return res
        except Exception as e:
            return {"ok": False, "exc": "Error", "error": f"{type(e).__name__}: {e}"}

    return {"ok": False, "exc": "Error", "error": f"unknown op: {op!r}"}


def _handle_runtime_request(req: dict) -> dict:
    try:
        operation, params = validate_runtime_request(req)
        data = _dispatch_runtime_operation(operation, params)
        return RuntimeResponse(ok=True, operation=operation, data=data).to_dict()
    except IncompatibleReportVersionError as exc:
        return RuntimeResponse(
            ok=False,
            operation=str(req.get("operation") or ""),
            error=str(exc),
            code=exc.code,
        ).to_dict()
    except (KeyError, TypeError, ValueError) as exc:
        return RuntimeResponse(
            ok=False,
            operation=str(req.get("operation") or ""),
            error=str(exc),
            code="invalid_request",
        ).to_dict()
    except Exception as exc:  # pragma: no cover - defensive transport boundary
        logger.exception("Runtime operation failed")
        return RuntimeResponse(
            ok=False,
            operation=str(req.get("operation") or ""),
            error=f"{type(exc).__name__}: {exc}",
            code="runtime_error",
        ).to_dict()


def _dispatch_runtime_operation(
    operation: str,
    params: dict,
) -> dict:
    if operation == "runtime.status":
        return {
            "session": _get_runtime().session.to_dict(),
            "project_context": _get_runtime().project_context.to_dict(),
            "capabilities": _runtime_capabilities(),
        }
    if operation == "runtime.session":
        return {"session": _get_runtime().session.to_dict()}
    if operation == "runtime.capabilities":
        return {"capabilities": _runtime_capabilities()}
    if operation == "runtime.invalidate":
        workflows = tuple(str(row) for row in params.get("workflows") or ())
        return {
            "invalidation": _get_runtime().invalidate(
                str(params.get("event") or "project_state_change"),
                workflows=workflows,
            )
        }
    if operation == "project.current":
        return {"project_context": _get_runtime().project_context.to_dict()}
    if operation in {"project.snapshot.get", "project.snapshot.refresh"}:
        snapshot = _get_runtime().get_static_project_snapshot(
            _get_bridge(),
            StaticSnapshotPolicy(
                force_refresh=operation.endswith("refresh"),
                include_patterns=bool(params.get("include_patterns", True)),
                include_playlist=bool(params.get("include_playlist", True)),
            ),
        )
        return {
            "snapshot": snapshot.to_dict(),
            "project_context": _get_runtime().project_context.to_dict(),
        }
    if operation == "workflow.catalog":
        rows = _get_runtime().workflow_registry.list(
            include_inactive=bool(params.get("include_inactive", True))
        )
        return {"workflows": [row.to_dict() for row in rows]}
    if operation == "workflow.declaration.get":
        workflow_id = canonical_workflow_id(str(params["workflow_id"]))
        return {"workflow": _get_runtime().workflow_registry.get(workflow_id).to_dict()}
    if operation == "analysis.workflow.run":
        workflow_id = canonical_workflow_id(str(params["workflow_id"]))
        declaration = _get_runtime().workflow_registry.get(workflow_id)
        if not declaration.enabled:
            raise ValueError(f"workflow is not active: {workflow_id}")
        inputs = params.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise ValueError("workflow inputs must be an object")
        return {
            "result": run_workflow(
                _get_runtime(),
                workflow_id,
                bridge=(
                    None
                    if workflow_id in {"preset_assistant", "audio_evidence"}
                    else _get_bridge()
                ),
                inputs=inputs,
            )
        }
    if operation == "analysis.live_meter.normalize":
        policy_data = dict(params.get("policy") or {})
        snapshot = StaticProjectSnapshot.from_dict(
            dict(params.get("static_snapshot") or {})
        )
        provider = _PayloadWatcherProvider(
            status=dict(params.get("watch_status") or {}),
            last_max=dict(params.get("watch_last_max") or {}),
        )
        window = _get_runtime().analysis_broker.get_live_meter_window(
            _get_bridge(),
            policy=LiveMeterPolicy(
                ttl_seconds=float(policy_data.get("ttl_seconds") or 2.0),
                require_playing=bool(policy_data.get("require_playing", False)),
                min_capture_seconds=float(
                    policy_data.get("min_capture_seconds") or 1.0
                ),
                recent_watch_seconds=float(
                    policy_data.get("recent_watch_seconds") or 120.0
                ),
            ),
            watcher_provider=provider,
            static_snapshot=snapshot,
        )
        return {"live_meter_window": window.to_dict()}
    if operation == "analysis.report.add":
        report = AnalysisReport.from_dict(dict(params["report"]))
        stored = _get_runtime().add_report(report)
        return {"report": stored.to_dict()}
    if operation == "analysis.report.latest":
        workflow_id = canonical_workflow_id(str(params["workflow_id"]))
        report = _get_runtime().latest_report(workflow_id)
        return {"report": report.to_dict() if report else None}
    if operation == "analysis.report.list":
        workflow = params.get("workflow_id")
        workflow_id = canonical_workflow_id(str(workflow)) if workflow else None
        reports = _get_runtime().report_store.list_reports(workflow_id)
        return {"reports": [report.to_dict() for report in reports]}
    if operation == "analysis.health.get":
        return {"health": _get_runtime().project_health()}
    if operation == "job.submit":
        payload = params.get("input") or {}
        summary = params.get("input_summary") or {}
        if not isinstance(payload, dict) or not isinstance(summary, dict):
            raise ValueError("job input and input_summary must be objects")
        job = _get_runtime().jobs.submit(
            kind=str(params.get("kind") or ""),
            input_payload=payload,
            input_summary=summary,
            idempotency_key=(
                str(params["idempotency_key"])
                if params.get("idempotency_key")
                else None
            ),
            idempotent=bool(params.get("idempotent", True)),
            max_retries=int(params.get("max_retries", 1)),
        )
        return {"job": job.to_dict()}
    if operation == "job.status":
        return {"job": _get_runtime().jobs.status(str(params["job_id"])).to_dict()}
    if operation == "job.result":
        return {"job": _get_runtime().jobs.result(str(params["job_id"])).to_dict()}
    if operation == "job.cancel":
        return {"job": _get_runtime().jobs.cancel(str(params["job_id"])).to_dict()}
    if operation == "job.list":
        jobs = _get_runtime().jobs.list(
            kind=str(params["kind"]) if params.get("kind") else None,
            status=str(params["status"]) if params.get("status") else None,
            limit=int(params.get("limit", 100)),
            offset=int(params.get("offset", 0)),
        )
        return {"jobs": [job.to_dict() for job in jobs]}
    raise ValueError(f"unsupported Runtime operation: {operation}")


def _runtime_capabilities() -> dict:
    return {
        "canonical_project_state": True,
        "observation_store": True,
        "report_store": True,
        "workflow_registry": True,
        "project_health": True,
        "workflow_execution": True,
        "durable_jobs": True,
    }


class _PayloadWatcherProvider:
    def __init__(self, *, status: dict, last_max: dict) -> None:
        self._status = status
        self._last_max = last_max

    def status(self) -> dict:
        return dict(self._status)

    def last_max(self) -> dict[int, float]:
        return {int(key): float(value) for key, value in self._last_max.items()}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        logger.debug("client connected: %s", self.client_address)
        try:
            for raw in self.rfile:  # one request per line
                line = raw.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line.decode("utf-8"))
                except Exception as e:
                    resp = {"ok": False, "exc": "Error", "error": f"bad json: {e}"}
                else:
                    resp = _handle_request(req)
                self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
                self.wfile.flush()
        except Exception:  # pragma: no cover - defensive
            logger.exception("handler error")
        finally:
            logger.debug("client disconnected: %s", self.client_address)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("FLS_PILOT_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("FLS_PILOT_TCP_HOST", DEFAULT_TCP_HOST)
    port = int(os.environ.get("FLS_PILOT_TCP_PORT", DEFAULT_TCP_PORT))

    # Pre-open so port problems surface in the log immediately. Non-fatal:
    # health/call retry until the ports exist.
    try:
        _get_bridge()
        logger.info("MIDI bridge open.")
    except FLPortMissing as e:
        logger.warning("MIDI ports not ready yet: %s", e)
        logger.warning(
            "Create the loopMIDI ports and start FL; the daemon "
            "will pick them up on the next request."
        )

    try:
        server = _Server((host, port), _Handler)
    except OSError as exc:
        fallback = find_available_tcp_port(host, port + 1)
        logger.error(
            "Could not bind daemon on %s:%d: %s. Try FLS_PILOT_TCP_PORT=%d.",
            host,
            port,
            exc,
            fallback,
        )
        raise
    logger.info("fls-pilot daemon %s listening on %s:%d", __version__, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.shutdown()
        server.server_close()
        _get_runtime().close(wait=False)


if __name__ == "__main__":
    main()
